"""The plan as an indented list."""

from gi.repository import Gio, Gtk, Pango

from ..stream import DONE, FAILED
from .rows import describe, walk_plan
from .widgets import PlanNode, StateSlot


class Gutter(Gtk.DrawingArea):
    """The connector lines, drawn over the row the expander indented.

    Same information the box characters carried — which columns continue,
    where this row hangs off its parent — at the row's real height instead
    of a glyph's. Nothing here is a guess: the expander's own arrow is
    measured, so the elbow lands on it whatever the theme makes it.
    """

    indent = 20

    def __init__(self, expander):
        super().__init__(can_target=False)
        self.expander = expander
        self.node = None
        self.set_draw_func(self.draw)

    def show(self, node):
        self.node = node
        self.queue_draw()

    def metrics(self):
        """Indent per level and arrow centre, as the theme laid them out."""
        arrow = self.expander.get_first_child()
        if arrow is None:
            return self.indent, self.indent / 2
        # Measured against the gutter, which the overlay lays over the whole
        # row: inside the expander the arrow sits at zero whatever the depth.
        found, box = arrow.compute_bounds(self)
        if found and self.node.row["depth"] and box.origin.x > 0:
            Gutter.indent = box.origin.x / self.node.row["depth"]
        return Gutter.indent, box.size.width / 2

    def draw(self, _area, cr, _width, height):
        row = self.node.row if self.node else None
        if not row or not row["depth"]:
            return
        indent, centre = self.metrics()
        colour = self.get_color()
        cr.set_source_rgba(colour.red, colour.green, colour.blue, 0.3)
        cr.set_line_width(1.0)
        mid = round(height / 2) + 0.5

        def column(level):
            return round(level * indent + centre) + 0.5

        for level, pipe in enumerate(row["pipes"]):
            if pipe:
                cr.move_to(column(level), 0)
                cr.line_to(column(level), height)

        # The elbow: down the parent's column, then out. It stops at the
        # arrow when there is one and runs on to the icon when there is not,
        # so either way the line ends on something rather than in air.
        x = column(row["depth"] - 1)
        cr.move_to(x, 0)
        cr.line_to(x, mid if row["last"] else height)
        cr.move_to(x, mid)
        cr.line_to(row["depth"] * indent + (0 if row["kids"] else indent - 4),
                   mid)
        cr.stroke()


class PlanList(Gtk.Box):
    """The plan as the indented list it used to be, with the indent and the
    lines drawn rather than spelled out in box characters."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_select = None
        self.bound = {}
        self.nodes = {}
        self.shape = ()

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self.setup)
        factory.connect("bind", self.bind)
        factory.connect("unbind", self.unbind)
        self.view = Gtk.ListView(factory=factory, vexpand=True,
                                 css_classes=["plan-list"])
        frame = Gtk.Frame(child=Gtk.ScrolledWindow(child=self.view,
                                                   vexpand=True))
        frame.add_css_class("view")
        self.append(frame)

    # -- the model ------------------------------------------------------------
    def update(self, plan):
        shape = tuple(row["key"] for row in walk_plan(plan))
        if shape != self.shape:
            self.shape = shape
            self.load(plan)
        else:
            for row in walk_plan(plan):
                self.nodes[row["key"]].row = row
        for item, node in self.bound.items():
            self.paint(item, node)

    def load(self, plan):
        self.nodes = {}
        store = Gio.ListStore.new(PlanNode)
        for row in plan:
            store.append(self.wrap(row))
        self.view.set_model(Gtk.NoSelection.new(
            Gtk.TreeListModel.new(store, False, True, self.children_of)))

    def wrap(self, row):
        node = PlanNode(row)
        node.kids = [self.wrap(kid) for kid in row["kids"]]
        self.nodes[row["key"]] = node
        return node

    @staticmethod
    def children_of(node):
        if not node.kids:
            return None
        store = Gio.ListStore.new(PlanNode)
        for kid in node.kids:
            store.append(kid)
        return store

    # -- the rows -------------------------------------------------------------
    def setup(self, _factory, item):
        slot = StateSlot()
        title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                           css_classes=["caption", "dim-label"])
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                         valign=Gtk.Align.CENTER, hexpand=True)
        labels.append(title)
        labels.append(detail)
        bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=120)

        inner = Gtk.Box(spacing=10, css_classes=["plan-row"])
        inner.append(slot)
        inner.append(labels)
        inner.append(bar)
        expander = Gtk.TreeExpander(child=inner)

        # The lines go over the row, not beside it: the expander indents by
        # depth on its own, and drawing on top is what lets the elbow reach
        # into that indent instead of stopping at the edge of a column.
        gutter = Gutter(expander)
        overlay = Gtk.Overlay(child=expander)
        overlay.add_overlay(gutter)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a, it=item: self.choose(it))
        overlay.add_controller(click)

        item.set_child(overlay)
        item.widgets = (gutter, expander, slot, title, detail, bar)

    def bind(self, _factory, item):
        listrow = item.get_item()
        node = listrow.get_item()
        self.bound[item] = node
        gutter, expander, *_ = item.widgets
        expander.set_list_row(listrow)
        gutter.show(node)
        self.paint(item, node)

    def unbind(self, _factory, item):
        self.bound.pop(item, None)

    def choose(self, item):
        node = self.bound.get(item)
        if node is not None and self.on_select:
            self.on_select(node.row["key"])

    @staticmethod
    def paint(item, node):
        gutter, _expander, slot, title, detail, bar = item.widgets
        title.set_label(node.row["name"])
        detail.set_label(describe(node.row))
        slot.show(node.row)
        fraction = node.row.get("fraction")
        bar.set_visible(fraction is not None
                        and node.row["state"] not in (DONE, FAILED))
        bar.set_fraction(min(fraction or 0, 1.0))
        gutter.queue_draw()
