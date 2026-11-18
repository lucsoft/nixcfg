// Finding and reading Wallpaper Engine items. Shared by the extension, which
// only ever reads the one item chosen, and the preferences, which list them.
// Nothing here touches the Shell or GTK, so both sides can import it.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const APP_ID = '431960';

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (ok)
            return new TextDecoder().decode(bytes);
    } catch {
        // missing or unreadable, which the callers treat the same way
    }
    return null;
}

// Every Steam library on this machine. libraryfolders.vdf is Valve's KeyValues
// text format; the one thing wanted from it is each "path", and a regex is
// enough for that.
function steamLibraries() {
    const roots = [
        GLib.build_filenamev([GLib.get_user_data_dir(), 'Steam']),
        GLib.build_filenamev([GLib.get_home_dir(), '.steam', 'steam']),
    ];

    const libraries = new Set();
    for (const root of roots) {
        const vdf = readText(GLib.build_filenamev([root, 'steamapps', 'libraryfolders.vdf']));
        if (vdf === null)
            continue;

        libraries.add(root);
        for (const match of vdf.matchAll(/"path"\s+"([^"]+)"/g))
            libraries.add(match[1].replace(/\\\\/g, '\\'));
    }
    return [...libraries];
}

// Subscribed Workshop items, plus the projects Wallpaper Engine itself ships
// and the ones made in its editor, if the app is installed.
export function itemDirectories() {
    const parents = [];
    for (const library of steamLibraries()) {
        parents.push(GLib.build_filenamev([library, 'steamapps', 'workshop', 'content', APP_ID]));
        for (const kind of ['defaultprojects', 'myprojects'])
            parents.push(GLib.build_filenamev([library, 'steamapps', 'common', 'wallpaper_engine', 'projects', kind]));
    }

    const dirs = [];
    const seen = new Set();
    for (const parent of parents) {
        let children;
        try {
            children = Gio.File.new_for_path(parent).enumerate_children(
                'standard::name,standard::type', Gio.FileQueryInfoFlags.NONE, null);
        } catch {
            continue;
        }

        for (const info of children) {
            if (info.get_file_type() !== Gio.FileType.DIRECTORY)
                continue;
            const dir = GLib.build_filenamev([parent, info.get_name()]);
            const real = GLib.canonicalize_filename(dir, null);
            if (!seen.has(real)) {
                seen.add(real);
                dirs.push(dir);
            }
        }
    }
    return dirs;
}

// A file named by project.json, kept inside the item's own directory. The
// manifest comes from the Workshop, which is anyone's upload.
function inside(dir, name) {
    if (typeof name !== 'string' || name === '' ||
        GLib.path_is_absolute(name) || name.split(/[\\/]/).includes('..'))
        return null;

    const path = GLib.build_filenamev([dir, name]);
    return GLib.file_test(path, GLib.FileTest.IS_REGULAR) ? path : null;
}

const VIDEO = /\.(mp4|webm|mkv|mov|m4v|avi)$/i;

// What one item is. type is lower-cased because the manifests disagree on
// case ("Video", "video", "scene"); video is the file to play, and only set
// for a video item whose file is actually there.
export function readProject(dir) {
    const text = readText(GLib.build_filenamev([dir, 'project.json']));
    if (text === null)
        return null;

    let json;
    try {
        json = JSON.parse(text.replace(/^﻿/, ''));
    } catch {
        return null;
    }

    const type = String(json.type ?? 'unknown').toLowerCase();
    const file = inside(dir, json.file);

    return {
        dir,
        id: GLib.path_get_basename(dir),
        title: String(json.title ?? GLib.path_get_basename(dir)),
        type,
        preview: inside(dir, json.preview),
        video: type === 'video' && file && VIDEO.test(file) ? file : null,
    };
}
