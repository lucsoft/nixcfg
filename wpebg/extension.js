import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';

// The player and the effect, in C. home.nix puts the typelib on
// GI_TYPELIB_PATH, which the Shell only reads at login.
import WpeBg from 'gi://WpeBg';

import * as Background from 'resource:///org/gnome/shell/ui/background.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

import { readProject } from './workshop.js';

const EFFECT_NAME = 'wpebg';

export default class WpeBgExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._actors = new Map();
        this._active = false;

        const context = global.stage.context.get_backend().get_cogl_context();
        this._player = WpeBg.Player.new(context);
        this._errorId = this._player.connect('error', (_p, message) => {
            console.error(`wpebg: ${this._project?.title ?? '?'} — ${message}`);
        });

        this._settingsIds = [
            this._settings.connect('changed::item', () => this._load()),
            this._settings.connect('changed::pause-fullscreen', () => this._updatePaused()),
        ];

        this._displayId = global.display.connect(
            'in-fullscreen-changed', () => this._updatePaused());
        this._sessionId = Main.sessionMode.connect(
            'updated', () => this._updatePaused());

        // The same factory hook as shaderbg, for the same reason: the overview
        // builds a background per workspace, and patching the one place they
        // are all made from catches the ones made later too.
        const self = this;
        this._origCreateActor = Background.BackgroundManager.prototype._createBackgroundActor;
        this._patchedCreateActor = function () {
            const actor = self._origCreateActor.call(this);
            self._attach(actor);
            return actor;
        };
        Background.BackgroundManager.prototype._createBackgroundActor =
            this._patchedCreateActor;

        this._load();
    }

    disable() {
        if (Background.BackgroundManager.prototype._createBackgroundActor ===
            this._patchedCreateActor) {
            Background.BackgroundManager.prototype._createBackgroundActor =
                this._origCreateActor;
        }
        this._origCreateActor = this._patchedCreateActor = null;

        for (const id of this._settingsIds)
            this._settings.disconnect(id);
        global.display.disconnect(this._displayId);
        Main.sessionMode.disconnect(this._sessionId);

        this._detachAll();

        // Stopping is what lets go of the decoder and the file; dropping the
        // last reference does the rest.
        this._player.set_uri(null);
        this._player.disconnect(this._errorId);
        this._player = null;

        this._settings = null;
        this._project = null;
    }

    // ---- the chosen item ---------------------------------------------------

    _load() {
        const dir = this._settings.get_string('item');
        const project = dir ? readProject(dir) : null;

        if (dir && !project)
            console.error(`wpebg: ${dir} has no readable project.json`);
        else if (project && !project.video)
            console.error(`wpebg: ${project.title} is a ${project.type} wallpaper, ` +
                'only video ones can be shown');

        this._project = project?.video ? project : null;
        this._active = this._project !== null;

        if (!this._active) {
            this._detachAll();
            this._player.set_uri(null);
            return;
        }

        this._player.set_uri(Gio.File.new_for_path(this._project.video).get_uri());
        this._forEachBackground(a => this._attach(a));
        this._updatePaused();
    }

    // ---- attaching to the Shell's background actors ------------------------

    _attach(actor) {
        if (!this._active || this._actors.has(actor))
            return;

        const effect = WpeBg.Effect.new(this._player);

        // First in the chain, ahead of anything already on the actor. A
        // ClutterEffect that draws without chaining up hides every effect after
        // it, so whichever comes first owns the picture. shaderbg's effect never
        // chains up; this one does whenever there is no frame yet, so with both
        // enabled the shader shows until the video starts, and after the video
        // is switched off. Clutter appends and has no insert, hence taking the
        // others off and putting them back behind it.
        const others = actor.get_effects();
        for (const other of others)
            actor.remove_effect(other);
        actor.add_effect_with_name(EFFECT_NAME, effect);
        for (const other of others) {
            const name = other.get_name();
            if (name)
                actor.add_effect_with_name(name, other);
            else
                actor.add_effect(other);
        }

        this._freeze(actor, effect);

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

    _forEachBackground(fn, actor = global.stage) {
        if (actor instanceof Meta.BackgroundActor)
            fn(actor);
        for (const child of actor.get_children())
            this._forEachBackground(fn, child);
    }

    // ---- pausing ------------------------------------------------------------

    _fullscreen(monitor) {
        return this._settings.get_boolean('pause-fullscreen') &&
            global.display.get_monitor_in_fullscreen(monitor);
    }

    _freeze(actor, effect) {
        effect.set_frozen(this._fullscreen(actor.monitor));
    }

    // One video for every monitor, so a game on one screen freezes only that
    // screen's copy; the decoder stops once no screen is left to show it on,
    // or the session is locked.
    _updatePaused() {
        if (!this._active)
            return;

        for (const actor of this._actors.keys()) {
            const effect = actor.get_effect(EFFECT_NAME);
            if (effect)
                this._freeze(actor, effect);
        }

        const monitors = Main.layoutManager.monitors;
        const covered = monitors.length > 0 &&
            monitors.every(m => this._fullscreen(m.index));

        this._player.set_playing(!covered && !Main.sessionMode.isLocked);
    }
}
