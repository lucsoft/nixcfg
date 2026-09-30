"""The vocabulary the pages share.

A boxed list, a heading, a monospace block, and the stylesheet for the few
things Adwaita has no class for.
"""

from gi.repository import Gio, Gtk, Pango

from ..paths import APP_ID
from ..stream import DONE, FAILED, PLANNED, RUNNING


# Said while a check the window did not start is running. A constant because
# the window also takes the line back down by recognising it.
CHECKING_ELSEWHERE = "Checking in the background…"


def boxed_list():
    box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    box.add_css_class("boxed-list")
    return box


def section(title):
    label = Gtk.Label(label=title, xalign=0)
    label.add_css_class("heading")
    label.set_margin_top(12)
    return label


def output_label(text):
    """Builder output, wherever it is shown. Monospace because it was
    written for a terminal and its columns still mean something."""
    return Gtk.Label(
        label=text, xalign=0, wrap=True, selectable=True,
        wrap_mode=Pango.WrapMode.WORD_CHAR,
        margin_top=8, margin_bottom=8, margin_start=12, margin_end=12,
        css_classes=["caption", "monospace", "dim-label"],
    )


def clock(seconds):
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


STATE_ICON = {
    PLANNED: "content-loading-symbolic",
    RUNNING: "system-run-symbolic",
    DONE: "object-select-symbolic",
    FAILED: "dialog-error-symbolic",
}


def load_settings():
    """The app's own settings, or None when the schema is not installed.

    The schema is installed by the package; running straight from a
    checkout has no schema at all, and Gio.Settings aborts the process
    rather than returning an error when it cannot find one — so the lookup
    happens here, and the window falls back to the default view.
    """
    source = Gio.SettingsSchemaSource.get_default()
    if source and source.lookup(APP_ID, True):
        return Gio.Settings.new(APP_ID)
    return None


# What Adwaita has no class for. Everything else on these pages is a stock
# widget with a stock style; this is the little that the drawn plan needs.
CSS = b"""
/* The row carries no padding of its own: the gutter has to reach the row
   above and below it, or the connector lines come out dashed. */
listview.plan-list > row { padding: 0; }
.plan-row { padding: 6px 12px 6px 0; }

.plan-card { padding: 8px 10px; border-radius: 12px; }
.plan-card label { font-size: .9em; }
/* An outline, not a border: a border takes room, and a card that grows by
   two pixels when it starts building shoves every card beside it. */
.plan-card.running, .plan-card.failed {
    outline-style: solid; outline-width: 2px; outline-offset: -2px;
}
.plan-card.running { outline-color: alpha(@accent_color, .6); }
.plan-card.failed  { outline-color: alpha(@error_color, .6); }

.plan-log { font-family: monospace; font-size: .85em; }
"""
