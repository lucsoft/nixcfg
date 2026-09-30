"""The output of whatever is being watched."""

from gi.repository import Adw, GLib, Gtk, Pango

from .common import output_label
from .rows import describe


class LogPane(Gtk.Box):
    """What one derivation is saying, as it says it.

    The plan has room for a name and a state; a build talks the whole way
    through. Everything it says lands here instead, for whichever node is
    building — or whichever one was clicked.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.key = None
        self.lines = []

        self.title = Gtk.Label(xalign=0, css_classes=["heading"],
                               ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.detail = Gtk.Label(xalign=0, css_classes=["caption", "dim-label"],
                                ellipsize=Pango.EllipsizeMode.END)
        self.follow = Gtk.CheckButton(label="Follow the build", active=True)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                       margin_top=12, margin_bottom=12, margin_start=12,
                       margin_end=12)
        head.append(self.title)
        head.append(self.detail)
        head.append(self.follow)

        self.view = Gtk.TextView(
            editable=False, cursor_visible=False, monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=12, right_margin=12,
            top_margin=8, bottom_margin=8, css_classes=["plan-log"])
        self.buffer = self.view.get_buffer()
        self.scroll = Gtk.ScrolledWindow(child=self.view, vexpand=True,
                                         hscrollbar_policy=Gtk.PolicyType.NEVER)

        self.append(head)
        self.append(Gtk.Separator())
        self.append(self.scroll)
        self.show(None)

    def show(self, row):
        """Point the pane at a row — a node, a download, or nothing."""
        if row is None:
            self.key = None
            self.lines = []
            self.title.set_label("Nothing to read yet")
            self.detail.set_label("Pick a derivation to follow its output.")
            self.buffer.set_text("")
            return

        if row["key"] != self.key:
            self.key, self.lines = row["key"], []
            self.buffer.set_text("")
        self.title.set_label(row["name"])
        self.detail.set_label(describe(row) or "building")

        # The log is a tail: lines fall off the front as new ones arrive, so
        # what is on screen is replaced rather than appended to. Sixty lines
        # four times a second is nothing, and it keeps the two in step.
        if row["log"] == self.lines:
            return
        self.lines = list(row["log"])
        # A build that has not said anything yet, or a download, which never
        # will: an empty pane looks like something failed to arrive.
        self.buffer.set_text("\n".join(self.lines) or "No output yet")

        # Stay at the newest line, unless whoever is reading scrolled up.
        adjustment = self.scroll.get_vadjustment()
        if adjustment.get_value() + adjustment.get_page_size() >= \
                adjustment.get_upper() - 48:
            GLib.idle_add(lambda: adjustment.set_value(
                adjustment.get_upper() - adjustment.get_page_size()))



def problem_row(problem):
    """What nix called an error or a warning, with the output that explains
    it where there is any.

    nix writes these for a terminal: a headline naming a store path, then
    indented lines of reason under it. A row wants the other order — what
    broke in the title, why underneath — and the hash in neither.
    """
    lines = [line.strip() for line in problem["text"].splitlines() if line.strip()]
    headline = (lines[0].removeprefix("error:").removeprefix("warning:").strip()
                if lines else "")
    # "Reason: builder failed with exit code 3" is the sentence worth having;
    # the output paths beside it are not.
    reason = next((line.removeprefix("Reason:").strip()
                   for line in lines[1:] if line.startswith("Reason:")),
                  " ".join(lines[1:]))

    title = problem["name"] or headline
    subtitle = reason

    if problem["log"]:
        row = Adw.ExpanderRow(title=title, subtitle=subtitle)
        row.add_row(output_label("\n".join(problem["log"])))
    else:
        row = Adw.ActionRow(title=title, subtitle=subtitle, title_lines=0,
                            subtitle_lines=0)
    row.add_prefix(Gtk.Image(
        icon_name="dialog-error-symbolic" if problem["error"]
        else "dialog-warning-symbolic",
        css_classes=["error"] if problem["error"] else ["warning"]))
    return row
