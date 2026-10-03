import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Meta from 'gi://Meta';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
// Cogl speaks an old GLSL: no #version, no in/out, texture2D() rather than
// texture(), and the fragment writes to cogl_color_out. Shadertoy assumes the
// opposite of all four. This prelude is glued in front of every shader so the
// files in shaders/ can stay as close to their upstream form as possible.
//
// iResolution has to be a global rather than a local in main(): mainImage is a
// separate function and reaches it by name. The i* names that no single-pass
// shader can be given real values for — the channels, the mouse, the date —
// are declared anyway, because a shader that merely mentions one of them
// should still compile instead of taking the whole set down with it.
const PRELUDE = `
uniform sampler2D tex;
uniform float iTime;
uniform float iTimeDelta;
uniform float iFrameF;
uniform float iResX;
uniform float iResY;

// gl_FragCoord runs over the actor, which is not always the monitor. The
// overview's workspace preview is allocated smaller — and animates to that
// size over several frames. Feeding its size in as iResolution made every
// shader recompose itself during the transition instead of simply appearing
// scaled down. So iResolution stays the monitor, and the coordinates are
// stretched to match: same picture, fewer samples.
uniform float iCoordScaleX;
uniform float iCoordScaleY;

// Every channel carries the same locally generated noise, so one number
// describes all four resolutions.
uniform float iChannelSize;

uniform sampler2D iChannel0;
uniform sampler2D iChannel1;
uniform sampler2D iChannel2;
uniform sampler2D iChannel3;

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

void main()
{
    iResolution = vec3(iResX, iResY, 1.0);
    iFrame = int(iFrameF);

    iChannelResolution[0] = vec3(iChannelSize, iChannelSize, 1.0);
    iChannelResolution[1] = iChannelResolution[0];
    iChannelResolution[2] = iChannelResolution[0];
    iChannelResolution[3] = iChannelResolution[0];

    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    mainImage(color, gl_FragCoord.xy * vec2(iCoordScaleX, iCoordScaleY));
    cogl_color_out = vec4(color.rgb, 1.0);
}
`;

const FALLBACK = [{ file: 'drift.frag', name: 'drift', author: 'lucsoft', speed: 1.0 }];

const ShaderBgEffect = GObject.registerClass(
class ShaderBgEffect extends Clutter.ShaderEffect {
    // shader-type is left at its default rather than set: the property takes a
    // CoglShaderType, not a Clutter one, and it already defaults to fragment
    // (clutter-shader-effect.c:442). Naming it is how this first broke.
    constructor(source) {
        super({});
        this.set_shader_source(PRELUDE + '\n' + source);
    }

    // GJS marshals a JS number that happens to be integral into an int GValue,
    // which a float uniform refuses — so a shader would break only on the
    // frames where its time landed on a whole number. blur-my-shell shaves off
    // 1e-6 everywhere for the same reason (effects/noise.js:59).
    setFloat(name, value) {
        this.set_uniform_value(name, parseFloat(value - 1e-6));
    }
});

const EFFECT_NAME = 'shaderbg';

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

        this._settingsIds = [
            'changed::fps-cap',
            'changed::pause-fullscreen',
        ].map(s => this._settings.connect(s, () => this._restartTicker()));

        this._settingsIds.push(...[
            'changed::override-index',
            'changed::override-day',
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
        Background.BackgroundManager.prototype._createBackgroundActor = function () {
            const actor = self._origCreateActor.call(this);
            self._attach(actor);
            return actor;
        };

        this._rebuild();
        this._scheduleMidnight();
    }

    disable() {
        if (this._origCreateActor) {
            Background.BackgroundManager.prototype._createBackgroundActor =
                this._origCreateActor;
            this._origCreateActor = null;
        }

        for (const id of this._settingsIds ?? [])
            this._settings.disconnect(id);
        this._settingsIds = null;

        if (this._displayId)
            global.display.disconnect(this._displayId);
        if (this._sessionId)
            Main.sessionMode.disconnect(this._sessionId);
        this._displayId = this._sessionId = 0;

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

    // sources.nix carries the speed a shader ships with; the preferences write
    // into `speeds` when one gets tuned. Only tuned shaders appear there, so
    // the committed value stays the fallback rather than being copied around.
    _speedOf(entry) {
        if (!entry)
            return 1;

        const tuned = this._settings.get_value('speeds').deepUnpack();
        return tuned[entry.file] ?? entry.speed ?? 1;
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

        actor.add_effect_with_name(EFFECT_NAME, new ShaderBgEffect(this._source));

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
        this._time = 0;
        this._frame = 0;

        this._forEachBackground(a => this._attach(a));

        this._updatePaused();
        this._restartTicker();
    }

    // ---- driving the clock ------------------------------------------------

    // A Clutter.Timeline would hang off the monitor's frame clock and so run
    // at 144 Hz whether or not a wallpaper needs it. A plain timeout lets the
    // repaint rate be a setting.
    _restartTicker() {
        this._stopTicker();

        if (this._paused || this._actors.size === 0)
            return;

        const fps = Math.max(1, this._settings.get_int('fps-cap'));
        this._lastTick = GLib.get_monotonic_time();
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

        const speed = this._shaderSpeed;
        this._time += delta * speed;
        this._frame++;

        for (const actor of this._actors.keys()) {
            // The overview's workspace previews are background actors too, and
            // there is one per workspace. Skipping the unmapped ones means they
            // cost nothing until the overview is actually open.
            if (!actor.mapped)
                continue;

            const effect = actor.get_effect(EFFECT_NAME);
            if (!effect)
                continue;

            // The resolution the shader composes for is the monitor's, never
            // the actor's — see the note on iCoordScale in the prelude. Both
            // are read every tick rather than at attach time, because the
            // overview previews are laid out after creation and the monitor
            // itself can change under us.
            const monitor = Main.layoutManager.monitors[actor.monitor];
            if (!monitor || actor.width <= 0 || actor.height <= 0)
                continue;

            this._bindChannels(effect);

            effect.setFloat('iResX', monitor.width);
            effect.setFloat('iResY', monitor.height);
            effect.setFloat('iCoordScaleX', monitor.width / actor.width);
            effect.setFloat('iCoordScaleY', monitor.height / actor.height);
            effect.setFloat('iTime', this._time);
            effect.setFloat('iTimeDelta', delta * speed);
            effect.setFloat('iFrameF', this._frame);
            effect.queue_repaint();
        }
    }

    // An offscreen effect has no pipeline until it has painted once, and it
    // may build a new one later, so this is checked per tick rather than at
    // attach time — but the actual binding only happens when the pipeline is
    // one we have not seen.
    _bindChannels(effect) {
        const pipeline = effect.get_pipeline();
        if (!pipeline || effect._sbPipeline === pipeline)
            return;

        if (!this._noise) {
            const context = global.stage.context.get_backend().get_cogl_context();
            this._noise = noiseTexture(context);
        }

        // Layer 0 is the actor's own offscreen texture, which the prelude
        // declares as `tex` and the shaders never read. The channels go above
        // it, and the sampler uniform is the layer index.
        for (let i = 0; i < 4; i++) {
            const layer = i + 1;
            pipeline.set_layer_texture(layer, this._noise);
            pipeline.set_layer_wrap_mode(layer, Cogl.PipelineWrapMode.REPEAT);
            effect.set_uniform_value(`iChannel${i}`, layer);
        }

        effect.setFloat('iChannelSize', CHANNEL_SIZE);
        effect._sbPipeline = pipeline;
    }

    _updatePaused() {
        const hidden = this._settings.get_boolean('pause-fullscreen') &&
            Main.layoutManager.monitors.some(
                (_, i) => global.display.get_monitor_in_fullscreen(i));

        const paused = hidden || Main.sessionMode.isLocked;
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
