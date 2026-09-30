"""The plan as a graph."""

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango

from ..stream import DONE, FAILED, RUNNING
from .rows import describe, walk_plan
from .widgets import Palette, PlanNode, StateSlot


class PlanGraph(Gtk.Widget):
    """Cards laid out by depth, edges drawn behind them.

    The list says what is waiting for what; this says it in one look, which
    is the thing a dependency tree is for. Cells are whatever the window
    leaves room for, down to a floor, so a plan fits instead of scrolling.
    """

    CARD_W, MIN_W, PAD, GAP_MIN, GAP_MAX = 210, 160, 12, 22, 72
    COLLAPSE = 320

    def __init__(self):
        super().__init__()
        self.on_select = None
        self.shape = ()
        self.cards = {}
        self.nodes = {}
        self.roots = []
        self.places = {}
        self.geometry_cache = ()
        self.fades = {}
        self.states = ()
        self.recentre = False
        self.columns = self.levels = 1

    # -- the model ------------------------------------------------------------
    def update(self, plan):
        shape = tuple(row["key"] for row in walk_plan(plan))
        if shape != self.shape:
            self.shape = shape
            self.load(plan)
        else:
            for row in walk_plan(plan):
                self.nodes[row["key"]].row = row
        self.refresh()

    def load(self, plan):
        for card in self.cards.values():
            card.unparent()
        self.cards, self.nodes, self.places, self.fades = {}, {}, {}, {}
        self.geometry_cache = ()
        self.roots = [self.wrap(row) for row in plan]
        self.recentre = True
        for node in self.nodes.values():
            card = self.card(node)
            card.set_parent(self)
            self.cards[node] = card
        self.layout()

    def wrap(self, row):
        node = PlanNode(row)
        self.nodes[row["key"]] = node
        node.kids = [self.wrap(kid) for kid in row["kids"]]
        return node

    def walk(self, node):
        yield node
        for kid in node.kids:
            yield from self.walk(kid)

    def card(self, node):
        """Name over three lines, state beside it, and a foot line for what
        the state cannot say on its own.

        Store paths are long and all the difference is in the middle, so a
        card that ellipsizes to one line says nothing; three fit most of
        them whole. The foot carries the phase while it builds and the
        count while it waits — and nothing at all once it is built.
        """
        slot = StateSlot()
        title = Gtk.Label(xalign=0, wrap=True, lines=3, hexpand=True,
                          wrap_mode=Pango.WrapMode.WORD_CHAR, max_width_chars=1,
                          ellipsize=Pango.EllipsizeMode.END,
                          valign=Gtk.Align.START)
        head = Gtk.Box(spacing=8, valign=Gtk.Align.START)
        head.append(slot)
        head.append(title)

        detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END,
                           css_classes=["caption", "dim-label"])
        # Only the run and its steps have a fraction — nix counts
        # derivations, not the inside of one — so only they get a bar. It
        # takes a fixed slice rather than expanding: the words beside it say
        # what it is counting, and they are the half worth reading.
        bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=64)
        foot = Gtk.Box(spacing=8, valign=Gtk.Align.END)
        foot.append(detail)
        foot.append(bar)
        # The revealer slides the foot out when there is nothing to put in
        # it, and the card measures shorter while it does, which is what
        # makes the row close up smoothly instead of snapping. The gap above
        # it is the foot's own margin rather than the box's spacing, because
        # spacing stays behind when the revealer folds.
        foot.set_margin_top(6)
        reveal = Gtk.Revealer(
            child=foot, reveal_child=True, transition_duration=self.COLLAPSE,
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                      css_classes=["card", "plan-card"])
        box.append(head)
        box.append(reveal)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a, n=node: self.choose(n))
        box.add_controller(click)
        box.parts = (slot, title, detail, bar, reveal)
        return box

    def choose(self, node):
        if self.on_select:
            self.on_select(node.row["key"])

    # -- layout ---------------------------------------------------------------
    def layout(self):
        """Leaves take the next free column, parents centre over their kids."""
        self.column = 0

        def place(node):
            if node.kids:
                xs = [place(kid) for kid in node.kids]
                x = (min(xs) + max(xs)) / 2
            else:
                x = self.column
                self.column += 1
            self.places[node] = x
            return x

        for root in self.roots:
            place(root)
        self.columns = max(self.column, 1)
        self.levels = max((node.row["depth"] for node in self.nodes.values()),
                          default=0) + 1

    def geometry(self):
        """Column step, card width, and where each level sits.

        Every level is as tall as the tallest card in it and no taller: a
        row of one-line names has no reason to take the room a row of
        wrapped store paths needs. What is left over becomes the gap between
        the levels, which is where the edges are drawn.
        """
        width = max(self.get_width(), 1) - 2 * self.PAD
        height = max(self.get_height(), 1) - 2 * self.PAD
        step_x = width / self.columns

        # No card is ever allocated less than it asked for: a card squeezed
        # below its minimum re-measures for the rest of the frame and the
        # widget never settles enough to draw.
        floor = max([self.MIN_W] + [card.measure(Gtk.Orientation.HORIZONTAL,
                                                 -1)[0]
                                    for card in self.cards.values()])
        card_w = max(floor, min(self.CARD_W, step_x - 8))

        tall, heights = {}, {}
        for node, card in self.cards.items():
            _min, natural, _b1, _b2 = card.measure(Gtk.Orientation.VERTICAL,
                                                   int(card_w))
            heights[node] = natural
            depth = node.row["depth"]
            tall[depth] = max(tall.get(depth, 0), natural)

        needed = sum(tall.values())
        gaps = max(self.levels - 1, 1)
        gap = min(self.GAP_MAX, max(self.GAP_MIN, (height - needed) / gaps))
        top = self.PAD + max(0, (height - needed - gap * gaps) / 2)

        rows, y = {}, top
        for depth in range(self.levels):
            rows[depth] = y
            y += tall.get(depth, 0) + gap
        return step_x, card_w, rows, heights

    def box_of(self, node):
        """Where a card sits, from the last allocation. Measuring children
        from inside a snapshot never settles, so before the first one there
        is nothing to draw and the next frame has it all."""
        if not self.geometry_cache:
            return None
        step_x, card_w, rows, heights = self.geometry_cache
        x = self.PAD + (self.places[node] + 0.5) * step_x - card_w / 2
        return x, rows[node.row["depth"]], card_w, heights[node]

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            floor = self.PAD * 2 + self.columns * (self.MIN_W + 8)
            want = self.PAD * 2 + self.columns * (self.CARD_W + 16)
            return (floor, want, -1, -1)
        else:
            floor = self.PAD * 2 + self.levels * (46 + self.GAP_MIN)
            want = self.PAD * 2 + self.levels * (96 + 36)
        return (floor, want, -1, -1)

    def centre(self):
        """Put the root in the middle of what can be seen.

        A plan wider than the window opens on its top left corner, which is
        a corner of a tree and reads as nothing. Done once per plan, so
        scrolling somewhere and staying there still works."""
        scroller = self.get_ancestor(Gtk.ScrolledWindow)
        box = self.box_of(self.roots[0]) if self.roots else None
        if scroller is None or box is None:
            return
        adjustment = scroller.get_hadjustment()
        page = adjustment.get_page_size()
        if not page:
            return
        self.recentre = False
        adjustment.set_value(max(0, min(box[0] + box[2] / 2 - page / 2,
                                        adjustment.get_upper() - page)))

    def do_size_allocate(self, _width, _height, _baseline):
        if not self.cards:
            return
        self.geometry_cache = self.geometry()
        for node, card in self.cards.items():
            x, y, w, h = self.box_of(node)
            rect = Gdk.Rectangle()
            rect.x, rect.y = int(x), int(y)
            rect.width, rect.height = int(w), int(h)
            card.size_allocate(rect, -1)
        if self.recentre:
            GLib.idle_add(self.centre)

    def do_dispose(self):
        # A plain GtkWidget subclass owns its children by hand; leaving them
        # parented at teardown takes the process with it.
        while child := self.get_first_child():
            child.unparent()
        Gtk.Widget.do_dispose(self)

    # -- the edges ------------------------------------------------------------
    def do_snapshot(self, snapshot):
        cr = snapshot.append_cairo(Graphene.Rect().init(
            0, 0, self.get_width(), self.get_height()))
        paint = Palette(self)
        cr.set_line_width(1.5)
        for node in self.cards:
            box = self.box_of(node)
            if box is None:
                break
            px, py, pw, ph = box
            for kid in node.kids:
                kx, ky, kw, _kh = self.box_of(kid)
                # An edge into something already built is spent; one feeding
                # what is building now is the path the build is on.
                state = kid.row["state"]
                if state == RUNNING:
                    cr.set_source_rgba(*paint.accent, .9)
                else:
                    cr.set_source_rgba(*paint.fg,
                                       .18 if state == DONE else .35)
                x0, y0 = px + pw / 2, py + ph
                x1, y1 = kx + kw / 2, ky
                slack = max((y1 - y0) / 2, 8)
                cr.move_to(x0, y0)
                cr.curve_to(x0, y0 + slack, x1, y1 - slack, x1, y1)
                cr.stroke()
        Gtk.Widget.do_snapshot(self, snapshot)

    # -- the cards ------------------------------------------------------------
    def refresh(self):
        for node, card in self.cards.items():
            slot, title, detail, bar, reveal = card.parts
            title.set_label(node.row["name"])
            detail.set_label(describe(node.row))
            slot.show(node.row)
            fraction = node.row.get("fraction")
            bar.set_visible(fraction is not None
                            and node.row["state"] not in (DONE, FAILED))
            bar.set_fraction(min(fraction or 0, 1.0))
            self.settle(node, detail, reveal)
            for state in (RUNNING, FAILED):
                card.remove_css_class(state)
            if node.row["state"] in (RUNNING, FAILED):
                card.add_css_class(node.row["state"])

        # Only a state change can move the layout, and the page redraws four
        # times a second: asking for a new one on every redraw leaves the
        # widget permanently mid-resize.
        shape = tuple(node.row["state"] for node in self.cards)
        if shape != self.states:
            self.states = shape
            self.queue_resize()
        self.queue_draw()

    def settle(self, node, detail, reveal):
        """Built is the end of the line: there is nothing left to say about
        a derivation that is done, so the status fades out and the foot
        slides shut under it, and the card gives back the height it was
        holding open for a word that will not change again."""
        wanted = node.row["state"] != DONE
        if wanted == reveal.get_reveal_child():
            return
        reveal.set_reveal_child(wanted)
        if wanted:
            self.fades.pop(node, None)
            detail.set_opacity(1)
            return
        target = Adw.CallbackAnimationTarget.new(detail.set_opacity)
        fade = Adw.TimedAnimation.new(detail, 1, 0, self.COLLAPSE - 60, target)
        fade.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self.fades[node] = fade
        fade.play()
