/* Decodes one video file, looping, into textures the effect can draw.
 *
 * The decode runs in this process, inside the Shell, through playbin. That
 * picks the VA-API decoders on its own — they rank above libav — so the
 * work lands on the GPU's video engine and not on the shader cores. What
 * comes back is NV12 in system memory: a full-size luma plane and a
 * half-size interleaved chroma plane, uploaded as two textures (R and RG)
 * and turned into RGB by a snippet. That is a 1.5-byte-per-pixel upload,
 * against 4 for RGBA, and no colour conversion on the CPU at all.
 *
 * Frames arrive on GStreamer's streaming thread and are only ever handed
 * over there. Cogl belongs to the main thread, so the upload waits for the
 * effect to be painted — and a background nobody can see, because a window
 * covers it and Mutter culled it, costs a decode and nothing else.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "wpebg-player.h"

#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>

/* playbin's GstPlayFlags, which is not in any installed header. Video only,
 * so an audio track is never even decoded, and native-video so playbin does
 * not add a converter of its own in front of ours. */
#define PLAY_FLAG_VIDEO        (1 << 0)
#define PLAY_FLAG_NATIVE_VIDEO (1 << 6)

#define SNIPPET_DECLARATIONS \
  "uniform mat3 wpebg_yuv_matrix;\n" \
  "uniform vec3 wpebg_yuv_offset;\n"

/* Both planes are sampled at layer 0's coordinate: the chroma plane is half
 * the size, but normalised coordinates do not care. */
#define SNIPPET_BODY \
  "  vec2 st = cogl_tex_coord0_in.st;\n" \
  "  vec3 yuv = vec3 (texture2D (cogl_sampler0, st).r,\n" \
  "                   texture2D (cogl_sampler1, st).rg) - wpebg_yuv_offset;\n" \
  "  cogl_color_out = vec4 (clamp (wpebg_yuv_matrix * yuv, 0.0, 1.0), 1.0);\n"

struct _WpeBgPlayer
{
  GObject parent_instance;

  CoglContext  *context;
  CoglPipeline *pipeline;
  CoglTexture  *luma;
  CoglTexture  *chroma;
  GstCaps      *caps;      /* what the textures were last sized from */
  float         aspect;

  GstElement   *playbin;
  guint         bus_watch;
  gboolean      loop_armed;

  char         *uri;
  gboolean      playing;

  /* Shared with the streaming thread. */
  GMutex        lock;
  GstSample    *pending;
  guint         notify_id;
};

G_DEFINE_FINAL_TYPE (WpeBgPlayer, wpebg_player, G_TYPE_OBJECT)

enum
{
  SIGNAL_FRAME,
  SIGNAL_ERROR,
  N_SIGNALS
};

static guint signals[N_SIGNALS];

/* ---- getting GStreamer ready -------------------------------------------- */

/* The Shell's wrapper puts core, base and good on the plugin path, which is
 * enough for its own screencast and not for this: the VA decoders and the
 * H.264/H.265 parsers are in bad, the software fallback is libav. The build
 * bakes their directories in.
 *
 * Scanning them is file I/O and, the first time, loading every plugin to
 * read it — seconds the compositor must not spend frozen. So it happens on a
 * worker thread, once per process, and the pipeline is built when it is
 * done. */
static gpointer
setup_gstreamer (gpointer data G_GNUC_UNUSED)
{
  g_autoptr (GError) error = NULL;
  g_auto (GStrv) dirs = NULL;

  if (!gst_init_check (NULL, NULL, &error))
    {
      g_warning ("wpebg: cannot initialise GStreamer: %s", error->message);
      return GINT_TO_POINTER (FALSE);
    }

  dirs = g_strsplit (WPEBG_PLUGIN_PATH, ":", -1);
  for (char **dir = dirs; *dir != NULL; dir++)
    if (**dir != '\0')
      gst_registry_scan_path (gst_registry_get (), *dir);

  return GINT_TO_POINTER (TRUE);
}

static void
setup_thread (GTask        *task,
              gpointer      source G_GNUC_UNUSED,
              gpointer      data G_GNUC_UNUSED,
              GCancellable *cancellable G_GNUC_UNUSED)
{
  static GOnce once = G_ONCE_INIT;

  g_task_return_boolean (task,
                         GPOINTER_TO_INT (g_once (&once, setup_gstreamer, NULL)));
}

/* ---- the streaming thread's side ---------------------------------------- */

static gboolean
notify_frame (gpointer data)
{
  WpeBgPlayer *self = data;

  g_mutex_lock (&self->lock);
  self->notify_id = 0;
  g_mutex_unlock (&self->lock);

  g_signal_emit (self, signals[SIGNAL_FRAME], 0);

  return G_SOURCE_REMOVE;
}

/* Only the newest frame is kept. If the main thread fell behind, the one it
 * missed is simply gone — a wallpaper has no reason to catch up. */
static void
hand_over (WpeBgPlayer *self,
           GstSample   *sample)
{
  g_mutex_lock (&self->lock);

  g_clear_pointer (&self->pending, gst_sample_unref);
  self->pending = sample;

  /* No reference is taken for the idle. dispose stops the pipeline, which
   * joins this thread, and then removes the idle under the same lock. */
  if (self->notify_id == 0)
    self->notify_id = g_idle_add (notify_frame, self);

  g_mutex_unlock (&self->lock);
}

static GstFlowReturn
on_new_sample (GstAppSink *sink,
               gpointer    data)
{
  GstSample *sample = gst_app_sink_pull_sample (sink);

  if (sample != NULL)
    hand_over (data, sample);

  return GST_FLOW_OK;
}

/* The first frame, before playback starts — so a player that is told to
 * stay paused still has a picture to show. */
static GstFlowReturn
on_new_preroll (GstAppSink *sink,
                gpointer    data)
{
  GstSample *sample = gst_app_sink_pull_preroll (sink);

  if (sample != NULL)
    hand_over (data, sample);

  return GST_FLOW_OK;
}

/* ---- the main thread's side --------------------------------------------- */

static void
drop_textures (WpeBgPlayer *self)
{
  g_clear_object (&self->luma);
  g_clear_object (&self->chroma);
  g_clear_pointer (&self->caps, gst_caps_unref);
}

static void
clear_pending (WpeBgPlayer *self)
{
  g_mutex_lock (&self->lock);
  g_clear_pointer (&self->pending, gst_sample_unref);
  g_mutex_unlock (&self->lock);
}

/* YCbCr to RGB for whatever the stream says it is. Wallpaper Engine videos
 * are nearly all BT.709 at limited range, but not all of them, and getting
 * it wrong is a washed-out or crushed picture rather than an error.
 * GstVideoInfo already filled in the default by resolution when the stream
 * said nothing. */
static void
set_colorimetry (WpeBgPlayer        *self,
                 const GstVideoInfo *info)
{
  double kr, kb, kg, max, sy, sc;
  int offsets[GST_VIDEO_MAX_COMPONENTS];
  int scales[GST_VIDEO_MAX_COMPONENTS];
  float offset[3];
  float matrix[9];

  if (!gst_video_color_matrix_get_Kr_Kb (info->colorimetry.matrix, &kr, &kb))
    {
      kr = 0.2126;
      kb = 0.0722;
    }
  kg = 1.0 - kr - kb;

  gst_video_color_range_offsets (info->colorimetry.range, info->finfo,
                                 offsets, scales);

  max = (1 << GST_VIDEO_INFO_COMP_DEPTH (info, 0)) - 1;
  sy = max / scales[0];
  sc = max / scales[1];

  for (int i = 0; i < 3; i++)
    offset[i] = offsets[i] / max;

  /* Column-major, one column per input: Y, Cb, Cr. */
  matrix[0] = sy;
  matrix[1] = sy;
  matrix[2] = sy;

  matrix[3] = 0.0f;
  matrix[4] = -2.0 * (1.0 - kb) * kb / kg * sc;
  matrix[5] = 2.0 * (1.0 - kb) * sc;

  matrix[6] = 2.0 * (1.0 - kr) * sc;
  matrix[7] = -2.0 * (1.0 - kr) * kr / kg * sc;
  matrix[8] = 0.0f;

  cogl_pipeline_set_uniform_matrix (self->pipeline,
                                    cogl_pipeline_get_uniform_location (self->pipeline,
                                                                        "wpebg_yuv_matrix"),
                                    3, 1, FALSE, matrix);
  cogl_pipeline_set_uniform_float (self->pipeline,
                                   cogl_pipeline_get_uniform_location (self->pipeline,
                                                                       "wpebg_yuv_offset"),
                                   3, 1, offset);
}

static gboolean
ensure_textures (WpeBgPlayer        *self,
                 GstCaps            *caps,
                 const GstVideoInfo *info)
{
  int width = GST_VIDEO_INFO_WIDTH (info);
  int height = GST_VIDEO_INFO_HEIGHT (info);

  if (self->caps != NULL && gst_caps_is_equal (self->caps, caps))
    return TRUE;

  drop_textures (self);

  self->luma = cogl_texture_2d_new_with_format (self->context, width, height,
                                                COGL_PIXEL_FORMAT_R_8);
  self->chroma = cogl_texture_2d_new_with_format (self->context,
                                                  GST_VIDEO_INFO_COMP_WIDTH (info, 1),
                                                  GST_VIDEO_INFO_COMP_HEIGHT (info, 1),
                                                  COGL_PIXEL_FORMAT_RG_88);
  if (self->luma == NULL || self->chroma == NULL)
    {
      drop_textures (self);
      return FALSE;
    }

  cogl_pipeline_set_layer_texture (self->pipeline, 0, self->luma);
  cogl_pipeline_set_layer_texture (self->pipeline, 1, self->chroma);

  set_colorimetry (self, info);

  self->aspect = (float) (width * (double) GST_VIDEO_INFO_PAR_N (info)) /
                 (float) (height * (double) MAX (1, GST_VIDEO_INFO_PAR_D (info)));
  self->caps = gst_caps_ref (caps);

  return TRUE;
}

static void
upload (WpeBgPlayer *self,
        GstSample   *sample)
{
  g_autoptr (GError) error = NULL;
  GstCaps *caps = gst_sample_get_caps (sample);
  GstBuffer *buffer = gst_sample_get_buffer (sample);
  GstVideoInfo info;
  GstVideoFrame frame;

  if (caps == NULL || buffer == NULL || !gst_video_info_from_caps (&info, caps))
    return;

  if (GST_VIDEO_INFO_FORMAT (&info) != GST_VIDEO_FORMAT_NV12)
    return;

  if (!ensure_textures (self, caps, &info))
    return;

  if (!gst_video_frame_map (&frame, &info, buffer, GST_MAP_READ))
    return;

  if (!cogl_texture_set_data (self->luma, COGL_PIXEL_FORMAT_R_8,
                              GST_VIDEO_FRAME_PLANE_STRIDE (&frame, 0),
                              GST_VIDEO_FRAME_PLANE_DATA (&frame, 0),
                              0, &error) ||
      !cogl_texture_set_data (self->chroma, COGL_PIXEL_FORMAT_RG_88,
                              GST_VIDEO_FRAME_PLANE_STRIDE (&frame, 1),
                              GST_VIDEO_FRAME_PLANE_DATA (&frame, 1),
                              0, &error))
    g_warning ("wpebg: cannot upload a frame: %s", error->message);

  gst_video_frame_unmap (&frame);
}

/* ---- looping ------------------------------------------------------------ */

/* A segment seek, not a seek on EOS. A flushing seek back to the start
 * throws the pipeline away and prerolls it again, which is a visible hitch
 * at every loop; a segment seek posts SEGMENT_DONE instead of EOS and the
 * next pass is queued without flushing anything, so the loop is seamless. */
static void
seek_to_start (WpeBgPlayer *self,
               gboolean     flush)
{
  GstSeekFlags flags = GST_SEEK_FLAG_SEGMENT;

  if (flush)
    flags |= GST_SEEK_FLAG_FLUSH;

  gst_element_seek (self->playbin, 1.0, GST_FORMAT_TIME, flags,
                    GST_SEEK_TYPE_SET, 0,
                    GST_SEEK_TYPE_NONE, GST_CLOCK_TIME_NONE);
}

static gboolean
on_bus_message (GstBus     *bus G_GNUC_UNUSED,
                GstMessage *message,
                gpointer    data)
{
  WpeBgPlayer *self = data;

  switch (GST_MESSAGE_TYPE (message))
    {
    case GST_MESSAGE_ERROR:
      {
        g_autoptr (GError) error = NULL;
        g_autofree char *debug = NULL;

        gst_message_parse_error (message, &error, &debug);
        g_debug ("wpebg: %s", debug);

        gst_element_set_state (self->playbin, GST_STATE_NULL);
        g_signal_emit (self, signals[SIGNAL_ERROR], 0, error->message);
        break;
      }

    /* A segment seek only works on a pipeline that has prerolled, so the
     * first one waits for that. */
    case GST_MESSAGE_ASYNC_DONE:
      if (GST_MESSAGE_SRC (message) == GST_OBJECT (self->playbin) &&
          self->loop_armed)
        {
          self->loop_armed = FALSE;
          seek_to_start (self, TRUE);
        }
      break;

    case GST_MESSAGE_SEGMENT_DONE:
      seek_to_start (self, FALSE);
      break;

    /* Only if the segment seek did not take, which a demuxer that cannot
     * seek would do. Looping with a hitch beats stopping. */
    case GST_MESSAGE_EOS:
      seek_to_start (self, TRUE);
      break;

    default:
      break;
    }

  return G_SOURCE_CONTINUE;
}

/* ---- the pipeline ------------------------------------------------------- */

static void
apply (WpeBgPlayer *self)
{
  if (self->playbin == NULL)
    return;

  gst_element_set_state (self->playbin, GST_STATE_NULL);
  clear_pending (self);

  if (self->uri == NULL)
    {
      drop_textures (self);
      return;
    }

  g_object_set (self->playbin, "uri", self->uri, NULL);
  self->loop_armed = TRUE;

  gst_element_set_state (self->playbin,
                         self->playing ? GST_STATE_PLAYING : GST_STATE_PAUSED);
}

static gboolean
build_pipeline (WpeBgPlayer *self)
{
  GstAppSinkCallbacks callbacks = {
    .new_preroll = on_new_preroll,
    .new_sample = on_new_sample,
  };
  g_autoptr (GstCaps) caps = NULL;
  g_autoptr (GstPad) pad = NULL;
  g_autoptr (GstBus) bus = NULL;
  GstElement *bin, *convert, *sink;

  self->playbin = gst_element_factory_make ("playbin", NULL);
  convert = gst_element_factory_make ("videoconvert", NULL);
  sink = gst_element_factory_make ("appsink", NULL);

  if (self->playbin == NULL || convert == NULL || sink == NULL)
    {
      g_warning ("wpebg: GStreamer is missing playbin, videoconvert or appsink");
      g_clear_pointer (&self->playbin, gst_object_unref);
      g_clear_pointer (&convert, gst_object_unref);
      g_clear_pointer (&sink, gst_object_unref);
      return FALSE;
    }

  gst_object_ref_sink (self->playbin);

  /* NV12 is what the VA decoders hand out for 8-bit video, so the convert
   * is a passthrough for nearly everything. It is there for the rest: a
   * software decoder's I420, or a 10-bit stream's P010. */
  caps = gst_caps_from_string ("video/x-raw, format=NV12");
  g_object_set (sink,
                "caps", caps,
                "sync", TRUE,
                "qos", TRUE,
                "max-buffers", 1,
                "drop", TRUE,
                "enable-last-sample", FALSE,
                NULL);
  gst_app_sink_set_callbacks (GST_APP_SINK (sink), &callbacks, self, NULL);

  bin = gst_bin_new ("wpebg-sink");
  gst_bin_add_many (GST_BIN (bin), convert, sink, NULL);
  gst_element_link (convert, sink);

  pad = gst_element_get_static_pad (convert, "sink");
  gst_element_add_pad (bin, gst_ghost_pad_new ("sink", pad));

  g_object_set (self->playbin,
                "video-sink", bin,
                "flags", PLAY_FLAG_VIDEO | PLAY_FLAG_NATIVE_VIDEO,
                "mute", TRUE,
                NULL);

  bus = gst_element_get_bus (self->playbin);
  self->bus_watch = gst_bus_add_watch (bus, on_bus_message, self);

  return TRUE;
}

static void
on_setup_done (GObject      *source,
               GAsyncResult *result,
               gpointer      data G_GNUC_UNUSED)
{
  WpeBgPlayer *self = WPEBG_PLAYER (source);

  if (!g_task_propagate_boolean (G_TASK (result), NULL))
    return;

  if (build_pipeline (self))
    apply (self);
}

/* ---- GObject ------------------------------------------------------------ */

static void
wpebg_player_dispose (GObject *object)
{
  WpeBgPlayer *self = WPEBG_PLAYER (object);

  if (self->bus_watch != 0)
    g_source_remove (self->bus_watch);
  self->bus_watch = 0;

  /* NULL joins the streaming threads, so after this nothing hands over a
   * frame or adds an idle any more. */
  if (self->playbin != NULL)
    gst_element_set_state (self->playbin, GST_STATE_NULL);
  g_clear_pointer (&self->playbin, gst_object_unref);

  g_mutex_lock (&self->lock);
  g_clear_pointer (&self->pending, gst_sample_unref);
  g_clear_handle_id (&self->notify_id, g_source_remove);
  g_mutex_unlock (&self->lock);

  drop_textures (self);
  g_clear_object (&self->pipeline);

  G_OBJECT_CLASS (wpebg_player_parent_class)->dispose (object);
}

static void
wpebg_player_finalize (GObject *object)
{
  WpeBgPlayer *self = WPEBG_PLAYER (object);

  g_free (self->uri);
  g_mutex_clear (&self->lock);

  G_OBJECT_CLASS (wpebg_player_parent_class)->finalize (object);
}

static void
wpebg_player_class_init (WpeBgPlayerClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);

  object_class->dispose = wpebg_player_dispose;
  object_class->finalize = wpebg_player_finalize;

  /**
   * WpeBgPlayer::frame:
   * @self: the player
   *
   * A new frame is waiting to be drawn. Emitted on the main thread.
   */
  signals[SIGNAL_FRAME] =
    g_signal_new ("frame",
                  G_TYPE_FROM_CLASS (klass),
                  G_SIGNAL_RUN_LAST,
                  0, NULL, NULL, NULL,
                  G_TYPE_NONE, 0);

  /**
   * WpeBgPlayer::error:
   * @self: the player
   * @message: what GStreamer said
   *
   * Playback stopped. The last frame stays up.
   */
  signals[SIGNAL_ERROR] =
    g_signal_new ("error",
                  G_TYPE_FROM_CLASS (klass),
                  G_SIGNAL_RUN_LAST,
                  0, NULL, NULL, NULL,
                  G_TYPE_NONE, 1, G_TYPE_STRING);
}

static void
wpebg_player_init (WpeBgPlayer *self)
{
  g_mutex_init (&self->lock);
  self->aspect = 16.0f / 9.0f;
}

WpeBgPlayer *
wpebg_player_new (CoglContext *context)
{
  g_autoptr (GTask) task = NULL;
  CoglSnippet *snippet;
  WpeBgPlayer *self;

  g_return_val_if_fail (context != NULL, NULL);

  self = g_object_new (WPEBG_TYPE_PLAYER, NULL);
  self->context = context;

  self->pipeline = cogl_pipeline_new (context);
  snippet = cogl_snippet_new (COGL_SNIPPET_HOOK_FRAGMENT,
                              SNIPPET_DECLARATIONS, SNIPPET_BODY);
  cogl_pipeline_add_snippet (self->pipeline, snippet);
  g_object_unref (snippet);

  for (int layer = 0; layer < 2; layer++)
    {
      cogl_pipeline_set_layer_filters (self->pipeline, layer,
                                       COGL_PIPELINE_FILTER_LINEAR,
                                       COGL_PIPELINE_FILTER_LINEAR);
      cogl_pipeline_set_layer_wrap_mode (self->pipeline, layer,
                                         COGL_PIPELINE_WRAP_MODE_CLAMP_TO_EDGE);
    }

  task = g_task_new (self, NULL, on_setup_done, NULL);
  g_task_run_in_thread (task, setup_thread);

  return self;
}

void
wpebg_player_set_uri (WpeBgPlayer *self,
                      const char  *uri)
{
  g_return_if_fail (WPEBG_IS_PLAYER (self));

  if (g_strcmp0 (uri, self->uri) == 0)
    return;

  g_free (self->uri);
  self->uri = g_strdup (uri);

  apply (self);
}

void
wpebg_player_set_playing (WpeBgPlayer *self,
                          gboolean     playing)
{
  g_return_if_fail (WPEBG_IS_PLAYER (self));

  playing = !!playing;
  if (playing == self->playing)
    return;

  self->playing = playing;

  if (self->playbin != NULL && self->uri != NULL)
    gst_element_set_state (self->playbin,
                           playing ? GST_STATE_PLAYING : GST_STATE_PAUSED);
}

gboolean
wpebg_player_prepare (WpeBgPlayer *self)
{
  GstSample *sample;

  g_return_val_if_fail (WPEBG_IS_PLAYER (self), FALSE);

  g_mutex_lock (&self->lock);
  sample = g_steal_pointer (&self->pending);
  g_mutex_unlock (&self->lock);

  if (sample != NULL)
    {
      upload (self, sample);
      gst_sample_unref (sample);
    }

  return self->luma != NULL;
}

/**
 * wpebg_player_get_pipeline:
 * @self: the player
 *
 * Returns: (transfer none): the pipeline that draws the current frame
 */
CoglPipeline *
wpebg_player_get_pipeline (WpeBgPlayer *self)
{
  g_return_val_if_fail (WPEBG_IS_PLAYER (self), NULL);

  return self->pipeline;
}

float
wpebg_player_get_aspect (WpeBgPlayer *self)
{
  g_return_val_if_fail (WPEBG_IS_PLAYER (self), 1.0f);

  return self->aspect;
}
