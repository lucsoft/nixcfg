import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Graphene from 'gi://Graphene';
import Meta from 'gi://Meta';

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

// All the work is in _sb_fragment, declared above the shader source where the
// shader's own macros cannot rewrite it.
const BODY = `
    cogl_color_out = _sb_fragment();
`;


const EFFECT_NAME = 'shaderbg';

// The resolutions a shader may be rendered at, largest first. Three steps and
// not a continuum: each one is a whole new buffer, and the difference between
// 0.6 and 0.65 is not worth a reallocation.
const SCALE_STEPS = [1.0, 0.5, 0.25];

// A frame may take this fraction of the interval the cap allows. Half, so
// that the compositor still has somewhere to put the windows.
const MEASURE_BUDGET = 0.5;

const MEASURE_DELAY = 8;        // seconds to let the session settle first
const MEASURE_WINDOW_MS = 2000; // how long the cap stays lifted
const MEASURE_RETRY = 60;       // seconds, when the desktop was not visible
const MEASURE_MIN_SAMPLES = 3;  // fewer than this and the window says nothing

// A gap longer than this is the background not being drawn — the overview
// took over, or a window covered it and Mutter culled it away. It is not a
// slow frame, and averaging it in would read a hidden background as an
// impossibly expensive shader. The cutoff is 2.5 frames a second; a shader
// genuinely slower than that is past helping and belongs at the smallest
// step whatever the rest of the numbers say.
const MEASURE_STALL = 400000;   // microseconds

// A ClutterEffect, deliberately, and not a ClutterShaderEffect.
//
// ClutterShaderEffect derives from ClutterOffscreenEffect, and that class
// decides the size of its own buffer: clutter_offscreen_effect_pre_paint ties
// the target size to the paint volume, the viewport to the target size, and
// the modelview scale to the ratio between them. Viewport and modelview cancel
// out, so the pixel density is nailed to the stage's and there is no way in
// from outside — three attempts at rendering smaller produced three different
// wrong pictures, all out of that one coupling.
//
// A plain ClutterEffect derives nothing from anything. It is handed a paint
// node and may build whatever it likes under it, so the buffer size, the
// viewport and the projection are all ours to pick. That is exactly what
// gnome-shell's own ShellBlurEffect does to render its blur at a third of the
// resolution, and this is modelled on it (src/shell-blur-effect.c).
//
// It also stays an *effect on the background actor*, so MetaBackgroundActor
// keeps its own content and stays cullable. That matters more than the
// downscaling does: Mutter dropping the background once a window covers it is
// worth 54 W against 17 W here, which is larger than any saving below.
const ShaderBgEffect = GObject.registerClass(
class ShaderBgEffect extends Clutter.Effect {
    constructor(source, scale, noise) {
        super({});

        this._scale = scale;
        this._locations = new Map();

        this._texture = null;
        this._framebuffer = null;
        this._bufferWidth = 0;
        this._bufferHeight = 0;

        const context = global.stage.context.get_backend().get_cogl_context();

        // What the shader draws with. The hook runs after Cogl's own fragment
        // code and overwrites cogl_color_out, which is why the declarations
        // may safely #define names Cogl's generated code does not use.
        this._pipeline = Cogl.Pipeline.new(context);
        this._pipeline.add_snippet(Cogl.Snippet.new(
            Cogl.SnippetHook.FRAGMENT, DECLARATIONS + '\n' + source, BODY));

        // Layers 0..3 are iChannel0..3. They are set even for shaders that
        // read none of them: layer 0 existing is what makes Cogl emit
        // cogl_tex_coord0_in, which the body needs for its coordinates.
        for (let i = 0; i < 4; i++) {
            this._pipeline.set_layer_texture(i, noise);
            this._pipeline.set_layer_wrap_mode(i, Cogl.PipelineWrapMode.REPEAT);
        }

        // What puts the result back on screen. Linear filtering is what turns
        // a half-resolution buffer into a soft picture rather than a blocky
        // one; for the kind of shader that gets downscaled — clouds, fluids,
        // raymarched fog — the difference is close to invisible.
        this._present = Cogl.Pipeline.new(context);
        this._present.set_layer_filters(0,
            Cogl.PipelineFilter.LINEAR, Cogl.PipelineFilter.LINEAR);
        this._present.set_layer_wrap_mode(0, Cogl.PipelineWrapMode.CLAMP_TO_EDGE);

        this.setFloat('iChannelSize', noise.get_width());
    }

    // The fraction of the actor's size the shader is actually rendered at.
    // Changing it throws the buffer away; the next paint builds the new one.
    get renderScale() {
        return this._scale;
    }

    set renderScale(scale) {
        if (scale === this._scale)
            return;

        this._scale = scale;
        this._dropBuffer();
        this.queue_repaint();
    }

    // Cogl addresses uniforms by location rather than by name, and the lookup
    // is a string hash into a per-context table — worth doing once per name
    // rather than once per frame. Unlike ClutterShaderEffect there is no
    // GValue in the way, so the integral-number trap that needed a 1e-6 fudge
    // before does not exist here.
    setFloat(name, value) {
        let location = this._locations.get(name);
        if (location === undefined) {
            location = this._pipeline.get_uniform_location(name);
            this._locations.set(name, location);
        }

        this._pipeline.set_uniform_1f(location, value);
    }

    // Timing the shader means timing the gap between *its* paints, not the
    // stage's. The stage paints for all sorts of reasons, and Mutter stops
    // painting the background altogether once a window covers it — counting
    // stage frames would read a culled background as a slow shader.
    startSampling() {
        this._samples = [];
        this._lastPaint = 0;
    }

    stopSampling() {
        const samples = this._samples ?? [];
        this._samples = null;
        return samples;
    }

    _dropBuffer() {
        this._texture = null;
        this._framebuffer = null;
        this._bufferWidth = 0;
        this._bufferHeight = 0;
    }

    _ensureBuffer(width, height) {
        const w = Math.max(1, Math.floor(width * this._scale));
        const h = Math.max(1, Math.floor(height * this._scale));

        if (this._framebuffer && this._bufferWidth === w && this._bufferHeight === h)
            return true;

        this._dropBuffer();

        const context = global.stage.context.get_backend().get_cogl_context();
        const texture = Cogl.Texture2D.new_with_size(context, w, h);
        if (!texture)
            return false;

        const framebuffer = Cogl.Offscreen.new_with_texture(texture);
        if (!framebuffer)
            return false;

        // The buffer's own coordinate space: 0..w across, 0..h down. Picking
        // this is the whole point of deriving from ClutterEffect — it is the
        // step ClutterOffscreenEffect does for itself, and wrongly for us.
        const projection = new Graphene.Matrix();
        projection.init_translate(
            new Graphene.Point3D({ x: -w / 2, y: -h / 2, z: 0 }));
        projection.scale(2 / w, -2 / h, 1);
        framebuffer.set_projection_matrix(projection);

        this._present.set_layer_texture(0, texture);

        this._texture = texture;
        this._framebuffer = framebuffer;
        this._bufferWidth = w;
        this._bufferHeight = h;
        return true;
    }

    // Two nested nodes, and the nesting is what does the scaling:
    //
    //   LayerNode(buffer, present)   draws its children into the buffer, then
    //     rectangle 0..actor         draws the buffer over the whole actor
    //     PipelineNode(shader)
    //       rectangle 0..buffer      fills the buffer, at the buffer's size
    //
    // The shader therefore runs once per buffer pixel, and the buffer is
    // stretched to the actor afterwards. No chain-up: the actor's own content
    // is the wallpaper file underneath, and the shader replaces it.
    vfunc_paint_node(node, _paintContext, _paintFlags) {
        const actor = this.get_actor();
        if (!actor)
            return;

        const box = actor.get_allocation_box();
        const width = box.get_width();
        const height = box.get_height();
        if (width < 1 || height < 1)
            return;

        if (!this._ensureBuffer(width, height))
            return;

        if (this._samples) {
            const now = GLib.get_monotonic_time();
            if (this._lastPaint)
                this._samples.push(now - this._lastPaint);
            this._lastPaint = now;
        }

        const layer = Clutter.LayerNode.new_to_framebuffer(
            this._framebuffer, this._present);
        node.add_child(layer);
        layer.add_rectangle(new Clutter.ActorBox({
            x1: 0, y1: 0, x2: width, y2: height,
        }));

        const shader = Clutter.PipelineNode.new(this._pipeline);
        layer.add_child(shader);
        shader.add_rectangle(new Clutter.ActorBox({
            x1: 0, y1: 0, x2: this._bufferWidth, y2: this._bufferHeight,
        }));
    }

    // Taken off an actor, the buffer is so much dead video memory — a
    // 3440x1440 RGBA texture is 19 MB, and there is one per monitor and per
    // workspace preview.
    vfunc_set_actor(actor) {
        if (!actor)
            this._dropBuffer();

        super.vfunc_set_actor(actor);
    }
});

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
        this._capOverride = 0;

        // pause-fullscreen is read inside the tick, but the timer's interval is
        // the cap, so changing that one has to rebuild it.
        this._settingsIds = [
            this._settings.connect('changed::fps-cap', () => this._restartTicker()),
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

    // The fastest a frame can possibly be observed. peek_stage_views is the
    // only path to it from an extension — neither the stage nor an actor hands
    // out its frame clock, but a stage view carries the rate itself.
    _refreshRate() {
        let best = 0;
        for (const view of global.stage.peek_stage_views?.() ?? [])
            best = Math.max(best, view.get_refresh_rate());

        return best > 0 ? best : 60;
    }

    _applyScale(scale) {
        this._scale = scale;
        for (const actor of this._actors.keys()) {
            const effect = actor.get_effect(EFFECT_NAME);
            if (effect)
                effect.renderScale = scale;
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
    // So the frame *time* is measured instead, with the cap briefly lifted,
    // and the scale follows from it in one step. Because the cost of a
    // fragment shader is its fragment count, the time at any other scale is
    // the measured time times the square of the ratio — the prediction holds
    // for every step, not just the one it was taken at. A shader that was put
    // on a quarter and later measured again comes straight back up to full if
    // it can. Nothing is ever derived from the outcome of a previous change,
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

        if (this._measuring) {
            this._measuring.stopSampling();
            this._measuring = null;
            this._capOverride = 0;
            this._applyScale(this._scaleBeforeMeasuring);
            this._restartTicker();
        }
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

        // Always at full resolution, whatever it is currently rendering at.
        // A downscaled shader is almost always fast enough to be limited by
        // the display rather than by itself, and a frame time pinned to the
        // refresh rate says nothing about how much work it really is — so a
        // shader that had been put on a quarter could never be shown to have
        // earned its way back up. Measuring at 1.0 every time also makes the
        // prediction below a plain multiplication instead of a ratio.
        this._scaleBeforeMeasuring = this._scale;
        this._applyScale(1.0);

        this._measuring = effect;
        effect.startSampling();

        // Off the leash for the length of the window: the frame time is only
        // visible when the shader, and not the timer, is what sets the pace.
        this._capOverride = 1000;
        this._restartTicker();

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
        const effect = this._measuring;
        this._measuring = null;
        this._capOverride = 0;

        const samples = effect.stopSampling()
            .filter(gap => gap <= MEASURE_STALL);
        this._restartTicker();

        // Nothing left after the stalls were dropped: the background was not
        // on screen for any useful part of the window. Come back later rather
        // than read that as a verdict.
        if (samples.length < MEASURE_MIN_SAMPLES) {
            this._applyScale(this._scaleBeforeMeasuring);
            this._retryMeasurement();
            return;
        }

        // The median, not the mean: a compositor frame that waited on
        // something else is an outlier, and there is no reason to let one
        // drag the verdict.
        samples.sort((a, b) => a - b);
        const frameTime = samples[Math.floor(samples.length / 2)] / 1e6;

        // The shader never gets to paint faster than the display refreshes,
        // so a frame time at the refresh interval is the floor of what can be
        // observed and not a reading of the shader at all. Asking for
        // anything below it would downscale every shader on a monitor fast
        // enough to make the question moot — at 144 Hz and a cap of 120 the
        // budget alone would be 4.2 ms against a floor of 6.9 ms, and
        // everything would fail a test nothing can pass.
        const cap = Math.max(1, this._settings.get_int('fps-cap'));
        const floor = 1 / this._refreshRate();
        const budget = Math.max(MEASURE_BUDGET / cap, floor * 1.15);

        // Measured at 1.0, so the prediction for a step is the square of that
        // step: a shader costs what its fragments cost.
        let chosen = SCALE_STEPS[SCALE_STEPS.length - 1];
        for (const step of SCALE_STEPS) {
            if (frameTime * step ** 2 <= budget) {
                chosen = step;
                break;
            }
        }

        const measured = this._settings.get_value('scales').deepUnpack();
        measured[this._scaleKey(this._entry)] = chosen;
        this._settings.set_value('scales', new GLib.Variant('a{sd}', measured));

        console.log(`shaderbg: ${this._entry.file} takes ` +
            `${(frameTime * 1000).toFixed(1)} ms a frame at full resolution ` +
            `(budget ${(budget * 1000).toFixed(1)} ms), rendering at ${chosen}x`);

        this._applyScale(chosen);
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

        const effect = new ShaderBgEffect(
            this._source, this._scale, this._noiseTexture());
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
        const fps = this._capOverride ||
            Math.max(1, this._settings.get_int('fps-cap'));
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

            effect.setFloat('iTime', this._time);
            effect.setFloat('iTimeDelta', delta * speed);
            effect.setFloat('iFrameF', this._frame);
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
    _setGeometry(actor, effect) {
        const monitor = Main.layoutManager.monitors[actor.monitor];
        if (!monitor)
            return;

        effect.setFloat('iResX', monitor.width);
        effect.setFloat('iResY', monitor.height);
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
