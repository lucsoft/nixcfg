# shaderbg

A GNOME Shell extension that draws a fragment shader as the desktop
background, rotating through the set in `sources.nix` one per day.

## Why an extension

On Wayland there is no wallpaper buffer. X11 had the root window pixmap, which
is why `feh` and `hsetroot` are one-liners; Wayland dropped it, and the usual
replacement — `wlr-layer-shell` — is a protocol Mutter does not implement, so
`swww`, `mpvpaper`, `oguri` and neowall are all out. `Meta.Background` can do a
colour, a gradient, or one or two blended image files, and nothing else.

But the background is not a client. gnome-shell draws it itself, as a Clutter
actor in `Meta.BackgroundGroup` at the bottom of `global.window_group`. An
extension runs inside that same process, so it is not a client either and the
restriction does not apply to it. `blur-my-shell` already renders GLSL this way
on this Shell version.

## The GLSL dialect

Cogl compiles an old GLSL. Shaders copied from Shadertoy usually need edits:

| Shadertoy | here |
|---|---|
| `texture(s, uv)` | `texture2D` — `extension.js` `#define`s this away |
| `#version`, `in`/`out` | not allowed, remove |
| `texelFetch`, `textureLod` | unavailable |
| output to `fragColor` | the prelude copies it to `cogl_color_out` |
| multiple render passes | impossible, one `ClutterShaderEffect` is one pass |
| `iChannel0..3` textures | declared so the shader compiles, but sample black |

`iTime`, `iTimeDelta`, `iFrame`, `iResolution`, `iMouse`, `iDate` and
`iSampleRate` all exist; only the first four carry real values.

Two things that look like bugs and are not:

- **No vector uniforms.** `iResolution` is fed as two separate floats,
  `iResX`/`iResY`, and reassembled in the prelude. Vector uniforms cannot be set
  cleanly through `set_uniform_value` from GJS — `blur-my-shell` splits its
  `vec2`s for the same reason.
- **`parseFloat(value - 1e-6)`.** GJS turns a JS number that happens to be
  integral into an `int` GValue, which a `float` uniform rejects. Without the
  shave a shader breaks only on the frames where its time lands on a round
  number, which is a miserable thing to debug.

## Importing shaders

Shadertoy sits behind a Cloudflare managed challenge. Every path answers HTTP
403 to a plain client — `/api/v1/` and the front page included, because the
challenge sits in front of the application. An API key does not help: the
block happens before the request ever reaches Shadertoy. It has to come from a
browser that has solved the challenge.

No key is needed, though. `import.js` uses the same internal endpoint the site
itself uses, same-origin, with the clearance cookie the browser already holds:
open any shadertoy.com page, paste the file into the console, and a
`shaders.json` downloads with every pass of every shader.

That can be driven rather than pasted, which is how this set was imported:
start the browser with `--remote-debugging-port=9222` and a throwaway
`--user-data-dir`, then send the same expression over the devtools protocol.
A plain Chromium passes the challenge on its own, so no login is involved.

Then split the JSON into `shaders/*.frag` and add the entries to `sources.nix`.
`import.js` records every render pass, not just the image one, so a shader that
needs a buffer pass or a channel texture is visible before it fails to render.

## Speed

Each shader has its own speed, set once and remembered. `sources.nix` carries
the value a shader ships with; the preferences write into the `speeds`
GSettings key, which holds only the ones actually tuned. That split is what
lets the reset button exist, and it keeps the committed file meaningful
instead of being overwritten by every nudge of the slider.

Both scale the time base rather than the repaint rate, so slowing a shader
down does not make it stutter.

## Attribution

Shadertoy defaults to CC BY-NC-SA 3.0. This repository is public, so every
entry in `sources.nix` carries its `id` and `author`, and the preferences
window links back to the original.

## Testing

Extensions run in the compositor process: a shader that takes the extension
down takes the session with it, and on Wayland there is no `Alt+F2` `r` to
recover. So test out of process first.

**Not in a nested Shell** — there is no such thing any more. Mutter 50 dropped
the nested backend: `meta_context_main_create_backend()` returns the native one
unconditionally, so `gnome-shell --wayland` without `--display-server` still
tries to take control of the logind session and dies with `EBUSY`. The help
text that says `--display-server` runs it "rather than nested" is stale.

What works is headless with a virtual monitor, pointed at a throwaway config so
the live session's dconf is left alone:

    XDG_CONFIG_HOME=$(mktemp -d) \
    XDG_DATA_DIRS=$(nix-build --no-out-link -E '…callPackage ./shaderbg {}')/share:$XDG_DATA_DIRS \
      dbus-run-session -- gnome-shell --headless --unsafe-mode --virtual-monitor 3440x1440

`--unsafe-mode` is a hidden mutter option, and it is what makes the run
useful: without it both `org.gnome.Shell.Eval` and the `Screenshot` D-Bus
method answer `AccessDenied`. With it, the actor tree can be inspected and the
output captured from outside:

    gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell \
      --method org.gnome.Shell.Eval 'Main.overview.hide(); 1'

Be clear about what that buys, though, because it is less than it looks.
A headless screenshot is **not** a colour reference and **not** a way to vet
individual shaders. A constant-colour shader measures anywhere from 67 to 255
across a single actor, and the same shader renders in one run and comes out
black in the next. The cause is damage tracking: an actor nobody repaints is
drawn once, and whatever fell outside that first damage region stays black no
matter what its shader does. Giving every test actor its own repaint timer
helps and still does not make the result stable.

So headless answers exactly one question — does the extension load, build its
actors, compile its shaders and drive its clock — and it answers that well.
Everything visual is a real-display question.

For vetting the shader set, two things that do work:

- `glslangValidator` against **both** `#version 110` and `#version 120`, with
  the prelude glued on and `cogl_color_out` swapped for `gl_FragColor`. Cogl
  compiles without a `#version` directive, which means 1.10, so 1.20 passing
  alone proves nothing.
- Stepping through the set on the real desktop, which is what the shader list
  in the preferences is for. Thirteen clicks beats any amount of headless
  measurement.
