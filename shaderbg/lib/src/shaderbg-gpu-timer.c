/* GPU-side timing for the shader pass.
 *
 * Why this exists at all: the frame time the extension used to work from was
 * the wall-clock gap between two paints, and that gap can never fall below the
 * refresh interval. Every shader that fitted into a frame therefore measured
 * as exactly one refresh interval, whether it had spent 1 % of it or 99 %, and
 * a budget expressed as a share of a frame had nothing to judge. A timer query
 * brackets the draw on the GPU itself, so it reports the work and not the pace.
 *
 * Cogl does not expose one. Mutter 50 carries COGL_FEATURE_ID_TIMESTAMP_QUERY
 * in its headers but no function to go with it, and there is no GL binding for
 * GJS either, which is the whole reason this library is native.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "shaderbg-gpu-timer.h"

#include <EGL/egl.h>

/* Declared here rather than pulled in from a GL header. The session runs on
 * the GLES driver, the desktop-GL one is still possible, and the two sets of
 * headers disagree about these very types — declaring the handful that are
 * used avoids having to pick. */
typedef unsigned int GLenum;
typedef unsigned int GLuint;
typedef int          GLint;
typedef int          GLsizei;
typedef guint64      GLuint64;

#define GL_TIME_ELAPSED_EXT            0x88BF
#define GL_QUERY_RESULT_EXT            0x8866
#define GL_QUERY_RESULT_AVAILABLE_EXT  0x8867
#define GL_GPU_DISJOINT_EXT            0x8FBB

typedef void (*GenQueriesFunc)        (GLsizei n, GLuint *ids);
typedef void (*DeleteQueriesFunc)     (GLsizei n, const GLuint *ids);
typedef void (*BeginQueryFunc)        (GLenum target, GLuint id);
typedef void (*EndQueryFunc)          (GLenum target);
typedef void (*GetQueryObjectuivFunc) (GLuint id, GLenum pname, GLuint *params);
typedef void (*GetQueryObjectui64vFunc) (GLuint id, GLenum pname, GLuint64 *params);
typedef void (*GetIntegervFunc)       (GLenum pname, GLint *params);

/* Four is enough to never stall: a result is normally ready one or two frames
 * after the draw, and begin() simply declines while they are all out. */
#define SLOTS 4

typedef struct
{
  GLuint  id;
  guint32 serial;
} Slot;

struct _ShaderBgGpuTimer
{
  GenQueriesFunc          gen_queries;
  DeleteQueriesFunc       delete_queries;
  BeginQueryFunc          begin_query;
  EndQueryFunc            end_query;
  GetQueryObjectuivFunc   get_query_uiv;
  GetQueryObjectui64vFunc get_query_ui64v;
  GetIntegervFunc         get_integerv;

  Slot     slots[SLOTS];
  guint    head;      /* next to be filled */
  guint    tail;      /* oldest in flight */
  guint    inflight;
  gboolean active;    /* a begin() is open; only one may be at a time */
};

static gpointer
resolve (const char *ext_name,
         const char *core_name)
{
  gpointer fn = (gpointer) eglGetProcAddress (ext_name);

  if (fn == NULL && core_name != NULL)
    fn = (gpointer) eglGetProcAddress (core_name);

  return fn;
}

ShaderBgGpuTimer *
shaderbg_gpu_timer_new (void)
{
  ShaderBgGpuTimer *self;

  /* EXT_disjoint_timer_query first, because the session is on the GLES
   * driver and that is the only spelling it has. The unsuffixed names are
   * the desktop-GL and GLES 3 ones, tried second so this keeps working if
   * the driver ever changes underneath. */
  GenQueriesFunc          gen   = resolve ("glGenQueriesEXT", "glGenQueries");
  DeleteQueriesFunc       del   = resolve ("glDeleteQueriesEXT", "glDeleteQueries");
  BeginQueryFunc          begin = resolve ("glBeginQueryEXT", "glBeginQuery");
  EndQueryFunc            end   = resolve ("glEndQueryEXT", "glEndQuery");
  GetQueryObjectuivFunc   uiv   = resolve ("glGetQueryObjectuivEXT", "glGetQueryObjectuiv");
  GetQueryObjectui64vFunc ui64v = resolve ("glGetQueryObjectui64vEXT", "glGetQueryObjectui64v");
  GetIntegervFunc         getiv = resolve ("glGetIntegerv", NULL);

  /* ui64v is the one that is genuinely optional-looking and genuinely
   * required: the 32-bit result wraps after 4.3 seconds, which is fine, but
   * it is also the entry point a driver without the extension omits while
   * still having the rest from GLES 3. No ui64v, no timing. */
  if (gen == NULL || del == NULL || begin == NULL || end == NULL ||
      uiv == NULL || ui64v == NULL || getiv == NULL)
    {
      g_debug ("shaderbg: no GPU timer query available");
      return NULL;
    }

  self = g_new0 (ShaderBgGpuTimer, 1);
  self->gen_queries     = gen;
  self->delete_queries  = del;
  self->begin_query     = begin;
  self->end_query       = end;
  self->get_query_uiv   = uiv;
  self->get_query_ui64v = ui64v;
  self->get_integerv    = getiv;

  for (guint i = 0; i < SLOTS; i++)
    self->gen_queries (1, &self->slots[i].id);

  return self;
}

void
shaderbg_gpu_timer_free (ShaderBgGpuTimer *self)
{
  if (self == NULL)
    return;

  for (guint i = 0; i < SLOTS; i++)
    self->delete_queries (1, &self->slots[i].id);

  g_free (self);
}

gboolean
shaderbg_gpu_timer_begin (ShaderBgGpuTimer *self,
                          guint32           serial)
{
  if (self == NULL || self->active || self->inflight == SLOTS)
    return FALSE;

  self->slots[self->head].serial = serial;
  self->begin_query (GL_TIME_ELAPSED_EXT, self->slots[self->head].id);
  self->active = TRUE;

  return TRUE;
}

void
shaderbg_gpu_timer_end (ShaderBgGpuTimer *self)
{
  if (self == NULL || !self->active)
    return;

  self->end_query (GL_TIME_ELAPSED_EXT);
  self->active = FALSE;

  self->head = (self->head + 1) % SLOTS;
  self->inflight++;
}

gboolean
shaderbg_gpu_timer_poll (ShaderBgGpuTimer *self,
                         guint32          *serial,
                         guint64          *elapsed_ns)
{
  Slot    *slot;
  GLuint   ready = 0;
  GLint    disjoint = 0;
  GLuint64 ns = 0;

  if (self == NULL || self->inflight == 0)
    return FALSE;

  slot = &self->slots[self->tail];

  self->get_query_uiv (slot->id, GL_QUERY_RESULT_AVAILABLE_EXT, &ready);
  if (!ready)
    return FALSE;

  self->get_query_ui64v (slot->id, GL_QUERY_RESULT_EXT, &ns);

  self->tail = (self->tail + 1) % SLOTS;
  self->inflight--;

  /* A disjoint event — the GPU was reset, or clocked around underneath the
   * query — makes every result gathered since the last check meaningless,
   * and the spec says so outright. Reading the flag also clears it. Dropping
   * the sample is the only honest answer; the caller has more frames. */
  self->get_integerv (GL_GPU_DISJOINT_EXT, &disjoint);
  if (disjoint)
    return FALSE;

  *serial = slot->serial;
  *elapsed_ns = ns;

  return TRUE;
}
