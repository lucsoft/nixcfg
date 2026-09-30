"""The Gtk application.

Imported only on the path that opens a window; `npins-ui --check` never
reaches this module, and so never loads Gtk.
"""

from .paths import APP_ID
from .ui.common import CSS          # importing .ui is what pins the versions
from .ui.window import Window

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402


class Application(Adw.Application):
    def __init__(self, repo):
        # NON_UNIQUE because the repo is per-process state: with the default
        # single-instance behaviour a second launch just raises the first
        # window and drops its repo argument on the floor.
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.repo = repo

    def do_activate(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window = self.props.active_window or Window(self, self.repo)
        window.present()
