# wpebg

A GNOME Shell extension that plays a Wallpaper Engine video wallpaper —
a Steam Workshop item of app 431960 — as the desktop background.

## Why inside the Shell

Wallpaper Engine has no Linux build, and the Linux reimplementations do not
reach a GNOME desktop: linux-wallpaperengine draws through `wlr-layer-shell`,
which Mutter does not implement, and the KDE plugin is a Plasma wallpaper
plugin. The way in is the one shaderbg already uses — an effect on
`Meta.BackgroundActor`, inside the compositor process, which is not a client
and needs no protocol. See `shaderbg/README.md` for why it is an effect and
not a replacement actor: Mutter still culls the background behind windows.

## Where items come from

Workshop items need a Steam account that owns Wallpaper Engine; Steam itself
downloads them into
`steamapps/workshop/content/431960/<id>/` of a library. The preferences list
every item in every library named in `libraryfolders.vdf`, plus the app's
own `projects/defaultprojects` and `projects/myprojects` if it is installed.
Each item is a directory with a `project.json`; `type` says what it is and
`file` names the video. Only `video` items can be shown; `scene` and `web`
are listed greyed out.

Workshop content belongs to its authors. Nothing of it goes in this
repository — the setting stores only the item's path.

## The video path

    playbin (VA-API decoder, picked by rank)
      → videoconvert (passthrough for NV12)
      → appsink, NV12 in system memory
      → two textures: R8 luma, RG88 chroma
      → a Cogl snippet turning YCbCr into RGB, matrix and range from the caps

The decoder is the GPU's video engine, so decoding costs the shader cores
nothing. NV12 is 1.5 bytes a pixel to upload against RGBA's 4, and no colour
conversion runs on the CPU. Frames arrive on GStreamer's streaming thread and
only the newest is kept; the upload happens when the effect is painted, so a
culled background costs a decode and nothing else. An effect that asked for a
repaint and was not painted stops asking until something paints it again,
which keeps a covered background from making Mutter recomposite at the
video's frame rate.

Looping is a segment seek: `SEGMENT_DONE` instead of EOS, and the next pass
queued without a flush, so there is no hitch at the loop point.

The Shell's wrapper puts only core, base and good on the plugin path. The
library bakes in bad (VA decoders, parsers) and libav (software fallback) and
scans them on a worker thread, because the first scan is seconds the
compositor must not spend frozen.

Fit is cover: the video is scaled until it fills the screen, the overhang
cropped evenly. Audio is never decoded.

## Living next to shaderbg

Both hang an effect on the same actors, and an effect that draws without
chaining up hides everything after it. wpebg puts its effect first and chains
up whenever it has no frame — no item chosen, or the first frame not decoded
yet — so the shader shows then.

## Pausing

Per screen, a fullscreen window freezes that screen's copy. The decoder
pauses once every screen is covered, and while the session is locked.

## Testing

Headless, as in `shaderbg/README.md`, works for this one and is worth more
than it is for shaders: a test video from `videotestsrc pattern=smpte100`
comes back through a screenshot with the bars at exact primaries, which
checks the colour matrix end to end. Two things the sandbox needs on top of
that recipe: `dbus-run-session --config-file=…/share/dbus-1/session.conf`,
and `--no-x11`.

A new typelib reaches the Shell only through `GI_TYPELIB_PATH` at login, and
a new extension only shows up after one too.
