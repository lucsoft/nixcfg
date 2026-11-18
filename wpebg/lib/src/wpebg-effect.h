/* A ClutterEffect that draws a WpeBgPlayer's frames over a background actor.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <clutter/clutter.h>

#include "wpebg-player.h"

G_BEGIN_DECLS

#define WPEBG_TYPE_EFFECT (wpebg_effect_get_type ())

G_DECLARE_FINAL_TYPE (WpeBgEffect, wpebg_effect, WPEBG, EFFECT, ClutterEffect)

/**
 * wpebg_effect_new:
 * @player: the player whose frames this draws; many effects share one
 *
 * Returns: (transfer full): the effect
 */
WpeBgEffect *wpebg_effect_new (WpeBgPlayer *player);

/* A frozen effect keeps showing its last frame and stops asking for
 * repaints — for a monitor a fullscreen window covers. */
void wpebg_effect_set_frozen (WpeBgEffect *self,
                              gboolean     frozen);

G_END_DECLS
