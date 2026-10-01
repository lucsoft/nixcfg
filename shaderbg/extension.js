import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

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

    vec4 color = vec4(0.0, 0.0, 0.0, 1.0);
    mainImage(color, gl_FragCoord.xy);
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

export default class ShaderBgExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._sources = this._loadSources();

        this._layers = [];
        this._tickId = 0;
        this._midnightId = 0;
        this._paused = false;
        this._time = 0;
        this._shaderSpeed = 1;

        this._settingsIds = [
            'changed::fps-cap',
            'changed::pause-fullscreen',
        ].map(s => this._settings.connect(s, () => this._restartTicker()));

        this._settingsIds.push(...[
            'changed::override-index',
            'changed::override-day',
        ].map(s => this._settings.connect(s, () => this._rebuild())));

        this._displayId = global.display.connect(
            'in-fullscreen-changed', () => this._updatePaused());
        this._sessionId = Main.sessionMode.connect(
            'updated', () => this._updatePaused());
        this._monitorsId = Main.layoutManager.connect(
            'monitors-changed', () => this._rebuild());

        this._rebuild();
        this._scheduleMidnight();
    }

    disable() {
        for (const id of this._settingsIds ?? [])
            this._settings.disconnect(id);
        this._settingsIds = null;

        if (this._displayId)
            global.display.disconnect(this._displayId);
        if (this._sessionId)
            Main.sessionMode.disconnect(this._sessionId);
        if (this._monitorsId)
            Main.layoutManager.disconnect(this._monitorsId);
        this._displayId = this._sessionId = this._monitorsId = 0;

        this._stopTicker();

        if (this._midnightId)
            GLib.source_remove(this._midnightId);
        this._midnightId = 0;

        this._destroyLayers();
        this._settings = null;
        this._sources = null;
    }

    // ---- shader set -------------------------------------------------------

    // sources.json is generated from sources.nix at build time, so the set and
    // the order it rotates in are part of the configuration, not of the code.
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
        return FALLBACK;
    }

    // Days since the epoch, counted in local time. Monotonic across a day
    // boundary, which is all the rotation needs — the absolute value never
    // leaves this file except as a stored override marker.
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

        // A hand-picked shader is deliberately tied to the day it was picked
        // on, so "stay on this one" expires by itself at midnight.
        if (index >= 0 && index < count && day === this._today())
            return this._sources[index];

        return this._sources[((this._today() % count) + count) % count];
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

    // ---- actors -----------------------------------------------------------

    _rebuild() {
        this._destroyLayers();

        const entry = this._pick();
        if (!entry)
            return;

        const source = this._readShader(entry.file);
        if (source === null)
            return;

        this._shaderSpeed = entry.speed ?? 1;
        this._time = 0;

        for (const monitor of Main.layoutManager.monitors) {
            // ShaderEffect derives from ClutterOffscreenEffect: it filters what
            // the actor paints, so an actor painting nothing never gets a pass.
            // The opaque fill exists purely to give the shader a surface, and
            // is overwritten by every fragment.
            const actor = new Clutter.Actor({
                x: monitor.x,
                y: monitor.y,
                width: monitor.width,
                height: monitor.height,
                reactive: false,
                backgroundColor: new Cogl.Color({ red: 0, green: 0, blue: 0, alpha: 255 }),
            });

            const scale = monitor.geometry_scale || 1;
            const effect = new ShaderBgEffect(source);
            effect.setFloat('iResX', monitor.width * scale);
            effect.setFloat('iResY', monitor.height * scale);
            actor.add_effect(effect);

            // _backgroundGroup sits at the bottom of window_group
            // (ui/layout.js), and appending puts this above the stock
            // MetaBackgroundActor but still below every window.
            Main.layoutManager._backgroundGroup.add_child(actor);
            this._layers.push({ actor, effect });
        }

        this._updatePaused();
        this._restartTicker();
    }

    _destroyLayers() {
        for (const { actor } of this._layers ?? [])
            actor.destroy();
        this._layers = [];
    }

    // ---- driving the clock ------------------------------------------------

    // A Clutter.Timeline would hang off the monitor's frame clock and so run at
    // 144 Hz whether or not a wallpaper needs it. A plain timeout lets the
    // repaint rate be a setting.
    _restartTicker() {
        this._stopTicker();

        if (this._paused || this._layers.length === 0)
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

    // Time is accumulated rather than derived from a start stamp, so that
    // changing the speed bends the curve from here on instead of making the
    // shader jump, and so a pause costs nothing when it resumes.
    _tick() {
        const now = GLib.get_monotonic_time();
        const delta = (now - this._lastTick) / 1e6;
        this._lastTick = now;

        const speed = this._settings.get_double('speed') * this._shaderSpeed;
        this._time += delta * speed;
        this._frame = (this._frame ?? 0) + 1;

        for (const { effect } of this._layers) {
            effect.setFloat('iTime', this._time);
            effect.setFloat('iTimeDelta', delta * speed);
            effect.setFloat('iFrameF', this._frame);
            // The effect's own queue, not the actor's: an offscreen effect
            // caches its framebuffer, and only this invalidates that cache.
            // Clutter.Actor.queue_repaint() is also simply gone in 50 —
            // queue_redraw() is what replaced it.
            effect.queue_repaint();
        }
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
