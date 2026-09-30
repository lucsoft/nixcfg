"""The window."""

import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from gi.repository import Adw, Gio, GLib, GObject, Gtk

from ..paths import CACHE, CATEGORIES, LOCKFILE
from ..errors import describe_error
from ..npins import pin_url, pin_version, read_pins, write_lockfile
from ..forge import changelog_for
from ..effect import (NOTHING, REBOOT, REBUILD, SESSION, TIER_ACTION,
                      TIER_ICON, TIER_PENDING, boot_paths, change_tier,
                      end_session, mark_session_stale, pending_tier,
                      reboot_needed)
from ..evaluate import closure_delta, closure_stats, profiles
from ..check import (APPLIED, CHECK_LOCK, FRESH_FOR, STATE, ago, applied_ago,
                     check_running, load_apply, load_check, save_apply,
                     save_check, survey)
from ..stream import (DEFAULT_PLAN_VIEW, FAILED, RUNNING, STEP_LINES,
                      RebuildStream, rebuild_steps)
from ..git import commit_lockfile
from .common import CHECKING_ELSEWHERE, boxed_list, load_settings, section
from .rows import compose, walk_plan
from .planlist import PlanList
from .plangraph import PlanGraph
from .logpane import LogPane, problem_row


class Window(Adw.ApplicationWindow):
    def __init__(self, app, repo):
        super().__init__(application=app, title="npins",
                         default_width=820, default_height=680)
        self.repo = Path(repo)
        self.lockfile = self.repo / LOCKFILE
        # Held as the object, not just its path: its finalizer takes the
        # directory away at interpreter exit too, so quitting by any route
        # other than closing the window does not leave one behind. Closing
        # the window is the prompt case and cleans up there; 123 of these
        # had collected in /tmp before anything did.
        self._workdir = tempfile.TemporaryDirectory(prefix="npins-ui-")
        self.workdir = Path(self._workdir.name)
        self.pending_text = None
        self.updates = []
        self.detail = {}
        # When the check on screen was made, so a state file written while
        # the window is open can be told from the one it already shows.
        self.state_stamp = 0
        self.working = False
        self._banner_timer = 0
        self.proc = None
        # Whether a rebuild is in flight, as its own answer rather than as
        # `proc is not None`. The process only exists once Popen has
        # returned, and everything that asks — the check button, the state
        # watch, Apply, Last Apply — asks earlier than that.
        self.rebuilding = False
        self.cancelled = False
        self.steps = []
        self.step_index = 0
        self.stream = None
        self.ticker = 0
        # Problems outlive the process that reported them: both rebuild steps
        # report into one list, and a failed step leaves it on screen.
        self.carried = []
        self.closure_before = None
        # Whether the update being applied touches the session. Recorded at
        # apply time because after the rebuild there is nothing left to read
        # it off; see session_marker.
        self.applied_session = False

        self.check_button = Gtk.Button(icon_name="view-refresh-symbolic",
                                       tooltip_text="Check for Updates")
        self.check_button.connect("clicked", lambda _b: self.check())

        view_menu = Gio.Menu()
        view_menu.append("Graph", "win.plan-view::graph")
        view_menu.append("List", "win.plan-view::list")

        menu = Gio.Menu()
        menu.append_section("Rebuild View", view_menu)
        menu.append("Last Apply", "win.last-apply")
        menu.append("Sources", "win.sources")
        menu.append("About npins", "win.about")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                     menu_model=menu, tooltip_text="Main Menu")

        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="npins", subtitle=str(self.repo))
        )
        header.pack_start(self.check_button)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                               margin_top=12, margin_bottom=12,
                               margin_start=12, margin_end=12)
        scroller = Gtk.ScrolledWindow(
            child=Adw.Clamp(child=self.content, maximum_size=700),
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
        )

        self.status = Adw.StatusPage(
            icon_name="software-update-available-symbolic",
            title="Pins",
            description="Check whether nixpkgs or Home Manager have moved.",
        )
        # The status page is the only place this belongs: it is where the
        # window says something is still owed, and it is never on screen at
        # the same time as a list of updates that ought to be applied first.
        self.finish_tier = NOTHING
        self.finish_button = Gtk.Button(halign=Gtk.Align.CENTER, visible=False,
                                        css_classes=["suggested-action", "pill"])
        self.finish_button.connect("clicked", lambda _b: self.finish())
        self.status.set_child(self.finish_button)
        # The rebuild page is the plan and nothing else. How far along the
        # run is used to be a bar above it; it is the root node now, with a
        # node per step under it, because a rebuild counting its own steps
        # is part of the tree rather than chrome around it.
        self.graph = PlanGraph()
        self.list = PlanList()
        self.graph.on_select = self.watch
        self.list.on_select = self.watch
        # The graph asks for the width its cards want; a rebuild with fifty
        # downloads in it would otherwise drag the window that wide. Inside
        # a scroller it fits when it can and scrolls when it cannot, and the
        # window keeps a size a window can have.
        self.plan_views = Gtk.Stack(vexpand=True)
        self.plan_views.add_named(
            Gtk.ScrolledWindow(child=self.graph, vexpand=True), "graph")
        self.plan_views.add_named(self.list, "list")
        self.pane = LogPane()
        self.watching = None
        self.seen = {}
        # What the page is showing when it is not showing a live rebuild:
        # the record of the last one, and which of its steps is on screen.
        self.replay = None
        self.record = []
        self.rebuild_started = self.step_started = 0

        self.problems = boxed_list()
        self.problems_heading = section("Problems")
        self.problem_count = 0

        # nix says things no row was written for — obsolete channels, a
        # substituter that went away mid-fetch. Keeping its own output one
        # click away costs a collapsed row and means nothing is lost.
        self.logview = Gtk.TextView(
            editable=False, cursor_visible=False, monospace=True,
            left_margin=12, right_margin=12, top_margin=8, bottom_margin=8,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        self.logbuf = self.logview.get_buffer()
        self.logscroll = Gtk.ScrolledWindow(child=self.logview, vexpand=True,
                                            min_content_height=260)
        self.logrow = Adw.ExpanderRow(title="Full nix output")
        self.logrow.add_prefix(Gtk.Image(icon_name="utilities-terminal-symbolic"))
        self.logrow.add_row(self.logscroll)
        log_group = boxed_list()
        log_group.append(self.logrow)

        self.rebuild_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=12, margin_top=12, margin_bottom=12,
                                    margin_start=12, margin_end=12)
        self.rebuild_body.append(self.problems_heading)
        self.rebuild_body.append(self.problems)
        self.rebuild_body.append(section("Details"))
        self.rebuild_body.append(log_group)
        # The plan takes the room and the rest takes what it needs: a
        # scroller that stops growing at a third of the window, so a long
        # list of downloads cannot push the plan off the page.
        extras = Gtk.ScrolledWindow(
            child=self.rebuild_body, hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True, max_content_height=260,
        )
        plan_side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        plan_side.append(self.plan_views)
        plan_side.append(extras)

        # Collapsed: the output is a drawer over the plan rather than a
        # third of the window standing empty until something is clicked.
        # Clicking a node opens it; the button in the header keeps it open.
        self.split = Adw.OverlaySplitView(
            content=plan_side, sidebar=self.pane, collapsed=True,
            show_sidebar=False, sidebar_position=Gtk.PackType.END,
            sidebar_width_fraction=0.34, min_sidebar_width=280,
            max_sidebar_width=400,
        )
        rebuild_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rebuild_page.append(self.split)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.status, "status")
        self.stack.add_named(scroller, "list")
        self.stack.add_named(rebuild_page, "rebuild")

        # A Gtk.ActionBar, not a second HeaderBar: this row carries actions,
        # not window controls or a title.
        apply_menu = Gio.Menu()
        apply_menu.append("Apply Without Committing", "win.apply-only")
        apply_menu.append("Write Pins Only", "win.write-only")
        self.apply_button = Adw.SplitButton(
            label="Apply", menu_model=apply_menu, visible=False
        )
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect(
            "clicked", lambda _b: self.apply(commit=True, rebuild=True))

        self.cancel_button = Gtk.Button(label="Cancel", visible=False)
        self.cancel_button.connect("clicked", lambda _b: self.cancel_rebuild())

        # The way off a failed rebuild's page. It has no Cancel left to press
        # and nothing has moved on, so leaving is a decision the user makes
        # once they have read what is on it.
        self.back_button = Gtk.Button(label="Back", visible=False)
        self.back_button.connect("clicked", lambda _b: self.leave_rebuild())

        # The output drawer, pinned open. Clicking a derivation opens it
        # anyway; this is for keeping it there while the build moves on.
        self.output_button = Gtk.ToggleButton(
            icon_name="sidebar-show-right-symbolic", visible=False,
            tooltip_text="Build Output")
        self.output_button.bind_property(
            "active", self.split, "show-sidebar",
            GObject.BindingFlags.BIDIRECTIONAL)

        # A persistent one-line verdict belongs in a banner, not in a toast
        # that vanishes.
        self.banner = Adw.Banner(revealed=False)

        self.spinner = Adw.Spinner(visible=False)

        # The primary action sits in the header, the way GNOME Software puts
        # "Update All" there. pack_end stacks right to left, so the menu keeps
        # the corner it conventionally owns.
        header.pack_end(menu_button)
        header.pack_end(self.apply_button)
        header.pack_end(self.cancel_button)
        header.pack_end(self.back_button)
        header.pack_end(self.output_button)
        header.pack_end(self.spinner)

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)

        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        for name, handler in (
            ("apply-only", lambda *_: self.apply(commit=False, rebuild=True)),
            ("write-only", lambda *_: self.apply(commit=True, rebuild=False)),
            ("last-apply", lambda *_: self.open_apply()),
            ("sources", lambda *_: self.sources()),
            ("about", lambda *_: self.about()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        # Which view the rebuild draws its plan in. GSettings owns the
        # choice when its schema is installed and hands out an action bound
        # to it; from a checkout there is no schema, so the action carries
        # the state itself and the choice lasts as long as the window.
        self.settings = load_settings()
        if self.settings:
            view_action = self.settings.create_action("plan-view")
            self.settings.connect("changed::plan-view",
                                  lambda *_: self.show_plan_view())
        else:
            view_action = Gio.SimpleAction.new_stateful(
                "plan-view", GLib.VariantType.new("s"),
                GLib.Variant("s", DEFAULT_PLAN_VIEW))
            view_action.connect("change-state", lambda action, value: (
                action.set_state(value), self.show_plan_view()))
        self.add_action(view_action)
        self.show_plan_view()

        # Open on what the timer already found rather than on nothing. It ran
        # the same check this window would, so repeating it on every launch
        # was two fetches for one answer.
        restored = load_check(self.repo, self.lockfile)
        if restored:
            age = self.adopt(restored)

        self.render()
        self.sync_apply()
        self.sync_apply_history()

        if not restored or age > FRESH_FOR:
            # Nothing kept, or kept longer than the timer promises to keep it
            # current. Either way the answer on screen is not one to stand on.
            self.check()
        elif self.updates:
            self.say(f"{self.verdict()} · checked {ago(age)}")
        else:
            self.show_current(age)

        self.watch_state()
        self.connect("close-request", self.closing)

    def closing(self, *_args):
        """Closing the window ends the process, and the rebuild with it.

        nix is written to with --log-format internal-json the whole way
        through, so losing the read end of its pipe kills it — possibly
        inside switch-to-configuration, between one service restart and the
        next. That is not something a window close should be able to do, so
        it is refused while a rebuild is in flight; Cancel is the way out,
        and it stops at the end of the step for the same reason.
        """
        if self.rebuilding:
            self.say("The rebuild is still running. Cancel it first.",
                     seconds=0)
            return True     # GDK_EVENT_STOP — the window stays
        self._workdir.cleanup()
        return False

    # -- helpers --------------------------------------------------------------
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def offer(self, tier):
        """Put what is owed on the status page as something to press."""
        self.finish_tier = tier
        self.finish_button.set_visible(tier != NOTHING)
        # A check landing mid-rebuild puts this page back up with Rebuild on
        # it, and pressing it would start a second nixos-rebuild over the
        # first. Greyed rather than hidden: it is still what is owed.
        self.finish_button.set_sensitive(not self.working and not self.rebuilding)
        if tier == REBOOT:
            self.finish_button.set_label("Restart")
        elif tier == SESSION:
            self.finish_button.set_label("Log Out")
        elif tier == REBUILD:
            self.finish_button.set_label("Rebuild")

    def finish(self):
        if self.finish_tier == REBUILD:
            # The pins are written already, so this is the rebuild half of
            # apply on its own. What the interrupted run knew about the
            # session it could not keep is gone if the window was reopened.
            self.start_rebuild()
            return
        # gnome-session takes it from here, confirmation dialog and all, so
        # there is nothing to do but hand it over and report a refusal.
        try:
            end_session(self.finish_tier)
        except GLib.Error as error:
            self.fail(error)

    def fail(self, error):
        """Errors carry a command's stderr, which a toast would truncate."""
        dialog = Adw.AlertDialog(heading="Something went wrong",
                                 body=describe_error(error))
        dialog.add_response("close", "Close")
        dialog.present(self)

    def say(self, text, seconds=8):
        """Put a verdict in the banner and let it fade out again.

        seconds=0 keeps it up — that is for progress, which should not
        disappear while the work is still running.
        """
        if self._banner_timer:
            GLib.source_remove(self._banner_timer)
            self._banner_timer = 0
        self.banner.set_title(text)
        self.banner.set_revealed(bool(text))
        if text and seconds:
            self._banner_timer = GLib.timeout_add_seconds(seconds, self._hide_banner)

    def _hide_banner(self):
        self.banner.set_revealed(False)
        self._banner_timer = 0
        return GLib.SOURCE_REMOVE

    def busy(self, active, message=None):
        self.working = active
        self.spinner.set_visible(active)
        self.sync_check()
        self.sync_apply(busy=active)
        self.offer(self.finish_tier)
        if message:
            self.say(message, seconds=0)

    def open_url(self, url):
        Gtk.UriLauncher(uri=url).launch(self, None, None, None)

    def sync_apply(self, busy=False):
        """There is nothing to apply until a check finds something, so the
        button is absent rather than present-and-greyed.

        Not while a rebuild is running either: applying writes the lock file
        that the running nixos-rebuild is reading.
        """
        ready = bool(self.pending_text) and not self.rebuilding
        self.apply_button.set_visible(ready)
        self.apply_button.set_sensitive(ready and not busy)

    def run_async(self, work, done):
        def worker():
            try:
                result = work()
            except Exception as error:  # handed to `done`, shown in a dialog
                result = error
            GLib.idle_add(done, result)

        threading.Thread(target=worker, daemon=True).start()

    # -- rendering ------------------------------------------------------------
    def render(self):
        """The window shows changed packages and nothing else.

        Which revision nixpkgs sits on is configuration, so it lives in the
        Sources dialog; what belongs here is the answer to "what changes for
        me". With nothing to report there is no list at all, only a status
        page.
        """
        while child := self.content.get_first_child():
            self.content.remove(child)
        # Whatever brought the window back to the pins — Back, or a check
        # started from the header — the failed rebuild's page is behind it
        # now, and its one button does not belong on this one.
        self.back_button.set_visible(False)

        try:
            read_pins(self.lockfile)
        except (OSError, ValueError, KeyError) as error:
            self.offer(NOTHING)
            self.status.set_title("Cannot read the pins")
            self.status.set_description(str(error))
            self.stack.set_visible_child_name("status")
            return

        # What is owed takes no check, no network and no evaluation — four
        # symlinks and two version strings — so it is the one thing the
        # window can answer the moment it opens.
        pending = pending_tier(self.lockfile)
        self.offer(pending)
        if pending:
            self.status.set_icon_name(TIER_ICON[pending])
            self.status.set_title(TIER_ACTION[pending])
            self.status.set_description(TIER_PENDING[pending])

        changes = self.detail.get("changes")
        if changes is not None:
            self.render_changes(changes)
        elif self.detail.get("changes_error"):
            group = boxed_list()
            group.append(Adw.ActionRow(
                title="Cannot tell what this changes for you",
                subtitle=self.detail["changes_error"].splitlines()[-1][:120],
            ))
            self.content.append(group)

        if self.content.get_first_child() is None:
            self.stack.set_visible_child_name("status")
        else:
            self.stack.set_visible_child_name("list")

    def render_changes(self, changes):
        subjects = self.detail.get("subjects", [])
        total = sum(len(changes.get(key, [])) for key, _ in CATEGORIES)

        # A kernel rebuilt at an unchanged version moves no version number,
        # so the categories can all be empty while a reboot is still owed.
        # That is the whole reason the reboot half is measured, and bailing
        # out on the count alone would throw the measurement away.
        if not total and not changes.get("reboot_added"):
            # No lock file on purpose: an update is pending here, and an
            # owed rebuild would offer to build the very pins this page is
            # asking to replace.
            pending = pending_tier()
            self.offer(pending)
            self.status.set_icon_name(TIER_ICON[pending])
            self.status.set_title("Nothing you installed changes")
            description = "The pins moved, but not through any of your packages."
            if pending:
                description += f"\n\n{TIER_ACTION[pending]} an earlier rebuild."
            self.status.set_description(description)
            return

        # What this costs to install, before agreeing to install it. nix
        # gets this from the substituters without fetching anything, so it
        # is a real number rather than an extrapolation from the diff below.
        download = self.detail.get("download")
        if download:
            group = boxed_list()
            row = Adw.ActionRow(
                title=f"{download['download']} to download",
                subtitle=f"{download['unpacked']} once unpacked")
            row.add_prefix(Gtk.Image(icon_name="folder-download-symbolic"))
            group.append(row)
            self.content.append(group)

        # One row at the top for the only part that is not automatic. It
        # names the components as well, because a kernel rebuilt at an
        # unchanged version leaves the section below empty and the verdict
        # would otherwise look like it came from nowhere.
        tier = change_tier(changes)
        if tier:
            named = (changes.get("reboot") if tier == REBOOT
                     else [e["name"] for e in changes.get("graphics", [])])
            row = Adw.ActionRow(title=TIER_ACTION[tier],
                                subtitle=", ".join(named))
            row.add_prefix(Gtk.Image(icon_name=TIER_ICON[tier]))
            group = boxed_list()
            group.append(row)
            self.content.append(group)

        for key, label in CATEGORIES:
            entries = changes.get(key, [])
            if not entries:
                continue
            if key == "dependencies":
                self.render_dependencies(entries, label)
                continue
            group = boxed_list()
            for entry in entries:
                # An entry the version diff could not speak for has no pair
                # to show — a package carrying no version, or one patched
                # without a bump. The commits are the evidence there, so say
                # that in the subtitle rather than showing "→".
                log = entry.get("subjects") or changelog_for(entry["name"], subjects)
                if entry.get("old"):
                    subtitle = f"{entry['old']}  →  {entry['new']}"
                elif entry.get("installed"):
                    subtitle = f"{entry['installed']} installed · patched"
                else:
                    count = len(log)
                    subtitle = f"{count} commit{'' if count == 1 else 's'}"
                row = Adw.ExpanderRow(title=entry["name"], subtitle=subtitle)
                for subject in log:
                    action = Adw.ActionRow(title=subject, title_lines=0,
                                           css_classes=["caption"])
                    if "cve-" in subject.lower():
                        badge = Gtk.Label(label="CVE")
                        badge.add_css_class("error")
                        badge.add_css_class("caption-heading")
                        action.add_suffix(badge)
                    row.add_row(action)
                if not log:
                    row.add_row(Adw.ActionRow(title="No matching commit subjects",
                                              css_classes=["caption", "dim-label"]))
                group.append(row)
            self.content.append(section(label))
            self.content.append(group)

    def render_dependencies(self, entries, label):
        """Dependencies get one row that opens a dialog.

        It is the longest list and the least often opened — nobody asked for
        these packages, they came along. A count is enough to decide whether
        to look, and a CVE is the one thing that has to be visible without
        opening anything at all.
        """
        cves = [e for e in entries
                if any("cve-" in s.lower() for s in e.get("subjects", []))]
        summary = f"{len(entries)} package{'' if len(entries) == 1 else 's'}"
        if cves:
            summary += f" · {len(cves)} with a CVE fix"

        row = Adw.ActionRow(title=label, subtitle=summary, activatable=True)
        if cves:
            badge = Gtk.Label(label="CVE", valign=Gtk.Align.CENTER)
            badge.add_css_class("error")
            badge.add_css_class("caption-heading")
            row.add_suffix(badge)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda _r: self.show_dependencies(entries, label))

        # No section heading: the row carries the label itself.
        group = boxed_list()
        group.append(row)
        self.content.append(group)

    def show_dependencies(self, entries, label):
        group = Adw.PreferencesGroup(
            title=label,
            description="Packages your config never names. They are in the "
                        "closure because something you did ask for needs "
                        "them, so a change here reaches you all the same.",
        )
        for entry in entries:
            log = entry.get("subjects", [])
            if entry.get("old"):
                head = f"{entry['old']}  →  {entry['new']}"
            elif entry.get("installed"):
                head = f"{entry['installed']} installed · patched"
            else:
                head = f"{len(log)} commit{'' if len(log) == 1 else 's'}"

            # Expanders are fine in here. In the main window they would have
            # been a second level under the Dependencies row; here the list
            # is the top level, so each package can keep its commits folded
            # and the dialog opens as a readable index rather than a wall.
            item = Adw.ExpanderRow(title=entry["name"], subtitle=head)
            if any("cve-" in s.lower() for s in log):
                mark = Gtk.Label(label="CVE", valign=Gtk.Align.CENTER)
                mark.add_css_class("error")
                mark.add_css_class("caption-heading")
                item.add_suffix(mark)
            for subject in log:
                line = Adw.ActionRow(title=subject, title_lines=0,
                                     css_classes=["caption"])
                if "cve-" in subject.lower():
                    flag = Gtk.Label(label="CVE", valign=Gtk.Align.CENTER)
                    flag.add_css_class("error")
                    flag.add_css_class("caption-heading")
                    line.add_suffix(flag)
                item.add_row(line)
            group.add(item)

        page = Adw.PreferencesPage()
        page.add(group)
        dialog = Adw.PreferencesDialog(title=label)
        dialog.add(page)
        dialog.present(self)

    def sources(self):
        """The pins live here, not in the main window: which revision
        nixpkgs sits on is configuration, not something to read every day."""
        try:
            pins = read_pins(self.lockfile)
        except (OSError, ValueError, KeyError) as error:
            self.fail(error)
            return

        moved = {u["name"]: u for u in self.updates}
        group = Adw.PreferencesGroup(
            title="Pins", description=str(self.lockfile)
        )
        for name in sorted(pins):
            row = Adw.ActionRow(title=name, subtitle=pin_version(pins[name]))
            update = moved.get(name)
            if update:
                info = self.detail.get(name, {})
                parts = [f"→ {update['new']}"]
                if info.get("behind"):
                    parts.append(f"{info['behind']} commits")
                if info.get("age"):
                    parts.append(info["age"])
                label = Gtk.Label(label="  ·  ".join(parts))
                label.add_css_class("accent")
                row.add_suffix(label)

            url = pin_url(pins[name], update)
            if url:
                button = Gtk.Button(
                    icon_name="web-browser-symbolic", valign=Gtk.Align.CENTER,
                    tooltip_text=("Show the commits in this update" if update
                                  else "Show the history at this revision"),
                    css_classes=["flat"],
                )
                button.connect("clicked", lambda _b, u=url: self.open_url(u))
                row.add_suffix(button)
                row.set_activatable_widget(button)
            group.add(row)

        page = Adw.PreferencesPage(title="Sources", icon_name="folder-download-symbolic")
        page.add(group)
        dialog = Adw.PreferencesDialog(title="Sources")
        dialog.add(page)
        dialog.present(self)

    # -- actions --------------------------------------------------------------
    def adopt(self, restored):
        """Take a stored check as what the window holds. Returns its age."""
        self.state_stamp, self.updates, text, self.detail = restored
        self.pending_text = text if self.updates else None
        return max(0, int(time.time()) - self.state_stamp)

    def watch_state(self):
        """Follow what happens outside the window, for as long as it is open:
        the answer the timer writes, and the marker it holds while it is
        still working one out.

        The timer writes what it finds to the same file the window opened
        on, so a check landing while it sits there is already the better
        answer — without this the window keeps showing the older one until
        it is told to check again, or reopened.
        """
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
        except OSError:
            return          # nothing is going to be written there either
        self.state_watch = Gio.File.new_for_path(str(STATE)).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.state_watch.connect("changed", self.state_changed)
        self.check_watch = Gio.File.new_for_path(str(CHECK_LOCK)).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.check_watch.connect(
            "changed", lambda *_args: self.sync_check())
        self.sync_check()       # one may be running already

    def sync_check(self):
        """Checking is off while a check is running, this window's own or the
        timer's underneath it: a second one would race the first for the
        state file, and one of the two answers would be dropped.
        """
        # A rebuild counts too: it is the window busy in its own way, and
        # a marker dropped mid-build would otherwise hand the button back.
        busy = self.working or self.rebuilding
        elsewhere = not busy and check_running()
        self.check_button.set_sensitive(not busy and not elsewhere)
        if elsewhere:
            self.say(CHECKING_ELSEWHERE, seconds=0)
        elif self.banner.get_title() == CHECKING_ELSEWHERE:
            # What it found comes in through the state watch and puts its own
            # line up. Only one still standing unanswered is the window's to
            # take back down.
            self.say("")

    def state_changed(self, _monitor, _file, _other, _event):
        """Every event is read back, rather than only the ones that mean a
        finished write: save_check renames the file into place, and a state
        that is half written, for another repo, or for pins that have moved
        since is one load_check turns down anyway."""
        if self.working or self.rebuilding:
            # A rebuild owns the window, and a check of the window's own is
            # about to arrive carrying this same answer.
            return
        restored = load_check(self.repo, self.lockfile)
        if not restored or restored[0] <= self.state_stamp:
            return
        self.adopt(restored)
        self.present_check()

    def present_check(self):
        """Put what the window holds on screen, however it got there."""
        if self.rebuilding:
            # A check started before the rebuild finishing during it. What
            # it found is held; render() would pull the status page up over
            # the live plan. rebuild_done catches the buttons back up.
            return
        self.render()
        self.sync_apply()
        if self.updates:
            self.say(self.verdict())
        else:
            self.show_current()

    def check(self):
        if check_running():
            # The timer got there first — the same check, whose answer
            # arrives through the watch. A second one would only race it.
            self.sync_check()
            return

        self.busy(True, "Checking pins…")

        def report(text):
            # Off the worker thread, so the banner is touched from the main
            # loop like everything else that draws.
            GLib.idle_add(self.progress_line, text)

        def work():
            found = survey(self.repo, self.lockfile, self.workdir, report)
            save_check(self.repo, self.lockfile, *found)
            return found

        self.run_async(work, self.checked)

    def progress_line(self, text):
        """What the check is doing, while it is doing it.

        A spinner and a line rather than a bar: nix reports no progress at
        all for an evaluation or for a question to a substituter, so a bar
        here could only pulse or lie, and the guidelines ask for neither.
        """
        if self.working:
            self.say(text, seconds=0)
        return GLib.SOURCE_REMOVE

    def checked(self, result):
        self.busy(False)
        if isinstance(result, Exception):
            self.say("")
            self.fail(result)
            return

        updates, text, self.detail = result
        self.updates = updates
        # probe_updates always hands back the probed lock file, moved or not.
        # pending_text has to mean "there is something to write", or the
        # Apply button reappears on the next check with nothing to apply.
        self.pending_text = text if updates else None
        # save_check has just written this one; dated here so the watch does
        # not read it straight back in as news.
        self.state_stamp = int(time.time())
        self.present_check()

    def show_current(self, age=None):
        """The status page for having nothing to apply. `age` says how long
        ago that was established, when it was not established just now."""
        pending = pending_tier(self.lockfile)
        headline = TIER_ACTION[pending] or "Everything is current"
        self.say(headline if age is None else f"{headline} · checked {ago(age)}")
        self.offer(pending)
        self.status.set_icon_name(TIER_ICON[pending])
        self.status.set_title(headline)
        # "Nothing new to write" and "what is written is installed" are two
        # claims, and this page used to make the second on the strength of
        # the first.
        if pending == REBUILD:
            description = ("No pin has moved since these were written, and "
                           "what is written has not been built.")
        else:
            description = "No pin has moved since you last applied."
            if pending:
                description += "\n\nAn earlier rebuild is still waiting on it."
        self.status.set_description(description)

    def verdict(self):
        """One line on what was found.

        The headline is the noise ratio: most of those commits are for
        packages this machine does not have.
        """
        changes = self.detail.get("changes", {})
        affected = sum(len(changes.get(key, [])) for key, _ in CATEGORIES)
        commits = sum(v["behind"] for k, v in self.detail.items()
                      if isinstance(v, dict) and v.get("behind"))
        if commits and affected:
            line = f"{affected} of your packages change, out of {commits} commits"
        elif commits:
            line = f"{commits} commits, none of them touch your packages"
        else:
            line = f"{affected} of your packages change"
        action = TIER_ACTION[change_tier(changes)]
        if action:
            line += f" · {action.lower()}"
        return line


    def apply(self, commit, rebuild):
        text, updates = self.pending_text, self.updates
        if not text:
            return

        changes = self.detail.get("changes")
        # The names, not just the fact. What a reboot is owed for can be
        # measured again afterwards; what a log out is owed for cannot, and
        # by then the change set is gone.
        self.applied_session = ([entry["name"] for entry in changes["graphics"]]
                                if changes else [])

        def work():
            write_lockfile(self.lockfile, text)
            if commit:
                commit_lockfile(self.repo, updates, changes)
            return commit

        self.busy(True, "Writing pins…")
        self.run_async(work, lambda r: self.applied(r, rebuild))

    def applied(self, result, rebuild):
        self.busy(False)
        if isinstance(result, Exception):
            self.fail(result)
            return

        committed = result
        self.updates, self.pending_text, self.detail = [], None, {}
        self.render()
        self.sync_apply()
        self.toast("Pins written and committed" if committed else "Pins written")

        if rebuild:
            self.start_rebuild()
            return

        # Writing a pin changes a text file and nothing else. Say so, or
        # "Apply" reads like "installed".
        self.say("Pins written — nothing is installed until you rebuild",
                 seconds=0)
        # No offer here even with a reboot owed from before: the page says
        # to rebuild, and a Restart button next to it would read as the way
        # to finish what was just written, which it is not.
        self.offer(NOTHING)
        self.status.set_icon_name("software-update-available-symbolic")
        self.status.set_title("Rebuild to install")
        self.status.set_description(
            "The pins moved, the system did not. Run:\n\n"
            "sudo nixos-rebuild switch --file ~/nixcfg\n"
            "home-manager switch"
        )

    # -- rebuild --------------------------------------------------------------
    # Four times a second, because the page is redrawn on a timer rather than
    # on the stream: nix emits thousands of events a second during a large
    # rebuild, and a redraw per event leaves the main loop no time to draw.
    TICK = 250

    def start_rebuild(self):
        if self.rebuilding:
            # Two nixos-rebuild switches against one store, and the second
            # would orphan the first's process so Cancel could never reach
            # it. Reachable from finish(), whose button a late check can put
            # back up over a running rebuild.
            return
        self.rebuilding = True
        self.steps = rebuild_steps(self.repo)
        self.replay = None
        self.record = []
        self.logbuf.set_text("")
        self.carried = []
        self.rebuild_started = time.monotonic()
        # Measured before the switch, because afterwards there is nothing
        # left that remembers what the store weighed.
        self.closure_before = closure_stats(profiles())
        self.stack.set_visible_child_name("rebuild")
        self.check_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.cancel_button.set_sensitive(True)   # a cancel left it greyed
        self.back_button.set_visible(False)
        self.output_button.set_visible(True)
        self.ticker = GLib.timeout_add(self.TICK, self.tick)
        self.sync_apply_history()
        self.run_step(0)

    def run_step(self, index):
        if index >= len(self.steps):
            self.rebuild_done(None)
            return

        label, command = self.steps[index]
        self.step_index = index
        self.say(f"{label}…", seconds=0)
        self.step_started = time.monotonic()
        self.clear_activity()
        # Two processes, two sets of counters — but one list of problems, so
        # that a warning from the system step is still on screen when the
        # home step is the one running.
        self.stream = RebuildStream(self.carried)
        self.stream.feed(f"$ {' '.join(command)}")

        try:
            self.proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except OSError as error:
            self.rebuild_done(error)
            return

        threading.Thread(target=self.pump, args=(self.proc, self.stream, index),
                         daemon=True).start()

    def pump(self, proc, stream, index):
        """Read the child line by line off the main loop and into the model.
        nix writes its json to stderr, which is merged in."""
        for line in proc.stdout:
            stream.feed(line.rstrip("\n"))
        code = proc.wait()
        GLib.idle_add(self.step_finished, index, code)

    def tick(self):
        if not self.ticker:
            return GLib.SOURCE_REMOVE
        snapshot = self.stream.snapshot() if self.stream else None
        if snapshot:
            self.draw_rebuild(snapshot)
        return GLib.SOURCE_CONTINUE

    def plan_view(self):
        """Which of the two views the plan is drawn in right now."""
        if self.settings:
            return self.settings.get_string("plan-view")
        action = self.lookup_action("plan-view")
        return action.get_state().get_string() if action else DEFAULT_PLAN_VIEW

    def show_plan_view(self):
        self.plan_views.set_visible_child_name(self.plan_view())

    def watch(self, key):
        """A click on a derivation: read that one, and stop chasing the
        build. The drawer comes out on its own — that is what the click was
        asking for."""
        self.pane.follow.set_active(False)
        self.watching = key
        self.pane.show(self.seen.get(key))
        self.split.set_show_sidebar(True)

    def clear_activity(self):
        self.seen = {}
        self.watching = None
        self.graph.update([])
        self.list.update([])
        self.pane.show(None)

    def pick_reading(self):
        """What a record opens on: whatever failed, or else the last thing
        that said anything at all."""
        failed = [key for key, row in self.seen.items()
                  if row.get("state") == FAILED]
        spoke = [key for key, row in self.seen.items() if row.get("log")]
        return (failed or spoke or [None])[-1]

    def live_steps(self, snapshot):
        """Every step of the run at once: the ones already archived, the one
        that is running, and the ones still to come.

        The page used to show one step at a time, because that is all the
        stream in front of it knew about. The record knows the rest, so the
        tree can hold the whole rebuild — including the half that has not
        started, which is the half people wonder about."""
        steps = []
        for index, (label, _command) in enumerate(self.steps):
            if index < len(self.record):
                kept = self.record[index]
                steps.append(dict(kept, fraction=1.0,
                                  tail=kept["raw"][-STEP_LINES:]))
            elif index == self.step_index:
                steps.append({
                    "label": label, "plan": snapshot["plan"],
                    "downloads": snapshot["downloads"],
                    "summary": snapshot["summary"], "running": True,
                    "fraction": snapshot["fraction"] or 0.0,
                    "tail": snapshot["tail"], "started": self.step_started,
                })
            else:
                steps.append({"label": label, "plan": [], "summary": "",
                              "fraction": None})
        return steps

    def draw_plan(self, plan):
        """Hand the tree to both views. The one not on screen is kept up to
        date too, so switching to it shows the build rather than the build
        as it was when it was last looked at."""
        self.graph.update(plan)
        self.list.update(plan)
        self.plan_views.set_visible(bool(plan))
        return plan

    def draw_rebuild(self, snapshot):
        """Bring the page up to date with one instant of the stream."""
        plan = self.draw_plan(compose(self.live_steps(snapshot),
                                      self.rebuild_started))
        self.seen = {row["key"]: row for row in walk_plan(plan)}
        self.draw_log()

        # Problems only ever grow, so the count is enough to tell whether
        # this redraw has anything new to say about them.
        problems = snapshot["problems"]
        if len(problems) != self.problem_count:
            while child := self.problems.get_first_child():
                self.problems.remove(child)
            for problem in problems:
                self.problems.append(problem_row(problem))
            self.problem_count = len(problems)
        self.problems.set_visible(bool(problems))
        self.problems_heading.set_visible(bool(problems))

        if snapshot["raw"]:
            self.log("\n".join(snapshot["raw"]))

    def draw_log(self):
        """Keep the pane on something worth reading.

        Following sticks with one derivation until it is finished rather
        than hopping to whichever started last: with a dozen builds running
        at once, hopping makes the pane unreadable. In a record there is
        nothing to follow at all — it opens on whatever failed, and every
        node is still one click away.
        """
        self.pane.follow.set_visible(self.replay is None)
        if self.replay:
            if self.watching is None:
                self.watching = self.pick_reading()
            self.pane.show(self.seen.get(self.watching))
            return

        running = [row for row in self.seen.values()
                   if row.get("state") == RUNNING or row.get("state") is None]
        if self.pane.follow.get_active():
            current = self.seen.get(self.watching)
            if current not in running:
                # Nothing left running means the step is over: hold whatever
                # was being read, and if that is nothing, open on the reason
                # it stopped.
                self.watching = (running[0]["key"] if running
                                 else self.watching or self.pick_reading())
        self.pane.show(self.seen.get(self.watching))

    def log(self, text):
        end = self.logbuf.get_end_iter()
        self.logbuf.insert(end, text + "\n")
        # Keep the newest line in view without fighting a user who scrolled up.
        adjustment = self.logscroll.get_vadjustment()
        if adjustment.get_value() + adjustment.get_page_size() >= \
                adjustment.get_upper() - 64:
            GLib.idle_add(lambda: adjustment.set_value(
                adjustment.get_upper() - adjustment.get_page_size()))

    def step_finished(self, index, code):
        # Whatever the stream still holds is drawn once more before the page
        # is handed over: the last events of a failed build arrive after the
        # final tick, and they are the ones worth reading.
        self.carried = self.stream.problems if self.stream else []
        snapshot = self.stream.snapshot() if self.stream else None
        if snapshot:
            self.draw_rebuild(snapshot)
        # Archived here rather than at the end of the run: the stream that
        # holds this step is replaced by the next one, and a failed step is
        # the last thing that happens before the page stops moving.
        self.keep_step(index)

        if self.cancelled:
            self.rebuild_done(None, cancelled=True)
            return GLib.SOURCE_REMOVE
        if code == 126:
            # polkit's own exit code when the dialog is dismissed.
            self.rebuild_done(None, cancelled=True)
            return GLib.SOURCE_REMOVE
        if code != 0:
            label = self.steps[index][0]
            self.rebuild_done(RuntimeError(f"{label} failed (exit {code})."))
            return GLib.SOURCE_REMOVE
        self.run_step(index + 1)
        return GLib.SOURCE_REMOVE

    def cancel_rebuild(self):
        """Stop the run, as far as it can be stopped.

        The flag is what actually cancels: step_finished reads it and does
        not start the next step. Signalling the current one is the part that
        may not be allowed — the system step is pkexec's child and runs as
        root, which an unprivileged parent cannot signal. Saying so is
        better than a button that looks ignored for the rest of the build.
        """
        self.cancelled = True
        self.cancel_button.set_sensitive(False)
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                self.say("Cancelling — the system build runs as root and "
                         "finishes this step first", seconds=0)
                return
        self.say("Cancelling…", seconds=0)

    def leave_rebuild(self):
        """Off the rebuild page — failed, or an old one read back — and
        back to the pins."""
        self.replay = None
        self.output_button.set_visible(False)
        self.split.set_show_sidebar(False)
        self.say("")
        self.render()
        self.sync_apply()

    def rebuild_failed(self, error):
        """A failed rebuild keeps its page.

        The status page can hold one sentence, and the reason a build failed
        is never one sentence — it is the compiler output now sitting in the
        rows behind this banner. Sending the window back to a status page
        would throw away the only copy.
        """
        # The plan stays: the derivation that failed is in it, marked, with
        # what it said still readable in the pane beside it. Clearing it
        # would throw away the only copy of the answer.
        self.say(f"{error} What went wrong is below.", seconds=0)
        self.back_button.set_visible(True)
        self.output_button.set_visible(True)
        if not self.problem_count:
            # nix said nothing a row was made of — a step that died before
            # it started, or was killed. The full output is all there is.
            self.logrow.set_expanded(True)

    # -- the last apply, kept and read back ------------------------------------
    def keep_step(self, index):
        """Put this step's page into the record being built."""
        if self.stream and self.steps:
            self.record.append(self.stream.archive(self.steps[index][0]))

    def keep_apply(self, outcome, message=""):
        """Write the record, and let the menu reach it."""
        if not self.record:
            return
        save_apply({
            "when": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outcome": outcome,
            "message": message,
            "steps": self.record,
        })
        self.sync_apply_history()

    def sync_apply_history(self):
        action = self.lookup_action("last-apply")
        if action:
            action.set_enabled(APPLIED.is_file() and not self.rebuilding)

    def open_apply(self):
        """The last rebuild's page, as it stood when it finished."""
        record = load_apply()
        if not record or not record.get("steps"):
            self.say("Nothing has been applied yet")
            return
        self.replay = record
        self.stack.set_visible_child_name("rebuild")
        self.cancel_button.set_visible(False)
        self.apply_button.set_visible(False)
        self.back_button.set_visible(True)
        self.output_button.set_visible(True)
        self.logrow.set_expanded(False)
        self.draw_replay()

    def draw_replay(self):
        """The record, as the same tree the live page draws.

        Every step is in it, so there is nothing to switch between: the run
        is the root, and what failed is a node under it with its output
        still attached."""
        if not self.replay:
            return
        self.clear_activity()
        self.logbuf.set_text("")

        steps = [dict(step, fraction=1.0, tail=step["raw"][-STEP_LINES:])
                 for step in self.replay["steps"]]
        plan = self.draw_plan(compose(steps))
        self.seen = {row["key"]: row for row in walk_plan(plan)}

        problems = [problem for step in self.replay["steps"]
                    for problem in step["problems"]]
        while child := self.problems.get_first_child():
            self.problems.remove(child)
        for problem in problems:
            self.problems.append(problem_row(problem))
        self.problem_count = len(problems)
        self.problems.set_visible(bool(problems))
        self.problems_heading.set_visible(bool(problems))
        self.log("\n".join(line for step in self.replay["steps"]
                           for line in step["raw"]))
        self.draw_log()
        # A record opens on what failed, so the drawer opens with it. There
        # is no build to watch here — reading is the only reason to be on
        # this page at all.
        self.split.set_show_sidebar(self.watching is not None)

        headline = self.replay.get("message") or {
            "failed": "The rebuild failed",
            "cancelled": "The rebuild was cancelled",
        }.get(self.replay["outcome"], "Applied")
        self.say(f"{headline} · {applied_ago(self.replay.get('when'))}",
                 seconds=0)

    def rebuild_done(self, error, cancelled=False):
        self.proc = None
        self.rebuilding = False
        self.cancelled = False
        self.cancel_button.set_visible(False)
        if self.ticker:
            GLib.source_remove(self.ticker)
            self.ticker = 0
        self.sync_check()
        self.output_button.set_visible(False)
        self.keep_apply("failed" if error and not cancelled else
                        "cancelled" if cancelled else "ok",
                        str(error) if error and not cancelled else "")
        self.sync_apply_history()
        # A check that landed mid-rebuild was held back from the page; the
        # buttons it should have moved are this window's to catch up on.
        self.sync_apply()

        if error and not cancelled:
            self.rebuild_failed(error)
            self.offer(NOTHING)
            return

        self.stack.set_visible_child_name("status")

        # A cancelled rebuild leaves the pins written and nothing installed,
        # which is what REBUILD is for. Offered without asking rebuild_owed()
        # first: a run stopped in its home half leaves a system that already
        # matches the pin, and is still unfinished.
        #
        # A failed one is not handled here at all — it keeps its own page,
        # above, because the build output is the answer and a status page
        # cannot hold it. It leaves the same thing behind, and render() reads
        # that back off the lock file when Back sends the window home.
        if cancelled:
            self.say("Rebuild cancelled")
            self.offer(REBUILD)
            self.status.set_icon_name(TIER_ICON[REBUILD])
            self.status.set_title("Rebuild cancelled")
            self.status.set_description("The pins are written and the rebuild "
                                        "stopped part way. Rebuild picks it up "
                                        "from the top.")
            return

        # The switch is what moved /run/current-system, so from here the
        # reboot half is measured rather than predicted. The session half
        # cannot be: nothing on disk records what the running session was
        # built from, so it gets written down while it is still known.
        if self.applied_session:
            mark_session_stale()

        tier = pending_tier(self.lockfile)
        headline = TIER_ACTION[tier] or "Installed"
        self.say(headline)
        self.offer(tier)
        self.status.set_icon_name(TIER_ICON[tier])
        self.status.set_title(headline)
        description = "The new system and home generations are live."
        # What the switch cost, now that both ends of it exist. Same two
        # numbers nvd and nh print, and the only summary of a rebuild that
        # does not depend on having predicted it correctly beforehand.
        delta = closure_delta(self.closure_before, closure_stats(profiles()))
        if delta:
            description += f"\n\n{delta}"
        # What is owed, named. The title already says that something is —
        # repeating it in a longer sentence is the one thing a description
        # here must not spend its words on.
        if tier == REBOOT:
            owed = reboot_needed(boot_paths("/run/current-system"))
        else:
            owed = self.applied_session if tier == SESSION else []
        if owed:
            description += f"\n\nWaiting on {', '.join(owed)}."
        self.status.set_description(description)

    def about(self):
        Adw.AboutDialog(
            application_name="npins",
            application_icon="de.lucsoft.NpinsUi",
            developer_name="lucsoft",
            version="0.2.0",
            comments="Check and move the pins in npins/sources.json.",
            website="https://github.com/andir/npins",
        ).present(self)
