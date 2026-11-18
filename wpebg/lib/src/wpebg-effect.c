/* A ClutterEffect that draws a WpeBgPlayer's frames over a background actor.
 *
 * Same shape as shaderbg's effect, and for the same reason: it stays an
 * effect on MetaBackgroundActor rather than replacing its content or adding
 * a child, so the actor is still a MetaCullable and Mutter still skips it
 * when a window covers it.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "wpebg-effect.h"

struct _WpeBgEffect
{
  ClutterEffect parent_instance;

  WpeBgPlayer  *player;
  gulong        frame_id;
  gboolean      frozen;

  /* A repaint was asked for and this effect has not been painted since.
   * While that holds, the actor is culled — a window covers it — and
   * asking again at the video's frame rate would only make Mutter
   * recomposite the windows on top of it for nothing. Whatever uncovers it
   * damages it, the paint clears this, and the next frame asks again. */
  gboolean      unanswered;
};

G_DEFINE_FINAL_TYPE (WpeBgEffect, wpebg_effect, CLUTTER_TYPE_EFFECT)

static void
on_frame (WpeBgPlayer *player G_GNUC_UNUSED,
          gpointer     data)
{
  WpeBgEffect *self = data;
  ClutterActorMeta *meta = CLUTTER_ACTOR_META (self);
  ClutterActor *actor = clutter_actor_meta_get_actor (meta);

  if (self->frozen || self->unanswered || actor == NULL ||
      !clutter_actor_meta_get_enabled (meta) ||
      !clutter_actor_is_mapped (actor))
    return;

  self->unanswered = TRUE;
  clutter_effect_queue_repaint (CLUTTER_EFFECT (self));
}

static void
wpebg_effect_paint_node (ClutterEffect           *effect,
                         ClutterPaintNode        *node,
                         ClutterPaintContext     *paint_context,
                         ClutterEffectPaintFlags  flags)
{
  WpeBgEffect *self = WPEBG_EFFECT (effect);
  ClutterActor *actor;
  ClutterActorBox box;
  ClutterPaintNode *video_node;
  float width, height, aspect, ratio;
  float x1 = 0.0f, y1 = 0.0f, x2 = 1.0f, y2 = 1.0f;

  self->unanswered = FALSE;

  actor = clutter_actor_meta_get_actor (CLUTTER_ACTOR_META (effect));
  if (actor == NULL)
    return;

  /* Nothing decoded yet, or no file at all: the actor's own content — the
   * ordinary wallpaper, or whatever effect comes after this one — shows
   * instead of a black screen. */
  if (!wpebg_player_prepare (self->player))
    {
      CLUTTER_EFFECT_CLASS (wpebg_effect_parent_class)->paint_node (effect, node,
                                                                   paint_context,
                                                                   flags);
      return;
    }

  clutter_actor_get_allocation_box (actor, &box);
  width = clutter_actor_box_get_width (&box);
  height = clutter_actor_box_get_height (&box);
  if (width < 1.0f || height < 1.0f)
    return;

  /* Cover, the way Wallpaper Engine fills a screen: scaled until both
   * sides are filled, the overhang cropped evenly. The actor's own aspect
   * is the monitor's, at full size and as a workspace thumbnail alike. */
  aspect = wpebg_player_get_aspect (self->player);
  if (width / height > aspect)
    {
      ratio = aspect / (width / height);
      y1 = (1.0f - ratio) / 2.0f;
      y2 = 1.0f - y1;
    }
  else
    {
      ratio = (width / height) / aspect;
      x1 = (1.0f - ratio) / 2.0f;
      x2 = 1.0f - x1;
    }

  /* No chain-up: the video replaces the actor's content. */
  video_node = clutter_pipeline_node_new (wpebg_player_get_pipeline (self->player));
  clutter_paint_node_add_child (node, video_node);
  clutter_paint_node_add_texture_rectangle (video_node,
                                            &(ClutterActorBox) { 0.0f, 0.0f, width, height },
                                            x1, y1, x2, y2);
  clutter_paint_node_unref (video_node);
}

static void
wpebg_effect_set_actor (ClutterActorMeta *meta,
                        ClutterActor     *actor)
{
  WPEBG_EFFECT (meta)->unanswered = FALSE;

  CLUTTER_ACTOR_META_CLASS (wpebg_effect_parent_class)->set_actor (meta, actor);
}

static void
wpebg_effect_dispose (GObject *object)
{
  WpeBgEffect *self = WPEBG_EFFECT (object);

  if (self->player != NULL)
    g_clear_signal_handler (&self->frame_id, self->player);
  g_clear_object (&self->player);

  G_OBJECT_CLASS (wpebg_effect_parent_class)->dispose (object);
}

static void
wpebg_effect_class_init (WpeBgEffectClass *klass)
{
  GObjectClass *object_class = G_OBJECT_CLASS (klass);
  ClutterActorMetaClass *meta_class = CLUTTER_ACTOR_META_CLASS (klass);
  ClutterEffectClass *effect_class = CLUTTER_EFFECT_CLASS (klass);

  object_class->dispose = wpebg_effect_dispose;
  meta_class->set_actor = wpebg_effect_set_actor;
  effect_class->paint_node = wpebg_effect_paint_node;
}

static void
wpebg_effect_init (WpeBgEffect *self G_GNUC_UNUSED)
{
}

WpeBgEffect *
wpebg_effect_new (WpeBgPlayer *player)
{
  WpeBgEffect *self;

  g_return_val_if_fail (WPEBG_IS_PLAYER (player), NULL);

  /* ClutterActorMeta is initially unowned. Handing GJS a floating
   * reference under (transfer full) leaves it and Clutter both believing
   * they own the one reference there is, and the effect is finalized while
   * still on the actor. */
  self = g_object_ref_sink (g_object_new (WPEBG_TYPE_EFFECT, NULL));
  self->player = g_object_ref (player);
  self->frame_id = g_signal_connect (player, "frame",
                                     G_CALLBACK (on_frame), self);

  return self;
}

void
wpebg_effect_set_frozen (WpeBgEffect *self,
                         gboolean     frozen)
{
  g_return_if_fail (WPEBG_IS_EFFECT (self));

  self->frozen = !!frozen;
}
