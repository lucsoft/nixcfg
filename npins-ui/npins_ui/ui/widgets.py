"""The small drawn parts both plan views use.

A colour pair off the theme, a progress ring, the icon-or-ring slot that
swaps between them, and the list-model object a row hangs on.
"""

import cairo
import math

from gi.repository import Adw, GObject, Gtk

from ..stream import DONE, FAILED, PLANNED, RUNNING
from .common import STATE_ICON


class Palette:
    """The two colours the drawn parts of the plan use, from the theme."""

    def __init__(self, widget):
        colour = widget.get_color()
        self.fg = (colour.red, colour.green, colour.blue)
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()
        self.accent = (accent.red, accent.green, accent.blue)


class Ring(Gtk.DrawingArea):
    """A spinner that knows how far along it is.

    Neither GTK nor libadwaita has one: Adw.Spinner only ever says "still
    going" and both progress widgets are bars. Only downloads get it —
    those are the ones nix reports a size for. A build reports the phase it
    is in and nothing else, so a percentage on a build would be a number
    the build never gave.
    """

    SIZE = 16

    def __init__(self):
        super().__init__(content_width=self.SIZE, content_height=self.SIZE,
                         valign=Gtk.Align.CENTER)
        self.fraction = 0.0
        self.set_draw_func(self.draw)

    def set_fraction(self, fraction):
        if abs(fraction - self.fraction) < 0.01:
            return
        self.fraction = fraction
        self.queue_draw()

    def draw(self, _area, cr, width, height):
        paint = Palette(self)
        radius = min(width, height) / 2 - 1.5
        cr.set_line_width(2.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.arc(width / 2, height / 2, radius, 0, 2 * math.pi)
        cr.set_source_rgba(*paint.fg, .18)
        cr.stroke()
        start = -math.pi / 2
        cr.arc(width / 2, height / 2, radius, start,
               start + 2 * math.pi * self.fraction)
        cr.set_source_rgba(*paint.accent, 1)
        cr.stroke()


class StateSlot(Gtk.Stack):
    """What a node is doing, in sixteen pixels: a spinner while it runs, a
    ring when there is a size to fill, the state's icon otherwise.

    A stack rather than a swap, because a build that finishes replaces one
    with the other and an instant replacement reads as a flicker. All three
    are built once and kept: rebuilding a spinner four times a second
    restarts its animation four times a second.
    """

    def __init__(self):
        super().__init__(valign=Gtk.Align.CENTER, hhomogeneous=True,
                         vhomogeneous=True, transition_duration=250,
                         transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.spinner = Adw.Spinner(width_request=16, height_request=16)
        self.ring = Ring()
        self.icon = Gtk.Image()
        self.add_named(self.spinner, "spinner")
        self.add_named(self.ring, "ring")
        self.add_named(self.icon, "icon")

    def show(self, row):
        state = row.get("state")
        if state in (None, RUNNING):
            # A download says how far along it is; a build only says that it
            # is going, so that is all the spinner claims.
            if row.get("expected"):
                self.ring.set_fraction(row["done"] / row["expected"])
                self.set_visible_child_name("ring")
            else:
                self.set_visible_child_name("spinner")
            return
        self.set_visible_child_name("icon")
        self.icon.set_from_icon_name(STATE_ICON[state])
        for name in ("dim-label", "success", "error"):
            self.icon.remove_css_class(name)
        self.icon.add_css_class({PLANNED: "dim-label", DONE: "success",
                                 FAILED: "error"}[state])


class PlanNode(GObject.Object):
    """One derivation, as the list model holds it. The dict behind it is
    replaced on every redraw; the object stays, so the rows do too."""

    def __init__(self, row):
        super().__init__()
        self.row = row
        self.kids = []
