/* A ClutterEffect that draws a Shadertoy fragment shader.
 *
 * A ClutterEffect, deliberately, and not a ClutterShaderEffect.
 * ClutterShaderEffect derives from ClutterOffscreenEffect, whose
 * pre_paint ties the target size to the paint volume, the viewport to the
 * target size and the modelview to the ratio between them. Viewport and
 * modelview cancel, so the pixel density is nailed to the stage's and
 * rendering at a lower resolution is not merely awkward but impossible. A
 * plain ClutterEffect derives nothing and picks all three itself.
 *
 * The shader is drawn into an offscreen buffer here, immediately, rather
 * than left to a nested ClutterLayerNode the way the JavaScript version did
 * it. Two things fall out of that. The draw is ours to bracket, which is
 * what makes the GPU timer possible at all; and it only has to happen when
 * something moved, so the stage repainting for reasons of its own — a
 * notification, a cursor, damage from a window above — costs one textured
 * quad instead of a whole frame of the shader.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "shaderbg-effect.h"
#include "shaderbg-gpu-timer.h"

/* All the work is in _sb_fragment, which the prelude declares above the
 * shader source where the shader's own macros cannot rewrite it. A snippet
 * body is emitted after the shader text, so every #define the shader made is
 * still in force over these two lines — hence the one call, under a name no
 * shader will have taken. */
#define SNIPPET_BODY "  cogl_color_out = _sb_fragment();\n"

/* Enough to outlive any query still in flight, so a finished one can always
 * find the CPU side of its own frame again. */
#define PENDING 8

typedef struct
{
  guint32 serial;
  gint64  build_us;
  gint64  latency_us;
  gint64  draw_us;     /* when the draw was issued, to subtract later */
  gint64  present_us;  /* from that draw to the stage reaching the screen */
} Pending;

struct _ShaderBgEffect
{
  ClutterEffect parent_instance;

  /* The backend's context, which outlives every effect on it. Cogl has no
   * getter to recover it from a pipeline, so it is kept here. */
  CoglContext   *context;

  CoglPipeline  *pipeline;   /* draws the shader into the buffer */
  CoglPipeline  *present;    /* draws the buffer onto the actor */

  CoglTexture   *texture;
  CoglOffscreen *framebuffer;
  int            buffer_width;
  int            buffer_height;

  float          scale;

  /* What the shader composes for. The buffer is sized from this and not from
   * the actor, so the overview zooming a workspace preview moves only the
   * rectangle the finished texture is stretched over. */
  int            res_width;
  int            res_height;

  GHashTable    *locations;  /* uniform name -> location + 1 */

  /* The shader is redrawn only when this is set, which a uniform change or a
   * new buffer does. */
  gboolean       dirty;

  guint32        serial;
  gint64         tick_us;

  gboolean       tracing;
  ShaderBgGpuTimer *timer;
  Pending        pending[PENDING];

  /* ClutterStage::presented carries a ClutterFrameInfo, which is a public
   * struct in C and has no GI boxed type, so the signal is marked
   * introspectable=0 and GJS cannot reach it at all. Reading the moment a
   * frame actually lands on the screen is therefore something only this side
   * of the library can do. */
  ClutterActor  *stage;
  gulong         presented_id;
  guint32        awaiting_present;
};

G_DEFINE_FINAL_TYPE (ShaderBgEffect, shaderbg_effect, CLUTTER_TYPE_EFFECT)

enum
{
  SIGNAL_FRAME,
  N_SIGNALS
};

static guint signals[N_SIGNALS];

/* ---- the offscreen buffer ---------------------------------------------- */

static void
drop_buffer (ShaderBgEffect *self)
{
  g_clear_object (&self->framebuffer);
  g_clear_object (&self->texture);
  self->buffer_width = 0;
  self->buffer_height = 0;
}

static gboolean
ensure_buffer (ShaderBgEffect *self)
{
  CoglContext *context;
  graphene_matrix_t projection;
  int w = MAX (1, (int) (self->res_width * self->scale));
  int h = MAX (1, (int) (self->res_height * self->scale));

  if (self->framebuffer != NULL &&
      self->buffer_width == w && self->buffer_height == h)
    return TRUE;

  drop_buffer (self);

  context = self->context;

  self->texture = cogl_texture_2d_new_with_size (context, w, h);
  if (self->texture == NULL)
    return FALSE;

  self->framebuffer = cogl_offscreen_new_with_texture (self->texture);
  if (self->framebuffer == NULL)
    {
      drop_buffer (self);
      return FALSE;
    }

  /* The buffer's own coordinate space: 0..w across, 0..h down. Picking this
   * is the whole point of deriving from ClutterEffect. */
  graphene_matrix_init_translate (&projection,
                                  &GRAPHENE_POINT3D_INIT (-w / 2.0f, -h / 2.0f, 0.0f));
  graphene_matrix_scale (&projection, 2.0f / w, -2.0f / h, 1.0f);

  cogl_framebuffer_set_projection_matrix (COGL_FRAMEBUFFER (self->framebuffer),
                                          &projection);
  cogl_framebuffer_set_viewport (COGL_FRAMEBUFFER (self->framebuffer),
                                 0, 0, w, h);

  cogl_pipeline_set_layer_texture (self->present, 0, self->texture);

  self->buffer_width = w;
  self->buffer_height = h;

  /* A buffer nobody has drawn into yet holds whatever the driver left in it. */
  self->dirty = TRUE;

  return TRUE;
}

/* ---- presentation -------------------------------------------------------- */

static void
on_stage_presented (ClutterActor     *stage G_GNUC_UNUSED,
                    gpointer          view G_GNUC_UNUSED,
                    ClutterFrameInfo *info,
                    gpointer          user_data)
{
  ShaderBgEffect *self = user_data;
  Pending *p;

  if (info == NULL || self->awaiting_present == 0)
    return;

  p = &self->pending[self->awaiting_present % PENDING];
  if (p->serial != self->awaiting_present)
    return;

  /* On more than one monitor this is whichever view presented first, which
   * is the earliest the frame could have been seen rather than when this
   * actor's own screen showed it. */
  p->present_us = info->presentation_time - p->draw_us;
  self->awaiting_present = 0;
}

static void
ensure_stage_connection (ShaderBgEffect *self,
                         ClutterActor   *actor)
{
  ClutterActor *stage = clutter_actor_get_stage (actor);

  if (stage == self->stage)
    return;

  if (self->stage != NULL)
    g_clear_signal_handler (&self->presented_id, self->stage);

  self->stage = stage;

  if (stage != NULL)
    self->presented_id = g_signal_connect (stage, "presented",
                                           G_CALLBACK (on_stage_presented), self);
}

/* ---- timing ------------------------------------------------------------- */

static void
drain_timer (ShaderBgEffect *self)
{
  guint32 serial;
  guint64 ns;

  if (self->timer == NULL)
    return;

  while (shaderbg_gpu_timer_poll (self->timer, &serial, &ns))
    {
      Pending *p = &self->pending[serial % PENDING];

      /* The slot was reused while this query was still out, which only
       * happens if the GPU fell PENDING frames behind. The GPU figure is
       * still good; the CPU side of that frame is gone. */
      gboolean matched = (p->serial == serial);

      g_signal_emit (self, signals[SIGNAL_FRAME], 0,
                     serial,
                     matched ? p->latency_us / 1000.0 : -1.0,
                     matched ? p->build_us / 1000.0 : -1.0,
                     ns / 1000000.0,
                     matched && p->present_us > 0 ? p->present_us / 1000.0 : -1.0);
    }
}

static void
render_shader (ShaderBgEffect *self)
{
  CoglFramebuffer *fb = COGL_FRAMEBUFFER (self->framebuffer);
  gboolean timed = FALSE;
  gint64 start;

  self->serial++;
  start = g_get_monotonic_time ();

  if (self->tracing && self->timer != NULL)
    {
      /* Whatever Cogl has already journalled has to be on its way to the GPU
       * before the query opens, or it lands inside the bracket and is
       * counted as this shader's work. */
      cogl_framebuffer_flush (fb);
      timed = shaderbg_gpu_timer_begin (self->timer, self->serial);
    }

  cogl_framebuffer_draw_rectangle (fb, self->pipeline,
                                   0.0f, 0.0f,
                                   (float) self->buffer_width,
                                   (float) self->buffer_height);

  if (timed)
    {
      /* And the draw has to be out before the query closes, or Cogl's
       * journal holds it back and the query times an empty bracket. flush,
       * not finish: this submits without stalling the CPU on the result. */
      cogl_framebuffer_flush (fb);
      shaderbg_gpu_timer_end (self->timer);
    }

  self->dirty = FALSE;

  if (self->tracing)
    {
      Pending *p = &self->pending[self->serial % PENDING];

      p->serial = self->serial;
      p->build_us = g_get_monotonic_time () - start;
      p->latency_us = self->tick_us != 0 ? start - self->tick_us : -1;
      p->draw_us = start;
      p->present_us = -1;

      self->awaiting_present = self->serial;
    }
}

/* ---- painting ----------------------------------------------------------- */

static void
shaderbg_effect_paint_node (ClutterEffect           *effect,
                            ClutterPaintNode        *node,
                            ClutterPaintContext     *paint_context G_GNUC_UNUSED,
                            ClutterEffectPaintFlags  flags G_GNUC_UNUSED)
{
  ShaderBgEffect *self = SHADERBG_EFFECT (effect);
  ClutterActor *actor;
  ClutterActorBox box;
  ClutterPaintNode *present_node;
  float width, height;

  actor = clutter_actor_meta_get_actor (CLUTTER_ACTOR_META (effect));
  if (actor == NULL)
    return;

  clutter_actor_get_allocation_box (actor, &box);
  width = clutter_actor_box_get_width (&box);
  height = clutter_actor_box_get_height (&box);
  if (width < 1.0f || height < 1.0f)
    return;

  /* Nothing has said what to compose for yet. A shader run with a zeroed
   * iResolution divides by it, and a raymarcher handed an infinite fragment
   * coordinate never meets its exit condition — that is a hung GPU, not a
   * wrong pixel. */
  if (self->res_width < 1 || self->res_height < 1)
    return;

  if (!ensure_buffer (self))
    return;

  if (self->tracing)
    ensure_stage_connection (self, actor);

  drain_timer (self);

  if (self->dirty)
    render_shader (self);

  /* No chain-up: the actor's own content is the wallpaper file underneath,
   * and the shader replaces it rather than covering it. */
  present_node = clutter_pipeline_node_new (self->present);
  clutter_paint_node_add_child (node, present_node);
  clutter_paint_node_add_rectangle (present_node,
                                    &(ClutterActorBox) { 0.0f, 0.0f, width, height });
  clutter_paint_node_unref (present_node);
}

/* Taken off an actor, the buffer is so much dead video memory — a 3440x1440
 * RGBA texture is 19 MB, and there is one per monitor and per workspace
 * preview. */
static void
shaderbg_effect_set_actor (ClutterActorMeta *meta,
                           ClutterActor     *actor)
{
  ShaderBgEffect *self = SHADERBG_EFFECT (meta);

  if (actor == NULL)
    {
      drop_buffer (self);

      /* Let go of the stage here rather than in dispose. Detaching is the
       * last moment the stage is certainly still alive — the effect can
       * outlive it otherwise, and a handler id disconnected from freed
       * memory is not a leak but a crash. */
      if (self->stage != NULL)
        g_clear_signal_handler (&self->presented_id, self->stage);
      self->stage = NULL;
    }

  CLUTTER_ACTOR_META_CLASS (shaderbg_effect_parent_class)->set_actor (meta, actor);
}

static void
shaderbg_effect_dispose (GObject *object)
{
  ShaderBgEffect *self = SHADERBG_EFFECT (object);

  if (self->stage != NULL)
    g_clear_signal_handler (&self->presented_id, self->stage);
  self->stage = NULL;

  drop_buffer (self);
  g_clear_pointer (&self->timer, shaderbg_gpu_timer_free);
  g_clear_pointer (&self->locations, g_hash_table_unref);
  g_clear_object (&self->pipeline);
  g_clear_object (&self->present);

  G_OBJECT_CLASS (shaderbg_effect_parent_class)->dispose (object);
}

static void
shaderbg_effect_class_init (ShaderBgEffectClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  ClutterActorMetaClass *meta_class = CLUTTER_ACTOR_META_CLASS (klass);
  ClutterEffectClass *effect_class = CLUTTER_EFFECT_CLASS (klass);

  object_class->dispose = shaderbg_effect_dispose;
  meta_class->set_actor = shaderbg_effect_set_actor;
  effect_class->paint_node = shaderbg_effect_paint_node;

  /**
   * ShaderBgEffect::frame:
   * @self: the effect
   * @serial: which redraw this is about
   * @latency_ms: from the tick asking for a frame to the shader being drawn,
   *   or -1 when it could not be paired up
   * @build_ms: CPU time spent issuing the draw
   * @gpu_ms: GPU time the shader itself took
   * @present_ms: from that draw to the stage reaching the screen, or -1
   *   when the presentation could not be paired up
   *
   * Emitted once per timed redraw, a frame or two after it happened —
   * a timer query is answered when the GPU gets round to it, not when the
   * draw was issued. Only emitted while tracing is on.
   */
  signals[SIGNAL_FRAME] =
    g_signal_new ("frame",
                  SHADERBG_TYPE_EFFECT,
                  G_SIGNAL_RUN_LAST,
                  0, NULL, NULL, NULL,
                  G_TYPE_NONE, 5,
                  G_TYPE_UINT,
                  G_TYPE_DOUBLE,
                  G_TYPE_DOUBLE,
                  G_TYPE_DOUBLE,
                  G_TYPE_DOUBLE);
}

static void
shaderbg_effect_init (ShaderBgEffect *self)
{
  self->scale = 1.0f;
  self->dirty = TRUE;
  self->locations = g_hash_table_new_full (g_str_hash, g_str_equal, g_free, NULL);
}

/* ---- public ------------------------------------------------------------- */

ShaderBgEffect *
shaderbg_effect_new (const char  *source,
                     CoglTexture *noise)
{
  ShaderBgEffect *self;
  CoglContext *context;
  CoglSnippet *snippet;

  g_return_val_if_fail (source != NULL, NULL);
  g_return_val_if_fail (noise != NULL, NULL);

  self = g_object_new (SHADERBG_TYPE_EFFECT, NULL);

  context = cogl_texture_get_context (noise);
  self->context = context;

  /* The hook runs after Cogl's own fragment code and overwrites
   * cogl_color_out, which is why the prelude may safely #define names Cogl's
   * generated code does not use. */
  self->pipeline = cogl_pipeline_new (context);
  snippet = cogl_snippet_new (COGL_SNIPPET_HOOK_FRAGMENT, source, SNIPPET_BODY);
  cogl_pipeline_add_snippet (self->pipeline, snippet);
  g_object_unref (snippet);

  /* Layers 0..3 are iChannel0..3. They are set even for shaders that read
   * none of them: layer 0 existing is what makes Cogl emit
   * cogl_tex_coord0_in, which is where the fragment coordinate comes from. */
  for (int i = 0; i < 4; i++)
    {
      cogl_pipeline_set_layer_texture (self->pipeline, i, noise);
      cogl_pipeline_set_layer_wrap_mode (self->pipeline, i,
                                         COGL_PIPELINE_WRAP_MODE_REPEAT);
    }

  /* Linear filtering is what turns a half-resolution buffer into a soft
   * picture rather than a blocky one; for the kind of shader that gets
   * downscaled — clouds, fluids, raymarched fog — the difference is close to
   * invisible. */
  self->present = cogl_pipeline_new (context);
  cogl_pipeline_set_layer_filters (self->present, 0,
                                   COGL_PIPELINE_FILTER_LINEAR,
                                   COGL_PIPELINE_FILTER_LINEAR);
  cogl_pipeline_set_layer_wrap_mode (self->present, 0,
                                     COGL_PIPELINE_WRAP_MODE_CLAMP_TO_EDGE);

  self->timer = shaderbg_gpu_timer_new ();

  shaderbg_effect_set_uniform (self, "iChannelSize",
                               cogl_texture_get_width (noise));

  return self;
}

float
shaderbg_effect_get_render_scale (ShaderBgEffect *self)
{
  g_return_val_if_fail (SHADERBG_IS_EFFECT (self), 1.0f);

  return self->scale;
}

void
shaderbg_effect_set_render_scale (ShaderBgEffect *self,
                                  float           scale)
{
  g_return_if_fail (SHADERBG_IS_EFFECT (self));

  if (scale == self->scale)
    return;

  self->scale = scale;
  drop_buffer (self);
  clutter_effect_queue_repaint (CLUTTER_EFFECT (self));
}

void
shaderbg_effect_set_uniform (ShaderBgEffect *self,
                             const char     *name,
                             float           value)
{
  gpointer cached;
  int location;

  g_return_if_fail (SHADERBG_IS_EFFECT (self));
  g_return_if_fail (name != NULL);

  /* Cogl addresses uniforms by location rather than by name, and the lookup
   * is a string hash into a per-context table — worth doing once per name
   * rather than once per frame. Stored as location + 1 so that a location of
   * 0 is not mistaken for a miss. */
  cached = g_hash_table_lookup (self->locations, name);
  if (cached != NULL)
    {
      location = GPOINTER_TO_INT (cached) - 1;
    }
  else
    {
      location = cogl_pipeline_get_uniform_location (self->pipeline, name);
      g_hash_table_insert (self->locations, g_strdup (name),
                           GINT_TO_POINTER (location + 1));
    }

  cogl_pipeline_set_uniform_1f (self->pipeline, location, value);
  self->dirty = TRUE;
}

void
shaderbg_effect_mark_tick (ShaderBgEffect *self,
                           gint64          monotonic_us)
{
  g_return_if_fail (SHADERBG_IS_EFFECT (self));

  self->tick_us = monotonic_us;
}

gboolean
shaderbg_effect_get_tracing (ShaderBgEffect *self)
{
  g_return_val_if_fail (SHADERBG_IS_EFFECT (self), FALSE);

  return self->tracing;
}

void
shaderbg_effect_set_tracing (ShaderBgEffect *self,
                             gboolean        tracing)
{
  g_return_if_fail (SHADERBG_IS_EFFECT (self));

  self->tracing = tracing;
}

gboolean
shaderbg_effect_has_gpu_timer (ShaderBgEffect *self)
{
  g_return_val_if_fail (SHADERBG_IS_EFFECT (self), FALSE);

  return self->timer != NULL;
}

void
shaderbg_effect_set_resolution (ShaderBgEffect *self,
                                int             width,
                                int             height)
{
  g_return_if_fail (SHADERBG_IS_EFFECT (self));

  if (width == self->res_width && height == self->res_height)
    return;

  self->res_width = width;
  self->res_height = height;

  /* Clamped on the way in as well as in the prelude: a zero here would size
   * the buffer to one pixel and hand the shader a division by nothing. */
  shaderbg_effect_set_uniform (self, "iResX", MAX (1, width));
  shaderbg_effect_set_uniform (self, "iResY", MAX (1, height));

  drop_buffer (self);
  clutter_effect_queue_repaint (CLUTTER_EFFECT (self));
}
