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
| multiple render passes | not built; one pipeline is one pass |
| `iChannel0..3` textures | bound to a generated noise texture, see below |
| `textureLod(s, uv, lod)` | `#define`d down to `texture2D(s, uv)`, the level is dropped |

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

Two numbers per shader, and they multiply.

`sources.nix` holds the **base** — what the shader is checked in at. The
preferences hold a **factor** on top of it, per shader, in the `speeds`
GSettings key; 1.0 means the base, and only shaders actually adjusted appear
there. So the committed number keeps meaning something after the slider has
been touched, and reset has somewhere to go back to.

An earlier version had the slider replace the base instead of scaling it,
which made `sources.nix` meaningless the moment anyone touched it.

Both scale the time base rather than the repaint rate, so slowing a shader
down does not make it stutter — and neither makes it cheaper, see below.

## Attribution, and what cannot go in here

Shadertoy defaults to CC BY-NC-SA 3.0. This repository is public, so every
entry in `sources.nix` carries its `id` and `author`, and the preferences
window links back to the original.

That default is not universal, and the exceptions matter. Several well-known
authors — Inigo Quilez among them — attach a licence that reads:

> You cannot host, display, distribute or share this Work neither as is or
> altered, in any form including physical and digital.

Checking into a public repository is hosting and distributing. **Any shader
carrying that notice has to stay out**, however good it looks. Two had already
been committed before anyone read the headers; they were removed again.

So the import is not finished when a shader compiles. Grep the code before
adding it, remembering that the notice wraps across lines:

    tr '\n' ' ' < shader.frag |
      grep -iE 'cannot host, display, distribute|sole copyright owner'

## Channel textures

Shadertoy's single most-used input is a 256×256 RGBA noise image: of the
channel uses across this set, nine want exactly that one. It is **generated
here** rather than downloaded — noise is noise, a locally made one is
equivalent where it matters, and nothing of Shadertoy's needs redistributing.
A seeded xorshift fills the bytes, so it is the same texture every session.

The channels are the pipeline's texture layers 0..3, bound once when the
effect is built. A Cogl pipeline names its own samplers, so the prelude
renames them — `#define iChannel0 cogl_sampler0` and so on — rather than
declaring sampler uniforms to be set from outside. Layer 0 is always bound
even for a shader that reads no channel at all: it existing is what makes
Cogl emit `cogl_tex_coord0_in`, which is where the fragment coordinate comes
from.

Only shaders whose every channel is that noise are in the set. The ones
wanting a photograph or a font atlas are not: binding noise would compile and
run, and look nothing like what their author made.

## What a shader costs

Measured on the RX 7800 XT in a live session at 3440×1440, 60 fps cap, with
nothing else running. Baseline without the extension: **10.7 W**.

| | over baseline | GPU |
|---|---:|---:|
| oceanic, tiny-clouds, sun-surface, protean-clouds | +39 … +46 W | 92–99 % |
| structured-vol-sampling, clearly-a-bug | +31 … +37 W | 67–78 % |
| star-nest, 2d-voxels | +22 … +24 W | 61–63 % |
| the other sixteen | +3 … +17 W | 9–30 % |

A 13× spread, in two clean groups with almost nothing between them.

Three things that are not levers, each of which looked like one:

- **Speed.** It scales the time base. The same fragments are computed either
  way, so a shader at 0.05 costs exactly what it costs at 1.0.
- **Frame rate.** Measured oceanic at 60, 30, 20, 10, 5 and 1 fps: 53–57 W and
  96–100 % every time. Once a frame takes longer than the interval, asking for
  fewer frames changes nothing.
- **Watts, as a measurement.** At 100 % GPU the power figure saturates, so it
  cannot tell a shader that is 2× too slow from one that is 10× too slow.
  Halving the fragment count showed *no* change in watts — and a 2× change in
  frame rate. Count frames, not watts.

Frame rate, counted in a headless session via `stage::after-paint`:

| oceanic at | fps |
|---|---:|
| full resolution | 18 |
| half the fragments | 37 |
| a quarter of the fragments | 60 (ceiling) |

So cost tracks fragment count almost exactly, and rendering the expensive
shaders at half linear resolution — a quarter of the fragments — is the lever
that works.

### Why this is a ClutterEffect and not a ClutterShaderEffect

`ClutterShaderEffect` derives from `ClutterOffscreenEffect`, and that class
**cannot render at a lower resolution at all**. Not "the attempts did not
work" — the mechanism forbids it. `clutter_offscreen_effect_pre_paint` ties
three things together:

    target        = paint volume size × ceilf(resource_scale)
    viewport      = 0, 0, target_width, target_height
    modelview    ×= stage_width / target_width, stage_height / target_height

The viewport is the target and the modelview is scaled by stage over target,
and those two cancel exactly. Pixel density is therefore pinned, and the only
free parameter is `resource_scale` — which is `ceilf()`'d, so it can only go
up. Shrinking the paint volume doubles the modelview scale to compensate,
giving a **crop at full density**; overriding `vfunc_create_texture` changes
only the texture, so rendering runs past it and is clipped. Three attempts,
three different wrong pictures, one cause.

The way out is the one gnome-shell itself takes. `ShellBlurEffect` renders its
blur at a third of the resolution, and its first line is the whole answer:

    G_DEFINE_TYPE (ShellBlurEffect, shell_blur_effect, CLUTTER_TYPE_EFFECT)

A plain `ClutterEffect` derives nothing from anything. It is handed a paint
node and sets the buffer, the viewport and the projection by hand:

    data->texture     = cogl_texture_2d_new_with_size (ctx, new_width, new_height);
    data->framebuffer = cogl_offscreen_new_with_texture (data->texture);
    graphene_matrix_scale (&projection, 2.0 / width, -2.0 / height, 1.f);

So `ShaderBgEffect` derives from `Clutter.Effect` and implements one vfunc,
`paint_node`. The shader is drawn into the buffer there and then, rather than
left to a nested `ClutterLayerNode` the way the first version did it:

    if (dirty)                   draw the shader into the offscreen, now
      cogl_framebuffer_draw_rectangle (fb, shader, 0, 0, bw, bh)
    PipelineNode(present)        then one quad over the actor
      rectangle 0..actor

Two things fall out of owning the draw. It can be bracketed, which is what
makes the timer query above possible at all; and it only has to happen when a
tick has actually moved a uniform, so the stage repainting for reasons of its
own — a notification, a cursor, damage from a window above — costs one
textured quad instead of a whole frame of the shader.

The buffer is sized from **the monitor's resolution, not the actor's**. The
shader composes for `iResolution` and the actor box only ever stretches the
result, so a workspace preview being animated from full size down to a
thumbnail moves one rectangle. Sizing it from the actor instead meant dropping
a 19 MB texture and redrawing the shader on every frame of that animation,
which is what the flicker on opening the overview was.

The shader runs once per buffer pixel and the buffer is stretched afterwards,
with linear filtering. It stays an **effect on the background actor**, so
`MetaBackgroundActor` keeps its own content and stays a `MetaCullable` — which
matters more than the downscaling does, because Mutter dropping the background
once a window covers it is worth 53.9 W against 17.3 W. Replacing the actor's
content, or hanging a child actor off it, both lose that; the child-actor
version was built and measured at 105 W with a window in front.

One trap the move brings with it: a Cogl snippet's body is emitted **after**
the shader source, so every `#define` the shader made is still in force over
it. Two shaders in this set open by defining `t` as `iTime`, which rewrote the
body's `cogl_tex_coord0_in.t` into `cogl_tex_coord0_in.iTime`. Everything of
ours therefore lives in `_sb_fragment()`, declared ahead of the shader source
where no macro of the shader's can reach it, and the body is one call.

### What is native, and why

Two halves. `extension.js` keeps everything that is not per-pixel — the
settings, the daily rotation, the ticker, and the GLSL prelude, which is text
and is far easier to iterate on in a file the Shell re-reads than in one that
needs a rebuild. `lib/src/` is the effect: the pipeline, the buffer, the paint
path and the uniforms, built as a GObject-Introspection library the extension
imports as `gi://ShaderBg`. The same shape `blur-my-shell` uses for
`gi://Blur`, and packaged the same way — `meson.build` names `libmutter-18`
literally, so a mutter bump fails to configure rather than building something
the Shell would refuse to load.

Rewriting the hot path in C bought nothing by itself, and it is worth being
clear about that: GJS was never in it. Per frame the JavaScript side runs one
timeout callback, four uniform writes and a `queue_repaint` — microseconds,
against a shader that is millions of fragments. What is native is native for
things GJS cannot reach at all:

| | why it needs C |
|---|---|
| `GL_TIME_ELAPSED` query | Cogl exposes no timer query, and GJS has no GL binding |
| `ClutterStage::presented` | carries a `ClutterFrameInfo`, a public C struct with no GI boxed type, so the signal is `introspectable="0"` |

The query is resolved through `eglGetProcAddress`, preferring the
`EXT_disjoint_timer_query` spelling because the session runs on the GLES
driver, and falling back to the unsuffixed names. Mutter 50 dropped epoxy and
links `libGL`/`libGLESv2`/`libEGL` itself, so there is no loader to borrow.
A disjoint event discards the sample rather than reporting a wrong one.

Bracketing has one trap worth writing down: Cogl batches draws into a journal,
so a query opened and closed around `cogl_framebuffer_draw_rectangle` times an
empty bracket. `cogl_framebuffer_flush` on both sides is what puts the draw
inside it — `flush`, not `finish`, because the result is wanted without
stalling the CPU on it. Results are collected a frame or two later out of a
four-slot ring, so nothing ever waits.

### Tracing the whole path

`trace`, off by default, puts a line a second in the journal with the median
of four spans:

    shaderbg: oceanic.frag at 0.5x, 97 frames — tick→draw 1.21 ms,
              cpu 0.04 ms, gpu 5.83 ms, draw→screen 7.42 ms

`tick→draw` is the repaint request waiting to be painted, `cpu` is this side
issuing the draw, `gpu` is the shader pass itself, and `draw→screen` is that
frame reaching the display. Medians and not a line a frame, because at a cap
of 100 the latter is a hundred lines a second.

It is off by default because it is not free: a timed pass flushes the journal
twice, and that is a real cost to pay for a number nobody is reading.

### Deciding which shaders get downscaled

Not by watching the frame rate. A shader that reaches the cap has only said
"fast enough", not how much room is left — at a cap of 30 and 30 fps a frame
may have taken 1 ms or 30 ms. Raising the resolution to find out and lowering
it again when it does not hold is an oscillation, not a measurement.

Nor by the wall clock, which was the first answer here and was wrong in a way
that took a while to see. The gap between two paints cannot fall below one
refresh interval, so on a 144 Hz screen it read 6.9 ms for *every* shader that
fitted into a frame: the same figure for `drift`, which has no loop at all, as
for `tiny-clouds`, which does 800 dependent texture fetches a pixel and holds
the card at 99 %. A budget handed two numbers it cannot tell apart does
nothing, which is exactly what a `frame-budget` of 10 % appeared to do.

So what the verdict is made from is **the GPU's own time for one pass of the
shader**, out of a `GL_TIME_ELAPSED` query bracketing the draw. That is the
whole reason the effect is a native library and not JavaScript: Cogl exposes
no timer query — mutter 50 still carries `COGL_FEATURE_ID_TIMESTAMP_QUERY` in
its headers with no function to go with it — and GJS has no GL binding to fall
back on.

- **Always at full resolution**, whatever it is currently drawn at, so that a
  shader put on a quarter can be shown to have earned its way back up and the
  prediction below stays a plain multiplication.
- **The cap is not touched.** A query times the work, not the pace, so there
  is nothing to be had from asking for frames faster than the setting says.
  Measuring is now invisible instead of two seconds of the fans spinning up.
- **The median** over a two-second window, so one pass that landed behind
  something else on the card does not drag the verdict.
- The largest of 1.0, 0.5, 0.25 whose predicted time fits the budget, and
  because cost is fragment count the prediction is the measured time times
  the square of the step.
- The budget is a share of the cap's interval — `frame-budget`, a percentage,
  half by default. That is also what the card's load settles at: at a 60 fps
  cap and 50 %, a shader that just fits spends 8.3 ms of every 16.7 ms
  drawing. Lowering it is how to ask for an idler card and accept a softer
  background.
- **Nothing is exempt from the budget.** The wall-clock version had to let
  every shader at the refresh interval off, because a budget below that
  interval was a test nothing could pass; that exemption was the bug. A GPU
  time has no floor under it — 0.4 ms is 0.4 ms.
- A driver with no timer query leaves every shader at full resolution and says
  so in the journal, rather than reaching a verdict from something else.

Nothing is ever derived from the outcome of a previous change, which is what
keeps it from swinging. The verdict is kept per shader *and* per screen
resolution, so plugging in another monitor means a fresh measurement rather
than a stale one. Moving the cap or the budget throws every verdict away,
because each one was reached against the old numbers; the shader on screen is
timed again eight seconds later.

The square law understates the cheap end — oceanic takes 57 ms at full
resolution and 32 ms at half, against 14 ms predicted, because part of each
frame is fixed overhead. Understating is the safe direction: it never picks a
step coarser than needed.

One thing that is easy to get wrong: **downscaling alone saves nothing.** Load
is fragments per frame times frames per second, and freeing capacity just
raises the frame rate — measured, oceanic at half the fragments went from
17.6 to 31.0 fps at an unchanged 51 W. The saving comes from pairing a lower
resolution with the frame cap. Capping alone does not work either: at 5 fps
the card still sits at 98 %, because it does not clock down between frames.

## Why the set is smaller than the list it came from

Of 52 picked shaders, 16 are in. The rest are not rejections, they are things
the render path does not do yet:

| | count | why |
|---|---|---|
| in the set | 20 | single image pass; noise channels are fine |
| needs a buffer pass | 14 | multipass, see below |
| needs a photo, font or audio channel | 15 | noise is not a substitute for those |
| restrictive licence | 3 | see above |

**Buffer passes are not impossible, only unbuilt** — and markedly closer than
they were. One pipeline is one program and one pass, but the effect now owns
its framebuffer, its pipeline and its paint nodes outright, so a second pass
is another of each rather than a new mechanism. What it takes is a small
render graph: a framebuffer per buffer pass, each with its own program, ping-ponged
between frames because a Shadertoy buffer reads its own previous frame, all
resized with the monitor, and finally bound as the image pass's channels.
That is a project, not an afternoon, and it would bring back the other
fourteen.

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
