/* Decodes one video file, looping, into textures the effect can draw.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include <glib-object.h>
#include <cogl/cogl.h>

G_BEGIN_DECLS

#define WPEBG_TYPE_PLAYER (wpebg_player_get_type ())

G_DECLARE_FINAL_TYPE (WpeBgPlayer, wpebg_player, WPEBG, PLAYER, GObject)

/**
 * wpebg_player_new:
 * @context: the Shell's Cogl context, which the frames are uploaded into
 *
 * Returns: (transfer full): the player
 */
WpeBgPlayer *wpebg_player_new (CoglContext *context);

/* A file:// URI, or NULL to stop and let go of the file. Starts paused or
 * playing, whichever was asked for last. */
void wpebg_player_set_uri (WpeBgPlayer *self,
                           const char  *uri);

void wpebg_player_set_playing (WpeBgPlayer *self,
                               gboolean     playing);

/* Uploads the newest decoded frame, if there is one nobody has drawn yet.
 * Returns FALSE while there is still nothing to draw at all. */
gboolean wpebg_player_prepare (WpeBgPlayer *self);

/* The pipeline that turns the two planes into RGB, and the video's display
 * aspect ratio. Only meaningful after wpebg_player_prepare returned TRUE. */
CoglPipeline *wpebg_player_get_pipeline (WpeBgPlayer *self);
float         wpebg_player_get_aspect   (WpeBgPlayer *self);

G_END_DECLS
