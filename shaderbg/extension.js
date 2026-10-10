import Cogl from 'gi://Cogl';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

// The effect, in C. home.nix puts the typelib on GI_TYPELIB_PATH; the Shell
// picks that up from environment.d, so a fresh install of the library only
// takes effect after a logout.
import ShaderBg from 'gi://ShaderBg';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

// Cogl speaks an old GLSL: no #version, no in/out, texture2D() rather than
// texture(), and the fragment writes to cogl_color_out. Shadertoy assumes the
// opposite of all four. This prelude is glued in front of every shader so the
// files in shaders/ can stay as close to their upstream form as possible.
//
// It is handed to Cogl as a *snippet*, which is split in two: DECLARATIONS
// lands at file scope, BODY lands inside the pipeline's own main(). That is
// why main() is not written out here the way it would be for a plain shader.
//
// iResolution has to be a global rather than a local: mainImage is a separate
// function and reaches it by name. The i* names that no single-pass shader can
// be given real values for — the mouse, the date — are declared anyway,
// because a shader that merely mentions one of them should still compile
// instead of taking the whole set down with it.
const DECLARATIONS = `
uniform float iTime;
uniform float iTimeDelta;
uniform float iFrameF;
uniform float iResX;
uniform float iResY;

// Every channel carries the same locally generated noise, so one number
// describes all four resolutions.
uniform float iChannelSize;

// The channels are the pipeline's texture layers 0..3. A Cogl pipeline names
// its samplers itself, so these are renames rather than declarations — the
// sampler uniform does not exist to be set from outside.
#define iChannel0 cogl_sampler0
#define iChannel1 cogl_sampler1
#define iChannel2 cogl_sampler2
#define iChannel3 cogl_sampler3

vec3  iResolution;
int   iFrame;
vec4  iMouse = vec4(0.0);
vec4  iDate = vec4(0.0);
float iSampleRate = 44100.0;
vec3  iChannelResolution[4];
float iChannelTime[4];

#define texture texture2D

// textureLod picks a mip level, and Cogl's GLSL has no fragment-stage
// equivalent — texture2DLod is vertex-only before an ARB extension that
// cannot be enabled from here, because Cogl prepends its own code and
// #extension has to come first in the file. Dropping the level is the
// honest approximation: distant detail aliases slightly, and thirteen of
// the twenty channel shaders compile instead of none.
#define textureLod(s, uv, l) texture2D(s, uv)
#define texture2DLod(s, uv, l) texture2D(s, uv)

// Functions GLSL gained in 1.30 that Shadertoy authors use freely and Cogl's
// dialect does not have. They are defined under private names and #defined
// into place, so a shader that never calls one pays nothing for it. tanh is
// clamped before exp() because exp(2x) overflows to inf well inside the range
// shaders pass in, and inf/inf is a NaN that paints black.
float _sb_tanh(float x) { x = clamp(x, -9.0, 9.0); float e = exp(2.0 * x); return (e - 1.0) / (e + 1.0); }
vec2  _sb_tanh(vec2 v)  { return vec2(_sb_tanh(v.x), _sb_tanh(v.y)); }
vec3  _sb_tanh(vec3 v)  { return vec3(_sb_tanh(v.x), _sb_tanh(v.y), _sb_tanh(v.z)); }
vec4  _sb_tanh(vec4 v)  { return vec4(_sb_tanh(v.x), _sb_tanh(v.y), _sb_tanh(v.z), _sb_tanh(v.w)); }
#define tanh _sb_tanh

float _sb_round(float x) { return floor(x + 0.5); }
vec2  _sb_round(vec2 v)  { return floor(v + 0.5); }
vec3  _sb_round(vec3 v)  { return floor(v + 0.5); }
vec4  _sb_round(vec4 v)  { return floor(v + 0.5); }
#define round _sb_round

float _sb_trunc(float x) { return sign(x) * floor(abs(x)); }
vec2  _sb_trunc(vec2 v)  { return sign(v) * floor(abs(v)); }
vec3  _sb_trunc(vec3 v)  { return sign(v) * floor(abs(v)); }
vec4  _sb_trunc(vec4 v)  { return sign(v) * floor(abs(v)); }
#define trunc _sb_trunc

// smoothstep is only defined for edge0 < edge1, and Shadertoy shaders reverse
// the edges all the time to get a falling ramp. On Shadertoy that happens to
// work; here Mesa returns NaN for it, and a NaN fragment paints black. Three
// of the first sixteen imported shaders died on exactly this. Spelling the
// interpolation out gives the behaviour their authors assumed.
float _sb_sstep(float e0, float e1, float x) { float t = clamp((x - e0) / (e1 - e0), 0.0, 1.0); return t * t * (3.0 - 2.0 * t); }
vec2  _sb_sstep(float e0, float e1, vec2 v)  { return vec2(_sb_sstep(e0, e1, v.x), _sb_sstep(e0, e1, v.y)); }
vec3  _sb_sstep(float e0, float e1, vec3 v)  { return vec3(_sb_sstep(e0, e1, v.x), _sb_sstep(e0, e1, v.y), _sb_sstep(e0, e1, v.z)); }
vec4  _sb_sstep(float e0, float e1, vec4 v)  { return vec4(_sb_sstep(e0, e1, v.x), _sb_sstep(e0, e1, v.y), _sb_sstep(e0, e1, v.z), _sb_sstep(e0, e1, v.w)); }
vec2  _sb_sstep(vec2 e0, vec2 e1, vec2 v)    { return vec2(_sb_sstep(e0.x, e1.x, v.x), _sb_sstep(e0.y, e1.y, v.y)); }
vec3  _sb_sstep(vec3 e0, vec3 e1, vec3 v)    { return vec3(_sb_sstep(e0.x, e1.x, v.x), _sb_sstep(e0.y, e1.y, v.y), _sb_sstep(e0.z, e1.z, v.z)); }
vec4  _sb_sstep(vec4 e0, vec4 e1, vec4 v)    { return vec4(_sb_sstep(e0.x, e1.x, v.x), _sb_sstep(e0.y, e1.y, v.y), _sb_sstep(e0.z, e1.z, v.z), _sb_sstep(e0.w, e1.w, v.w)); }
#define smoothstep _sb_sstep

void mainImage(out vec4 fragColor, in vec2 fragCoord);

// The whole of the fragment stage, and it lives here — in the declarations,
// ahead of the shader's own text — rather than in the snippet body that Cogl
// drops into its main().
//
// It has to. A snippet body is emitted *after* the shader source, so every
// #define the shader made is still in force over it, and Shadertoy shaders
// define single letters freely. Two in this set open with a #define of t to
// iTime, which quietly rewrote this function's cogl_tex_coord0_in.t into
// cogl_tex_coord0_in.iTime and took them both down. Written here, nothing
// of the shader's can reach it; the body is left with one call, under a name
// no shader will have taken.
vec4 _sb_fragment()
{
    // Clamped, not trusted. A uniform that has not been set yet reads as 0,
    // and dividing by that gives an infinite fragCoord — which a raymarching
    // shader turns into a loop that never meets its exit condition. That is
    // not a wrong pixel, it is a hung GPU and a compositor reset. Ask how
    // this comment came to be written.
    vec2 res = max(vec2(iResX, iResY), vec2(1.0));

    iResolution = vec3(res, 1.0);
    iFrame = int(iFrameF);

    iChannelResolution[0] = vec3(iChannelSize, iChannelSize, 1.0);
    iChannelResolution[1] = iChannelResolution[0];
    iChannelResolution[2] = iChannelResolution[0];
    iChannelResolution[3] = iChannelResolution[0];

    // The quad's own texture coordinate, not gl_FragCoord.
    //
    // gl_FragCoord is a position in the framebuffer, so using it meant
    // working out where the actor currently sits on screen and subtracting
    // that — every frame, because the overview moves its previews, scrolls
    // them between workspaces and shrinks them during a search. Three
    // separate bugs came out of that chase: the shader standing still like a
    // mask while a preview slid across it, the picture reflowing during the
    // open animation, and banding in the app grid where parts of the actor
    // were painted at different moments with different geometry.
    //
    // cogl_tex_coord0_in is interpolated across the quad this pipeline draws,
    // so it is 0..1 over the rendered area by construction — under any
    // position, any size, any transform, and at any render scale, with
    // nothing to keep in sync.
    //
    // t runs downwards and Shadertoy counts upwards, hence the subtraction.
    //
    // The clamp is left as a backstop: a loop that marches until it passes
    // some distance has to be able to finish, or the whole GPU stops.
    vec2 n = clamp(vec2(cogl_tex_coord0_in.s, 1.0 - cogl_tex_coord0_in.t), 0.0, 1.0);

    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    mainImage(color, n * res);
    return vec4(color.rgb, 1.0);
}
`;


const EFFECT_NAME = 'shaderbg';

// The resolutions a shader may be rendered at, largest first. Three steps and
// not a continuum: each one is a whole new buffer, and the difference between
// 0.6 and 0.65 is not worth a reallocation.
const SCALE_STEPS = [1.0, 0.5, 0.25];

// The timing no longer touches the frame cap. A GL timer query reports the
// work a pass of the shader was, not the pace it was asked for, so the window
// is simply a stretch of ordinary frames with tracing switched on.
const MEASURE_DELAY = 8;        // seconds to let the session settle first
const MEASURE_WINDOW_MS = 2000; // how long the shader is timed for
const MEASURE_RETRY = 60;       // seconds, when the desktop was not visible
const MEASURE_MIN_SAMPLES = 3;  // fewer than this and the window says nothing

// How often the trace prints a line, in seconds. Medians over the interval,
// because at a cap of 100 one line a frame is a hundred lines a second.
const TRACE_REPORT = 1;

// The effect itself is native, and lives in lib/src/shaderbg-effect.c. What
// is left on this side is everything that is not per-pixel: the settings, the
// rotation, the ticker, and the prelude above — a few microseconds of work a
// frame, where the shader is millions of fragments.
//
// It was moved for a number the frame budget could not otherwise have. The
// budget needs to know what one pass of the shader costs, and the only honest
// source for that is a GL timer query bracketing the draw. Cogl exposes none:
// mutter 50 still carries COGL_FEATURE_ID_TIMESTAMP_QUERY in its headers but
// nothing to call, and GJS has no GL binding to fall back on. Measuring the
// wall-clock gap between paints instead — which is what this file used to do —
// cannot read below one refresh interval, so every shader that fitted into a
// frame measured as exactly one frame whether it had used 1 % of it or 99 %.
// On a 144 Hz screen that was 6.9 ms for `drift`, which has no loop at all,
// and 7.0 ms for `tiny-clouds`, which does 800 dependent texture fetches per
// pixel and holds the card at 99 %. The budget was being handed two numbers
// it could not tell apart.
//
// Two things came with it. ClutterStage::presented carries a ClutterFrameInfo,
// a plain public struct with no GI boxed type, so the signal is marked
// introspectable=0 and GJS cannot connect to it — in C it is a field read, and
// it is what closes the path from the tick to the picture being on screen.
// And the shader is now drawn into its buffer only when a tick has moved a
// uniform, so a stage repaint for reasons of its own costs one textured quad
// instead of a whole frame of the shader.

// Shadertoy's most-used input by a wide margin is a 256x256 RGBA noise image,
// and nine of the channel uses in this set want exactly that. It is generated
// here rather than shipped: noise is noise, a locally made one is equivalent
// where it matters, and nothing of Shadertoy's has to be redistributed to get
// it. The generator is seeded so the texture is the same every session.
const CHANNEL_SIZE = 256;

function noiseTexture(context) {
    const bytes = new Uint8Array(CHANNEL_SIZE * CHANNEL_SIZE * 4);

    let state = 0x2545f491;
    for (let i = 0; i < bytes.length; i++) {
        state ^= state << 13;
        state ^= state >>> 17;
        state ^= state << 5;
        bytes[i] = state & 0xff;
    }

    return Cogl.Texture2D.new_from_data(
        context, CHANNEL_SIZE, CHANNEL_SIZE,
        Cogl.PixelFormat.RGBA_8888, CHANNEL_SIZE * 4, bytes);
}

export default class ShaderBgExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._sources = this._loadSources();

        this._actors = new Map();
        this._tickId = 0;
        this._midnightId = 0;
        this._paused = false;
        this._time = 0;
        this._shaderSpeed = 1;
        this._entry = null;
        this._frame = 0;
        this._source = null;
        this._scale = 1;
        this._measureId = 0;
        this._measuring = null;
        this._tracedEffect = null;
        this._traceId = 0;
        this._traceReportId = 0;
        this._samples = null;

        // pause-fullscreen is read inside the tick, but the timer's interval is
        // the cap, so changing that one has to rebuild it. The cap is also the
        // interval the frame budget is a share of, so moving either of them
        // throws away every verdict reached against the budget they made.
        this._settingsIds = [
            this._settings.connect('changed::fps-cap', () => {
                this._restartTicker();
                this._forgetMeasurements();
            }),
            this._settings.connect('changed::frame-budget',
                () => this._forgetMeasurements()),
            this._settings.connect('changed::scales', () => this._rescale()),
            this._settings.connect('changed::trace', () => this._updateTracing()),
        ];

        this._settingsIds.push(...[
            'changed::override-index',
            'changed::override-day',
            'changed::auto-downscale',
        ].map(s => this._settings.connect(s, () => this._rebuild())));

        // Re-read rather than rebuild: the speed only scales the time base, so
        // there is no reason to throw away the effects and start the shader over.
        this._settingsIds.push(this._settings.connect('changed::speeds', () => {
            this._shaderSpeed = this._speedOf(this._entry);
        }));

        this._displayId = global.display.connect(
            'in-fullscreen-changed', () => this._updatePaused());
        this._sessionId = Main.sessionMode.connect(
            'updated', () => this._updatePaused());

        // The desktop is not the only background. The overview builds its own
        // per workspace (workspace.js:978), which is why hooking only
        // layoutManager._backgroundGroup left the old wallpaper showing there.
        // Both go through this one factory, so patching it catches every
        // background the Shell will ever make, including ones created later.
        const self = this;
        this._origCreateActor = Background.BackgroundManager.prototype._createBackgroundActor;
        this._patchedCreateActor = function () {
            const actor = self._origCreateActor.call(this);
            self._attach(actor);
            return actor;
        };
        Background.BackgroundManager.prototype._createBackgroundActor =
            this._patchedCreateActor;

        this._rebuild();
        this._scheduleMidnight();
    }

    disable() {
        // Only unwind if the wrapper on the prototype is still ours. Another
        // extension may have patched the same method after us, and restoring
        // blindly would throw its version away.
        if (this._origCreateActor) {
            if (Background.BackgroundManager.prototype._createBackgroundActor ===
                this._patchedCreateActor) {
                Background.BackgroundManager.prototype._createBackgroundActor =
                    this._origCreateActor;
            }
            this._origCreateActor = null;
            this._patchedCreateActor = null;
        }

        for (const id of this._settingsIds ?? [])
            this._settings.disconnect(id);
        this._settingsIds = null;

        if (this._displayId)
            global.display.disconnect(this._displayId);
        if (this._sessionId)
            Main.sessionMode.disconnect(this._sessionId);
        this._displayId = this._sessionId = 0;

        this._cancelMeasurement();
        this._stopTraceReport();
        this._stopTicker();

        if (this._midnightId)
            GLib.source_remove(this._midnightId);
        this._midnightId = 0;

        this._detachAll();
        this._settings = null;
        this._sources = null;
    }

    // ---- shader set -------------------------------------------------------

    _loadSources() {
        const path = GLib.build_filenamev([this.path, 'sources.json']);
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (ok) {
                const parsed = JSON.parse(new TextDecoder().decode(bytes));
                if (Array.isArray(parsed) && parsed.length > 0)
                    return parsed;
            }
        } catch (err) {
            console.error(`shaderbg: cannot read sources.json — ${err}`);
        }
        return [{ file: 'drift.frag', name: 'drift', author: 'lucsoft', speed: 1 }];
    }

    // Days since the epoch, counted in local time. Monotonic across a day
    // boundary, which is all the rotation needs.
    _today() {
        const now = new Date();
        const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        return Math.floor(midnight.getTime() / 86400000);
    }

    _pick() {
        const count = this._sources.length;
        if (count === 0)
            return null;

        const index = this._settings.get_int('override-index');
        const day = this._settings.get_int('override-day');

        // A hand-picked shader is tied to the day it was picked on, so "stay
        // on this one" expires by itself at midnight.
        if (index >= 0 && index < count && day === this._today())
            return this._sources[index];

        return this._sources[((this._today() % count) + count) % count];
    }

    // Two numbers, and they multiply. sources.nix carries the base — the
    // speed a shader is checked in at, arrived at by watching it — and the
    // preferences store a factor on top of that, per shader. Replacing the
    // base instead of scaling it made the committed value meaningless the
    // moment the slider was touched.
    _speedOf(entry) {
        if (!entry)
            return 1;

        const tuned = this._settings.get_value('speeds').deepUnpack();
        return (entry.speed ?? 1) * (tuned[entry.file] ?? 1);
    }

    // How much of the monitor's resolution the shader is rendered at. A
    // fragment shader's cost is fragments times frames, and at 3440x1440 the
    // expensive half of this set cannot keep up — so the ones that cannot get
    // fewer fragments and are stretched back up afterwards.
    //
    // A value in sources.nix is a deliberate choice about one shader and wins
    // outright. Everything else is left to the measurement.
    _scaleOf(entry) {
        if (!entry)
            return 1;

        if (typeof entry.scale === 'number')
            return entry.scale;

        if (!this._settings.get_boolean('auto-downscale'))
            return 1;

        const measured = this._settings.get_value('scales').deepUnpack();
        return measured[this._scaleKey(entry)] ?? 1;
    }

    // Keyed by resolution as well as by shader: the same shader is a different
    // amount of work on a different monitor, so plugging one in has to mean a
    // fresh measurement rather than a stale verdict.
    _scaleKey(entry) {
        const monitor = Main.layoutManager.primaryMonitor;
        const w = monitor?.width ?? 0;
        const h = monitor?.height ?? 0;
        return `${entry.file}@${w}x${h}`;
    }

    _forgetMeasurements() {
        this._settings.set_value('scales', new GLib.Variant('a{sd}', {}));
    }

    // Timings can be dropped from outside — the preferences window's "time
    // every shader again", or a budget change above. Picking that up here is
    // what makes it take effect now rather than at the next login: back to
    // full resolution, and timed afresh.
    _rescale() {
        this._applyScale(this._scaleOf(this._entry));
        this._scheduleMeasurement();
    }

    _applyScale(scale) {
        this._scale = scale;
        for (const actor of this._actors.keys()) {
            const effect = actor.get_effect(EFFECT_NAME);
            if (effect)
                effect.set_render_scale(scale);
        }
    }

    // ---- working out how much resolution a shader can afford ---------------
    //
    // Not by watching the frame rate. A shader that reaches the cap has only
    // said "fast enough", not how much room is left — at a cap of 30 and 30
    // fps a frame may have taken 1 ms or 30 ms. Raising the scale to find out
    // and lowering it again when it does not hold is exactly the oscillation
    // this has to avoid.
    //
    // Nor by the wall clock. Timing the gap between two paints was the first
    // answer and it was wrong in a way that took a while to see: the gap
    // cannot fall below one refresh interval, so it reported 6.9 ms for every
    // shader that fitted into a frame — the same figure for `drift`, which has
    // no loop, as for `tiny-clouds`, which saturates the card. That is why the
    // budget appeared to do nothing.
    //
    // So the GPU's own time for one pass is what the verdict is made from, out
    // of a timer query in the native effect. Because the cost of a fragment
    // shader is its fragment count, the time at any other scale is the
    // measured time times the square of the ratio — the prediction holds for
    // every step, not just the one it was taken at. A shader that was put on a
    // quarter and later measured again comes straight back up to full if it
    // can. Nothing is ever derived from the outcome of a previous change,
    // which is what keeps it from swinging.
    //
    // Measured: Oceanic at 3440x1440 takes 57 ms a frame, and 32 ms at half
    // the fragments — against 14 ms predicted. The square law understates the
    // cost of the cheap end because a part of each frame is fixed overhead,
    // and understating it is the safe direction: it never picks a scale
    // coarser than needed.
    _scheduleMeasurement() {
        this._cancelMeasurement();

        if (!this._settings.get_boolean('auto-downscale'))
            return;

        // A value in sources.nix is a decision, not a guess to be checked.
        if (typeof this._entry?.scale === 'number')
            return;

        const measured = this._settings.get_value('scales').deepUnpack();
        if (measured[this._scaleKey(this._entry)] !== undefined)
            return;

        // Not straight away. At login the Shell is still starting services and
        // laying out the overview, and a measurement taken into that reads
        // every shader as expensive.
        this._measureId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, MEASURE_DELAY, () => {
                this._measureId = 0;
                this._measure();
                return GLib.SOURCE_REMOVE;
            });
    }

    _cancelMeasurement() {
        if (this._measureId)
            GLib.source_remove(this._measureId);
        this._measureId = 0;

        this._stopTracing();

        if (this._measuring) {
            this._measuring = null;
            this._applyScale(this._scaleBeforeMeasuring);
        }
    }

    // Tracing is what makes the effect emit its frame signal, and it is not
    // free: a timed pass flushes Cogl's journal twice, so that the query
    // brackets this draw and nothing else. It is switched on for the
    // measurement window and for the trace setting, and off the rest of the
    // time.
    _startTracing(effect, onFrame) {
        this._stopTracing();

        this._tracedEffect = effect;
        this._traceId = effect.connect('frame', onFrame);
        effect.set_tracing(true);
    }

    _stopTracing() {
        if (!this._tracedEffect)
            return;

        this._tracedEffect.set_tracing(false);
        this._tracedEffect.disconnect(this._traceId);
        this._tracedEffect = null;
        this._traceId = 0;
    }

    // ---- the end-to-end path ------------------------------------------------
    //
    // Four spans, from the timer deciding a frame is due to the picture being
    // on the screen:
    //
    //   tick→draw   the repaint request waiting for the actor to be painted
    //   cpu         issuing the draw, which is all this side still does
    //   gpu         the shader pass itself, out of a GL timer query
    //   draw→screen that frame reaching the display
    //
    // The last of those is the reason the effect is native and not a few
    // hundred lines of JavaScript. ClutterStage::presented carries a
    // ClutterFrameInfo — a public struct in C, with the presentation time in
    // it, and no GI boxed type — so the signal is marked introspectable=0 and
    // GJS cannot connect to it at all.
    //
    // Reported as a median a second, not a line a frame: at a cap of 100 the
    // latter is a hundred lines a second and the journal is not the place for
    // it.
    _updateTracing() {
        // The measurement owns the effect's tracing while it runs, and puts it
        // back the way it found it afterwards.
        if (this._measuring)
            return;

        this._stopTraceReport();

        if (!this._settings.get_boolean('trace')) {
            this._stopTracing();
            return;
        }

        const actor = [...this._actors.keys()].find(
            a => a.mapped && a.monitor === Main.layoutManager.primaryIndex);
        const effect = actor?.get_effect(EFFECT_NAME);
        if (!effect)
            return;

        if (!effect.has_gpu_timer())
            console.log('shaderbg: no GPU timer query on this driver, ' +
                'the gpu span will read as a dash');

        const spans = { latency: [], cpu: [], gpu: [], present: [] };

        this._startTracing(effect,
            (_e, _serial, latency, cpu, gpu, present) => {
                if (latency >= 0) spans.latency.push(latency);
                if (cpu >= 0) spans.cpu.push(cpu);
                if (gpu >= 0) spans.gpu.push(gpu);
                if (present >= 0) spans.present.push(present);
            });

        this._traceReportId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, TRACE_REPORT, () => {
                const median = xs => {
                    if (xs.length === 0)
                        return '—';
                    xs.sort((a, b) => a - b);
                    return `${xs[Math.floor(xs.length / 2)].toFixed(2)} ms`;
                };

                const frames = Math.max(spans.latency.length, spans.gpu.length);
                if (frames > 0) {
                    console.log(`shaderbg: ${this._entry?.file} at ` +
                        `${this._scale}x, ${frames} frames — ` +
                        `tick→draw ${median(spans.latency)}, ` +
                        `cpu ${median(spans.cpu)}, ` +
                        `gpu ${median(spans.gpu)}, ` +
                        `draw→screen ${median(spans.present)}`);
                }

                for (const key of Object.keys(spans))
                    spans[key].length = 0;

                return GLib.SOURCE_CONTINUE;
            });
    }

    _stopTraceReport() {
        if (this._traceReportId)
            GLib.source_remove(this._traceReportId);
        this._traceReportId = 0;
    }

    _measure() {
        const actor = [...this._actors.keys()].find(
            a => a.mapped && a.monitor === Main.layoutManager.primaryIndex);
        const effect = actor?.get_effect(EFFECT_NAME);

        // Locked, or the desktop is not up. Come back rather than decide.
        if (!effect || this._paused) {
            this._retryMeasurement();
            return;
        }

        // No timer query on this driver, so there is no number to hold against
        // the budget. Full resolution is the honest answer rather than a
        // verdict reached from something else.
        if (!effect.has_gpu_timer()) {
            console.log('shaderbg: no GPU timer query on this driver, ' +
                'leaving every shader at full resolution');
            return;
        }

        // Always at full resolution, whatever it is currently rendering at.
        // That makes the prediction below a plain multiplication instead of a
        // ratio, and lets a shader that had been put on a quarter earn its way
        // back up.
        this._scaleBeforeMeasuring = this._scale;
        this._applyScale(1.0);

        this._measuring = effect;
        this._samples = [];
        this._startTracing(effect, (_e, _serial, _latency, _build, gpuMs) => {
            if (gpuMs >= 0)
                this._samples.push(gpuMs);
        });

        // The cap is left exactly where it is. The query times the pass and
        // not the pace, so there is nothing to be had from asking for frames
        // faster than the setting says — which also makes a measurement
        // invisible, instead of two seconds of the fans spinning up.
        this._measureId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, MEASURE_WINDOW_MS, () => {
                this._measureId = 0;
                this._finishMeasurement();
                return GLib.SOURCE_REMOVE;
            });
    }

    _retryMeasurement() {
        this._measureId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, MEASURE_RETRY, () => {
                this._measureId = 0;
                this._measure();
                return GLib.SOURCE_REMOVE;
            });
    }

    _finishMeasurement() {
        this._measuring = null;
        this._stopTracing();

        const samples = this._samples ?? [];
        this._samples = null;

        // The background was not drawn for any useful part of the window: the
        // overview took over, or a window covered it and Mutter culled it
        // away. Come back later rather than read that as a verdict.
        if (samples.length < MEASURE_MIN_SAMPLES) {
            this._applyScale(this._scaleBeforeMeasuring);
            this._retryMeasurement();
            return;
        }

        // The median, not the mean: one pass that landed behind something else
        // on the card is an outlier, and there is no reason to let it drag the
        // verdict.
        samples.sort((a, b) => a - b);
        const passTime = samples[Math.floor(samples.length / 2)] / 1000;

        // How much of each frame the shader may take. The rest is what the
        // compositor has left for the windows, and where the line goes is the
        // setting: at 10 % the card spends a tenth of its time on the
        // background, at 100 % the budget is the whole frame.
        //
        // Nothing is exempt from this any more. The old wall-clock timing
        // could not read below one refresh interval, so a budget under that
        // interval was a test no shader could pass and every shader had to be
        // let off it — which is exactly why a budget of 10 % used to leave the
        // card at 100 %. A GPU time has no such floor: 0.4 ms is 0.4 ms.
        const cap = Math.max(1, this._settings.get_int('fps-cap'));
        const budget = this._settings.get_int('frame-budget') / 100 / cap;

        // Measured at 1.0, so the prediction for a step is the square of that
        // step: a shader costs what its fragments cost.
        let chosen = SCALE_STEPS[SCALE_STEPS.length - 1];
        for (const step of SCALE_STEPS) {
            if (passTime * step ** 2 <= budget) {
                chosen = step;
                break;
            }
        }

        const measured = this._settings.get_value('scales').deepUnpack();
        measured[this._scaleKey(this._entry)] = chosen;
        this._settings.set_value('scales', new GLib.Variant('a{sd}', measured));

        console.log(`shaderbg: ${this._entry.file} takes ` +
            `${(passTime * 1000).toFixed(2)} ms of GPU at full resolution ` +
            `(budget ${(budget * 1000).toFixed(2)} ms), rendering at ${chosen}x`);

        this._applyScale(chosen);

        // The measurement had tracing to itself; hand it back if the setting
        // wants it.
        this._updateTracing();
    }

    _readShader(file) {
        const path = GLib.build_filenamev([this.path, 'shaders', file]);
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (ok)
                return new TextDecoder().decode(bytes);
        } catch (err) {
            console.error(`shaderbg: cannot read ${file} — ${err}`);
        }
        return null;
    }

    // ---- attaching to the Shell's background actors -----------------------

    _attach(actor) {
        if (!this._source || this._actors.has(actor))
            return;

        // The prelude is glued on here rather than in C: it is text, it is where
        // every Shadertoy-to-Cogl workaround lives, and it is far easier to
        // iterate on in a file the Shell re-reads than in one that needs a
        // rebuild. C adds only the snippet body that calls into it.
        const effect = ShaderBg.Effect.new(
            DECLARATIONS + '\n' + this._source, this._noiseTexture());
        effect.set_render_scale(this._scale);
        actor.add_effect_with_name(EFFECT_NAME, effect);

        // Give the geometry before the actor is ever painted. The first paint
        // can happen before the first tick, and a shader that runs with zeroed
        // uniforms is the hang described in the prelude.
        this._setGeometry(actor, effect);

        // Keep the handler id: disable() has to take these back off again, or
        // enabling a second time stacks another one on every surviving actor.
        this._actors.set(actor, actor.connect('destroy', () => {
            this._actors.delete(actor);
        }));
    }

    _detachAll() {
        for (const [actor, handlerId] of this._actors) {
            actor.disconnect(handlerId);
            if (actor.get_effect(EFFECT_NAME))
                actor.remove_effect_by_name(EFFECT_NAME);
        }
        this._actors.clear();
    }

    // Walks the whole stage rather than one container: background actors live
    // under window_group for the desktop and inside each workspace preview in
    // the overview, and both may already exist when the extension is enabled.
    _forEachBackground(fn, actor = global.stage) {
        if (actor instanceof Meta.BackgroundActor)
            fn(actor);
        for (const child of actor.get_children())
            this._forEachBackground(fn, child);
    }

    _rebuild() {
        const entry = this._pick();
        if (!entry)
            return;

        const source = this._readShader(entry.file);
        if (source === null)
            return;

        // A ClutterShaderEffect takes its source exactly once
        // (clutter_shader_effect_set_shader_source), so switching shaders
        // means new effect objects, not new source on the old ones.
        this._detachAll();

        this._source = source;
        this._entry = entry;
        this._shaderSpeed = this._speedOf(entry);
        this._scale = this._scaleOf(entry);
        this._time = 0;
        this._frame = 0;

        this._forEachBackground(a => this._attach(a));

        this._updatePaused();
        this._restartTicker();
        this._scheduleMeasurement();
        this._updateTracing();
    }

    // ---- driving the clock ------------------------------------------------

    // A Clutter.Timeline would hang off the monitor's frame clock and so run
    // at 144 Hz whether or not a wallpaper needs it. A plain timeout lets the
    // repaint rate be a setting.
    _restartTicker() {
        this._stopTicker();

        if (this._paused || this._actors.size === 0)
            return;

        this._lastTick = GLib.get_monotonic_time();

        // A timer, deliberately, and not a Clutter.Timeline on the frame
        // clock. The timeline paces exactly — measured 60.0, 30.1, 15.2 and
        // 5.0 fps against a timer's 40, 24, 13.5 and 4.8 — but it achieves
        // that by being advanced every single frame, which keeps the stage
        // updating at the display's rate whatever the cap says. That showed
        // up as a floor of about 20 % GPU that would not move between a cap
        // of 60 and a cap of 5: not the shader, just the compositor never
        // being allowed back to sleep.
        //
        // A timer wakes it only when a frame is wanted. The price is that
        // requests land between vblanks, so the achieved rate quantises to
        // the refresh rate and comes out under the cap. For a wallpaper that
        // is much the better trade.
        const fps = Math.max(1, this._settings.get_int('fps-cap'));
        this._tickId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, Math.round(1000 / fps), () => {
                this._tick();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _stopTicker() {
        if (this._tickId)
            GLib.source_remove(this._tickId);
        this._tickId = 0;
    }

    // Time is accumulated rather than derived from a start stamp, so changing
    // the speed bends the curve from here on instead of making the shader
    // jump, and a pause costs nothing when it resumes.
    _tick() {
        const now = GLib.get_monotonic_time();

        const delta = (now - this._lastTick) / 1e6;
        this._lastTick = now;

        const pauseFullscreen = this._settings.get_boolean('pause-fullscreen');
        const speed = this._shaderSpeed;
        this._time += delta * speed;
        this._frame++;

        for (const actor of this._actors.keys()) {
            // The overview's workspace previews are background actors too, and
            // there is one per workspace. Skipping the unmapped ones means they
            // cost nothing until the overview is actually open.
            if (!actor.mapped)
                continue;

            // Per monitor, not per session: a game filling one screen is no
            // reason to freeze the background on another.
            if (pauseFullscreen && global.display.get_monitor_in_fullscreen(actor.monitor))
                continue;

            const effect = actor.get_effect(EFFECT_NAME);
            if (!effect)
                continue;

            this._setGeometry(actor, effect);

            effect.mark_tick(now);
            effect.set_uniform('iTime', this._time);
            effect.set_uniform('iTimeDelta', delta * speed);
            effect.set_uniform('iFrameF', this._frame);
            effect.queue_repaint();
        }
    }

    // One texture for every effect on every monitor: it is the same noise,
    // it is read-only, and a 256x256 RGBA texture built per actor would be
    // 256 kB of pointless duplication.
    _noiseTexture() {
        if (!this._noise) {
            const context = global.stage.context.get_backend().get_cogl_context();
            this._noise = noiseTexture(context);
        }
        return this._noise;
    }

    // All that is left of the geometry is the resolution the shader composes
    // for, which is the monitor's and has nothing to do with how large the
    // actor happens to be drawn. Where the actor is no longer matters — see
    // the note on cogl_tex_coord_in in the prelude.
    //
    // How large it is does not matter either, and that is what keeps the
    // overview smooth. The buffer is sized from this resolution, so a
    // workspace preview being animated from full size down to a thumbnail
    // moves only the rectangle the finished texture is stretched over.
    // Sizing it from the actor instead meant throwing away a 19 MB texture
    // and redrawing the shader on every frame of that animation, which is
    // what the flicker on opening the overview was.
    _setGeometry(actor, effect) {
        const monitor = Main.layoutManager.monitors[actor.monitor];
        if (!monitor)
            return;

        effect.set_resolution(monitor.width, monitor.height);
    }

    // Fullscreen is handled per actor in the tick, because it is a property of
    // one monitor. What stops the clock outright is the session going away.
    _updatePaused() {
        const paused = Main.sessionMode.isLocked;
        if (paused === this._paused)
            return;

        this._paused = paused;
        this._restartTicker();
    }

    _scheduleMidnight() {
        const now = new Date();
        const next = new Date(
            now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 5);
        const seconds = Math.max(1, Math.ceil((next.getTime() - now.getTime()) / 1000));

        this._midnightId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, seconds, () => {
                this._midnightId = 0;
                this._rebuild();
                this._scheduleMidnight();
                return GLib.SOURCE_REMOVE;
            });
    }
}
