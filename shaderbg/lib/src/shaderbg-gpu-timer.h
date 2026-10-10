/* GPU-side timing for the shader pass.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <glib.h>

G_BEGIN_DECLS

typedef struct _ShaderBgGpuTimer ShaderBgGpuTimer;

/* NULL when the driver has no timer query, which is not an error: the caller
 * is expected to carry on untimed. */
ShaderBgGpuTimer *shaderbg_gpu_timer_new  (void);
void              shaderbg_gpu_timer_free (ShaderBgGpuTimer *self);

/* FALSE when every slot is still in flight, in which case no matching end()
 * may be issued. */
gboolean shaderbg_gpu_timer_begin (ShaderBgGpuTimer *self,
                                   guint32           serial);
void     shaderbg_gpu_timer_end   (ShaderBgGpuTimer *self);

/* Drains one finished query per call, oldest first. */
gboolean shaderbg_gpu_timer_poll (ShaderBgGpuTimer *self,
                                  guint32          *serial,
                                  guint64          *elapsed_ns);

G_END_DECLS
