import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

import { itemDirectories, readProject } from './workshop.js';

export default class WpeBgPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();

        const page = new Adw.PreferencesPage();
        window.add(page);

        const playback = new Adw.PreferencesGroup({ title: 'Playback' });
        const pause = new Adw.SwitchRow({
            title: 'Pause while a window is fullscreen',
            subtitle: 'Per screen; the video stops decoding once every screen is covered',
        });
        settings.bind('pause-fullscreen', pause, 'active', Gio.SettingsBindFlags.DEFAULT);
        playback.add(pause);
        page.add(playback);

        page.add(this._itemsGroup(settings));
    }

    _itemsGroup(settings) {
        const projects = itemDirectories()
            .map(readProject)
            .filter(p => p !== null)
            .sort((a, b) => Number(b.video !== null) - Number(a.video !== null) ||
                a.title.localeCompare(b.title));

        const group = new Adw.PreferencesGroup({
            title: 'Wallpaper',
            description: projects.length === 0
                ? 'No Wallpaper Engine items found. Subscribe to some in the ' +
                  'Steam Workshop and let Steam download them, then reopen this window.'
                : 'Downloaded Wallpaper Engine items. Only video wallpapers can be ' +
                  'shown so far; scene and web ones are listed but greyed out.',
        });

        const chosen = settings.get_string('item');

        const off = new Adw.ActionRow({
            title: 'None',
            subtitle: 'The ordinary background',
        });
        const offCheck = new Gtk.CheckButton({ active: chosen === '', valign: Gtk.Align.CENTER });
        off.add_prefix(offCheck);
        off.activatable_widget = offCheck;
        offCheck.connect('toggled', () => {
            if (offCheck.active)
                settings.set_string('item', '');
        });
        group.add(off);

        for (const project of projects) {
            const row = new Adw.ActionRow({
                title: GLib.markup_escape_text(project.title, -1),
                subtitle: project.video ? `video · ${project.id}` : `${project.type} · not supported yet`,
                sensitive: project.video !== null,
            });

            const check = new Gtk.CheckButton({
                group: offCheck,
                active: chosen === project.dir,
                valign: Gtk.Align.CENTER,
            });
            row.add_prefix(check);
            row.activatable_widget = check;
            check.connect('toggled', () => {
                if (check.active)
                    settings.set_string('item', project.dir);
            });

            // A GIF preview shows its first frame, which is all a list needs.
            if (project.preview) {
                const picture = Gtk.Picture.new_for_filename(project.preview);
                picture.set_content_fit(Gtk.ContentFit.COVER);
                picture.set_size_request(96, 54);
                picture.set_valign(Gtk.Align.CENTER);
                picture.add_css_class('card');
                row.add_suffix(picture);
            }

            group.add(row);
        }

        return group;
    }
}
