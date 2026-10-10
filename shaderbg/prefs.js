import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

function today() {
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.floor(midnight.getTime() / 86400000);
}

export default class ShaderBgPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const sources = this._loadSources();

        const page = new Adw.PreferencesPage();
        window.add(page);

        page.add(this._todayGroup(settings, sources));
        page.add(this._playbackGroup(settings));
        page.add(this._pickGroup(settings, sources));
    }

    _loadSources() {
        const path = GLib.build_filenamev([this.path, 'sources.json']);
        try {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (ok)
                return JSON.parse(new TextDecoder().decode(bytes));
        } catch (err) {
            console.error(`shaderbg: cannot read sources.json — ${err}`);
        }
        return [];
    }

    _current(settings, sources) {
        if (sources.length === 0)
            return null;

        const index = settings.get_int('override-index');
        if (index >= 0 && index < sources.length &&
            settings.get_int('override-day') === today())
            return sources[index];

        const day = today();
        return sources[((day % sources.length) + sources.length) % sources.length];
    }

    // Speed belongs to the shader, not to the extension: each one is tuned once
    // and remembered. sources.nix holds what a shader ships with, the `speeds`
    // key holds only the ones actually adjusted, so an untouched shader keeps
    // following the committed value and the reset button has something to go
    // back to.
    _todayGroup(settings, sources) {
        const group = new Adw.PreferencesGroup({ title: 'Running now' });

        const row = new Adw.ActionRow();
        const link = new Gtk.LinkButton({
            label: 'Shadertoy',
            valign: Gtk.Align.CENTER,
        });
        row.add_suffix(link);
        group.add(row);

        const speed = new Adw.SpinRow({
            title: 'Speed',
            adjustment: new Gtk.Adjustment({
                lower: 0.05, upper: 4.0, step_increment: 0.05, page_increment: 0.5,
            }),
            digits: 2,
        });

        const reset = new Gtk.Button({
            icon_name: 'edit-undo-symbolic',
            valign: Gtk.Align.CENTER,
            css_classes: ['flat'],
        });
        speed.add_suffix(reset);
        group.add(speed);

        let entry = null;
        let settingValue = false;

        const refresh = () => {
            entry = this._current(settings, sources);

            row.title = entry ? entry.name : 'No shaders configured';
            row.subtitle = entry
                ? `${entry.author ?? 'unknown'} · ${this._scaleLabel(settings, entry)}`
                : 'No shaders available';

            link.visible = !!entry?.id;
            if (entry?.id)
                link.uri = `https://www.shadertoy.com/view/${entry.id}`;

            speed.sensitive = !!entry;
            reset.tooltip_text = entry ? 'Back to its normal speed' : '';

            if (!entry)
                return;

            const tuned = settings.get_value('speeds').deepUnpack();
            const base = entry.speed ?? 1;
            const factor = tuned[entry.file] ?? 1;

            // The slider is a factor on the base, not a replacement for it,
            // so the number checked into sources.nix keeps meaning something
            // after the slider has been touched.
            speed.subtitle = factor === 1
                ? 'Running at its normal speed'
                : `${factor.toFixed(2)}× its normal speed`;

            // Guard the write-back: assigning to .value fires notify::value,
            // which would otherwise store 1.0 as if it had been set by hand.
            settingValue = true;
            speed.value = factor;
            settingValue = false;
        };

        speed.connect('notify::value', () => {
            if (settingValue || !entry)
                return;
            const next = settings.get_value('speeds').deepUnpack();
            next[entry.file] = speed.value;
            settings.set_value('speeds', new GLib.Variant('a{sd}', next));
        });

        reset.connect('clicked', () => {
            if (!entry)
                return;
            const next = settings.get_value('speeds').deepUnpack();
            delete next[entry.file];
            settings.set_value('speeds', new GLib.Variant('a{sd}', next));
            refresh();
        });

        // Picking another shader in the list below has to move this group with
        // it, or the slider would quietly keep editing the one that was running
        // when the window opened.
        const ids = [
            'changed::override-index',
            'changed::override-day',
            'changed::scales',
            'changed::auto-downscale',
        ].map(s => settings.connect(s, refresh));
        group.connect('destroy', () => ids.forEach(id => settings.disconnect(id)));

        refresh();
        return group;
    }

    // What resolution this shader ends up being drawn at. The extension keys
    // its measurements by shader *and* screen resolution, and this window has
    // no reliable way to know which screen the background is on — so a single
    // match is reported and several are not, which is honest and is also the
    // case that never comes up on one monitor.
    _scaleLabel(settings, entry) {
        const names = {
            1: 'full resolution',
            0.5: 'half resolution',
            0.25: 'quarter resolution',
        };

        if (typeof entry.scale === 'number')
            return `${names[entry.scale] ?? `${entry.scale}× resolution`}, set by hand`;

        if (!settings.get_boolean('auto-downscale'))
            return 'full resolution';

        const measured = settings.get_value('scales').deepUnpack();
        const hits = Object.keys(measured).filter(k => k.startsWith(`${entry.file}@`));
        if (hits.length !== 1)
            return 'not timed yet';

        return names[measured[hits[0]]] ?? `${measured[hits[0]]}× resolution`;
    }

    _playbackGroup(settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Playback',
        });

        const fps = new Adw.SpinRow({
            title: 'Frames per second',
            subtitle: 'Lower draws less and uses less power',
            adjustment: new Gtk.Adjustment({
                lower: 5, upper: 144, step_increment: 5, page_increment: 15,
            }),
        });
        settings.bind('fps-cap', fps, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(fps);

        const pause = new Adw.SwitchRow({
            title: 'Pause on fullscreen',
            subtitle: 'Stop animating when a fullscreen window covers the screen',
        });
        settings.bind('pause-fullscreen', pause, 'active', Gio.SettingsBindFlags.DEFAULT);
        group.add(pause);

        const downscale = new Adw.SwitchRow({
            title: 'Lower the resolution of demanding shaders',
            subtitle: 'Each shader is timed once; the heavy ones are drawn ' +
                'smaller and scaled up, which looks softer and costs much less',
        });

        // Each shader is only timed once, so there has to be a way to ask for
        // it again — after a driver update, or simply because the verdict
        // looks wrong.
        const forget = new Gtk.Button({
            icon_name: 'view-refresh-symbolic',
            tooltip_text: 'Time every shader again',
            valign: Gtk.Align.CENTER,
            css_classes: ['flat'],
        });
        forget.connect('clicked', () =>
            settings.set_value('scales', new GLib.Variant('a{sd}', {})));

        settings.bind('auto-downscale', downscale, 'active',
            Gio.SettingsBindFlags.DEFAULT);
        settings.bind('auto-downscale', forget, 'sensitive',
            Gio.SettingsBindFlags.GET);

        downscale.add_suffix(forget);
        group.add(downscale);

        // The number the timing is judged against. Not a frame rate: the cap
        // above says how often the background is drawn, this says how much of
        // each of those frames the card may spend drawing it.
        const budget = new Adw.SpinRow({
            title: 'Frame budget',
            subtitle: 'Percent of each frame a shader may take before it is ' +
                'drawn smaller; lower leaves the card idle more of the time',
            adjustment: new Gtk.Adjustment({
                lower: 5, upper: 100, step_increment: 5, page_increment: 10,
            }),
        });
        settings.bind('frame-budget', budget, 'value',
            Gio.SettingsBindFlags.DEFAULT);
        settings.bind('auto-downscale', budget, 'sensitive',
            Gio.SettingsBindFlags.GET);
        group.add(budget);

        // Off by default, and worth leaving off: a timed pass flushes Cogl's
        // journal twice so that the query brackets the draw and nothing else.
        const trace = new Adw.SwitchRow({
            title: 'Log frame timings',
            subtitle: 'Write a line a second to the journal with what each ' +
                'frame spent waiting, on the processor, on the card, and ' +
                'reaching the screen',
        });
        settings.bind('trace', trace, 'active', Gio.SettingsBindFlags.DEFAULT);
        group.add(trace);

        return group;
    }

    _pickGroup(settings, sources) {
        const group = new Adw.PreferencesGroup({
            title: `All shaders (${sources.length})`,
            description: 'Picking one keeps it until midnight, then the daily rotation resumes.',
        });

        // The -1 button doubles as the radio group's anchor, so "follow the
        // rotation" is a selectable state rather than a button that clears one.
        const rotate = new Gtk.CheckButton({ valign: Gtk.Align.CENTER });
        const rotateRow = new Adw.ActionRow({
            title: 'Follow the daily rotation',
            subtitle: 'One shader per day, in a fixed order',
            activatable_widget: rotate,
        });
        rotateRow.add_prefix(rotate);
        group.add(rotateRow);

        const active = settings.get_int('override-day') === today()
            ? settings.get_int('override-index')
            : -1;
        rotate.active = active < 0;

        rotate.connect('toggled', () => {
            if (rotate.active)
                settings.set_int('override-index', -1);
        });

        sources.forEach((entry, index) => {
            const check = new Gtk.CheckButton({
                group: rotate,
                valign: Gtk.Align.CENTER,
                active: index === active,
            });

            const row = new Adw.ActionRow({
                title: entry.name ?? entry.file,
                activatable_widget: check,
            });
            row.add_prefix(check);

            // Showing the speed here is what makes the set reviewable at a
            // glance: which ones have been tuned, and how far.
            const describe = () => {
                const tuned = settings.get_value('speeds').deepUnpack();
                const factor = tuned[entry.file] ?? 1;
                row.subtitle = factor === 1
                    ? `${entry.author ?? 'unknown'}`
                    : `${entry.author ?? 'unknown'} · ${factor.toFixed(2)}× speed`;
            };
            const speedsId = settings.connect('changed::speeds', describe);
            row.connect('destroy', () => settings.disconnect(speedsId));
            describe();

            check.connect('toggled', () => {
                if (!check.active)
                    return;
                // Day first: the extension reads both, and a stale day would
                // make the new index expire the moment it is written.
                settings.set_int('override-day', today());
                settings.set_int('override-index', index);
            });

            group.add(row);
        });

        return group;
    }
}
