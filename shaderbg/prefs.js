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

    _todayGroup(settings, sources) {
        const group = new Adw.PreferencesGroup({ title: 'Running now' });
        const entry = this._current(settings, sources);

        const row = new Adw.ActionRow({
            title: entry ? entry.name : 'No shaders configured',
            subtitle: entry
                ? `${entry.author ?? 'unknown'} · speed ${entry.speed ?? 1}`
                : 'sources.nix is empty, falling back to drift.frag',
        });

        if (entry?.id) {
            const link = new Gtk.LinkButton({
                label: 'Shadertoy',
                uri: `https://www.shadertoy.com/view/${entry.id}`,
                valign: Gtk.Align.CENTER,
            });
            row.add_suffix(link);
        }

        group.add(row);
        return group;
    }

    _playbackGroup(settings) {
        const group = new Adw.PreferencesGroup({
            title: 'Playback',
            description: 'Speed multiplies the per-shader value from sources.nix.',
        });

        const speed = new Adw.SpinRow({
            title: 'Speed',
            subtitle: 'Scales the time base, so slowing down does not stutter',
            adjustment: new Gtk.Adjustment({
                lower: 0.05, upper: 2.0, step_increment: 0.05, page_increment: 0.25,
            }),
            digits: 2,
        });
        settings.bind('speed', speed, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(speed);

        const fps = new Adw.SpinRow({
            title: 'Frames per second',
            subtitle: 'The monitor runs at 144; a wallpaper has no reason to',
            adjustment: new Gtk.Adjustment({
                lower: 5, upper: 144, step_increment: 5, page_increment: 15,
            }),
        });
        settings.bind('fps-cap', fps, 'value', Gio.SettingsBindFlags.DEFAULT);
        group.add(fps);

        const pause = new Adw.SwitchRow({
            title: 'Pause on fullscreen',
            subtitle: 'Drops the timer while something covers the screen',
        });
        settings.bind('pause-fullscreen', pause, 'active', Gio.SettingsBindFlags.DEFAULT);
        group.add(pause);

        return group;
    }

    _pickGroup(settings, sources) {
        const group = new Adw.PreferencesGroup({
            title: `All shaders (${sources.length})`,
            description: 'Picking one keeps it until midnight, then the rotation resumes.',
        });

        // The -1 button doubles as the radio group's anchor, so "follow the
        // rotation" is a selectable state rather than a button that clears one.
        const rotate = new Gtk.CheckButton({ valign: Gtk.Align.CENTER });
        const rotateRow = new Adw.ActionRow({
            title: 'Follow the daily rotation',
            subtitle: 'One shader per day, in the order given by sources.nix',
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
                subtitle: entry.author ?? '',
                activatable_widget: check,
            });
            row.add_prefix(check);

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
