/* A ClutterEffect that draws a Shadertoy fragment shader.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <clutter/clutter.h>
#include <cogl/cogl.h>

G_BEGIN_DECLS

#define SHADERBG_TYPE_EFFECT (shaderbg_effect_get_type ())

G_DECLARE_FINAL_TYPE (ShaderBgEffect, shaderbg_effect, SHADERBG, EFFECT, ClutterEffect)

/**
 * shaderbg_effect_new:
 * @source: the complete fragment source, prelude already glued on
 * @noise: the texture bound to all four iChannels
 *
 * Returns: (transfer full): the effect
 */
ShaderBgEffect *shaderbg_effect_new (const char  *source,
                                     CoglTexture *noise);

float shaderbg_effect_get_render_scale (ShaderBgEffect *self);
void  shaderbg_effect_set_render_scale (ShaderBgEffect *self,
                                        float           scale);

void shaderbg_effect_set_uniform (ShaderBgEffect *self,
                                  const char     *name,
                                  float           value);

/* The resolution the shader composes for, which is the monitor's and has
 * nothing to do with how large the actor happens to be drawn. It sizes the
 * buffer and sets iResolution; the actor box only ever stretches the result. */
void shaderbg_effect_set_resolution (ShaderBgEffect *self,
                                     int             width,
                                     int             height);

/* The tick's own clock reading, so the frame signal can report how long the
 * repaint request waited before anything was drawn for it. */
void shaderbg_effect_mark_tick (ShaderBgEffect *self,
                                gint64          monotonic_us);

gboolean shaderbg_effect_get_tracing (ShaderBgEffect *self);
void     shaderbg_effect_set_tracing (ShaderBgEffect *self,
                                      gboolean        tracing);

/* FALSE when the driver had no timer query, which makes the gpu figure in the
 * frame signal a -1 forever. */
gboolean shaderbg_effect_has_gpu_timer (ShaderBgEffect *self);

G_END_DECLS
