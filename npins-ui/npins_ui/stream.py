"""The rebuild, as nix reports it.

nix --log-format internal-json emits "@nix {...}" on stderr, and everything
the rebuild page shows comes out of it. Activities open, carry results, and
stop; the id is the thread that ties the three together, and `parent` nests
them. The types that carry something worth showing:

  104 builds        opened once, holds the [done, expected] build counter
  103 copy-paths    the same for downloads
  105 build         one per derivation, fields[0] is the .drv being built
  108 substitute    one per path fetched, with 100 and 101 nested under it
  100 copy-path     fields[0] the path, fields[1] where from, unpacked bytes
  101 file-transfer fields[0] the URL, and the bytes actually off the wire

and the results that hang off an activity's id:

  101 build-log-line  what the builder printed — the only place a compile
                      error exists before nix summarises it
  104 set-phase       unpackPhase, configurePhase, buildPhase, …
  105 progress        [done, expected, running, failed]
"""

import collections
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse


ACT_COPY_PATH, ACT_FILE_TRANSFER = 100, 101
ACT_COPY_PATHS, ACT_BUILDS, ACT_BUILD, ACT_SUBSTITUTE = 103, 104, 105, 108

RES_BUILD_LOG_LINE, RES_SET_PHASE, RES_PROGRESS = 101, 104, 105

# nix's own verbosity levels. Only the top two are worth interrupting for.
LEVEL_ERROR, LEVEL_WARN = 0, 1

# nix colours its messages even when asked for json, so the escapes arrive
# inside the text. A GTK label renders them as stray digits and a blank.
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The derivation a failure message names, so its output can be found again.
DRV_NAMED = re.compile(r"/nix/store/[a-z0-9]{32}-\S+?\.drv")

BUILD, DOWNLOAD = "build", "download"

# Per build, how much of its output to hold. A compile that fails says why in
# its last few lines; the thousands before that are the ones that worked.
TAIL = 60

# Builds that have already stopped, kept in case nix is about to say one of
# them failed — which it does *after* the activity is gone.
RECENT = 24

# How much of nix's own commentary the fallback view keeps. Build output is
# not in here: interleaved from a dozen jobs it is unreadable, which is the
# whole reason the per-derivation rows exist.
RAW_LINES = 2000

# How much of that a step node carries. The whole run is still one click
# away under Details; this is the part worth re-setting four times a second.
STEP_LINES = 200

# Before it builds anything, nix says what it is about to build, as a heading
# and one indented store path per line. That listing is the build plan, and
# it is the only place the plan exists — the activity stream announces each
# build as it starts and never says what is still to come.
PLAN_HEADING = re.compile(r"^(?:this|these \d+) derivations? will be built:")
PLAN_ENTRY = re.compile(r"^\s+(/nix/store/\S+\.drv)$")

# What a node in the build tree can be. Planned is what the listing above
# hands over; the rest the activity stream moves it through.
PLANNED, RUNNING, DONE, FAILED = "planned", "running", "done", "failed"

# A plan bigger than this is not a plan anyone reads. It is only a guard
# against a rebuild that plans hundreds of derivations: the graph would draw
# them a few pixels wide and the list would scroll for a minute.
PLAN_NODES = 80

# Which view a rebuild opens in when nothing has said otherwise. The schema
# carries the same default; this is what a run from a checkout falls back to.
DEFAULT_PLAN_VIEW = "graph"

# pkexec is how a GNOME app asks for root: polkit puts up the password dialog
# and gnome-shell is already the agent. Absolute paths are required — pkexec
# scrubs the environment, so PATH lookups do not survive it.
PKEXEC = "/run/wrappers/bin/pkexec"
NIXOS_REBUILD = "/run/current-system/sw/bin/nixos-rebuild"


def rebuild_steps(repo):
    return [
        ("Building the system", [
            PKEXEC, NIXOS_REBUILD, "switch",
            "--file", str(repo), "--log-format", "internal-json",
        ]),
        # -f matters as much as --file above. Without it home-manager takes
        # ~/.config/home-manager/home.nix no matter which repo this window is
        # pointed at, so the two steps would build from different trees.
        ("Building your home", ["home-manager", "switch",
                                "-f", str(Path(repo) / "home.nix")]),
    ]


def package_name(store_path):
    """The readable half of a store path. The hash is not for reading and
    the .drv suffix says nothing the row does not already say."""
    name = str(store_path).rsplit("/", 1)[-1].removesuffix(".drv")
    return name.split("-", 1)[-1] if "-" in name else name


def input_derivations(drv):
    """The derivations a derivation is built from.

    This is the one thing the activity stream does not carry. nom gets it by
    reading the .drv file and taking its inputDrvs; the store's own
    reference graph holds the same edges — a .drv references the .drv of
    each of its inputs — so asking nix costs a database query instead of an
    ATerm parser.
    """
    try:
        out = subprocess.run(["nix-store", "-q", "--references", drv],
                             check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.split() if line.endswith(".drv")]


def build_forest(planned):
    """Edges and roots among the derivations a rebuild plans to build.

    Edges *within* the plan only. An input already in the store is not going
    to be built and so is not a node here, which is what keeps this small: a
    rebuild that moves the configuration rather than the pins plans on the
    order of a dozen derivations, because everything else is a download.

    Returns (edges, roots), a root being a derivation nothing else in the
    plan is waiting for — for a system rebuild, the toplevel.
    """
    inside = set(planned)
    edges, parented = {}, set()
    for drv in planned:
        deps = [d for d in input_derivations(drv) if d in inside and d != drv]
        edges[drv] = deps
        parented.update(deps)
    return edges, [drv for drv in planned if drv not in parented]


class Activity:
    """One thing nix is doing right now: a build, or a download."""

    __slots__ = ("kind", "name", "detail", "log", "done", "expected",
                 "started", "drv")

    def __init__(self, kind, name, detail=""):
        self.kind = kind
        self.name = name
        self.detail = detail
        self.drv = ""
        self.log = collections.deque(maxlen=TAIL)
        self.done = self.expected = 0
        self.started = time.monotonic()


class RebuildStream:
    """The internal-json stream, as something a window can draw.

    Fed line by line off the reader thread and read on a timer by the main
    loop — nix emits thousands of events a second, and one idle callback per
    event is not something GTK survives. The lock covers the model rather
    than any single field, because a redraw wants one consistent set of rows
    and not a freshly torn one per row.
    """

    def __init__(self, problems=()):
        self.lock = threading.Lock()
        self.kinds = {}       # activity id -> type
        self.parents = {}     # activity id -> parent id
        self.live = {}        # activity id -> Activity
        self.totals = {}      # ACT_BUILDS / ACT_COPY_PATHS -> (done, expected)
        self.recent = collections.OrderedDict()   # stopped build -> its output
        # Same thing keyed by derivation rather than name, and kept for the
        # whole run: a build that has finished still has output worth
        # reading, and after the page is archived it is the only copy.
        self.tails = collections.OrderedDict()    # drv -> its last output
        # Downloads that have arrived. A rebuild that only moves a pin
        # builds nothing and downloads everything, and without this the
        # page would have nothing to show for it once they finish.
        self.fetched = collections.OrderedDict()  # name -> the finished row
        self.problems = list(problems)  # what nix called an error or a warning
        self.raw = collections.deque(maxlen=RAW_LINES)
        self.pending = []     # raw lines the view has not been handed yet
        self.dirty = True

        # The build plan, and the graph over it. `planned` is ordered because
        # nix lists the plan bottom up, which puts the toplevel last and its
        # inputs before it — a reasonable order to fall back to while the
        # edges are still being worked out.
        self.planned = collections.OrderedDict()   # drv -> PLANNED/RUNNING/…
        self.by_drv = {}      # drv -> the Activity now building it
        self.edges = {}       # drv -> the drvs in the plan it waits for
        self.roots = []
        self.reading_plan = False
        self.grapher = None

    # -- fed from the reader thread -------------------------------------------
    def feed(self, line):
        with self.lock:
            self.dirty = True
            if not line.startswith("@nix "):
                self.remember(line)
                return
            try:
                event = json.loads(line[5:])
            except ValueError:
                return
            action = event.get("action")
            if action == "start":
                self.started(event)
            elif action == "stop":
                self.stopped(event.get("id"))
            elif action == "result":
                self.result(event)
            elif action == "msg" and event.get("msg"):
                self.message(event)

    def remember(self, text):
        self.raw.append(text)
        self.pending.append(text)

    def started(self, event):
        ident, kind = event.get("id"), event.get("type")
        fields = event.get("fields") or []
        self.kinds[ident] = kind
        self.parents[ident] = event.get("parent", 0)

        if kind == ACT_BUILD and fields:
            drv = str(fields[0])
            activity = Activity(BUILD, package_name(drv))
            self.live[ident] = activity
            # A build nix never listed — the plan is printed per invocation,
            # and the home step prints one of its own. Take it as a node
            # anyway; with no inputs in the plan it stands as its own root.
            self.planned.setdefault(drv, PLANNED)
            self.planned[drv] = RUNNING
            self.by_drv[drv] = activity
            activity.drv = drv
            # The listing is normally closed by the next message, but the
            # first build starting is just as good a sign that it is over.
            self.reading_plan = False
            self.resolve_graph()
            self.remember(event.get("text") or f"building {drv}")
        elif kind == ACT_COPY_PATH and len(fields) > 1:
            # Where from, not the full URL: one row has no space for a nar
            # hash, and which cache answered is the part worth seeing.
            host = urlparse(str(fields[1])).netloc or str(fields[1])
            self.live[ident] = Activity(DOWNLOAD, package_name(fields[0]), host)

    def stopped(self, ident):
        activity = self.live.pop(ident, None)
        self.kinds.pop(ident, None)
        self.parents.pop(ident, None)
        if activity and activity.drv:
            self.by_drv.pop(activity.drv, None)
            # A build that stops has succeeded as far as this stream is
            # concerned. The failure message, when there is one, arrives
            # afterwards and says so itself.
            if self.planned.get(activity.drv) == RUNNING:
                self.planned[activity.drv] = DONE
        # nix reports a failure a moment *after* closing the activity, and by
        # then the builder's output is the only thing that says why. Hold the
        # last few so the message can be given back its evidence.
        if activity and activity.kind == DOWNLOAD:
            self.fetched[activity.name] = {
                "key": (DOWNLOAD, activity.name), "kind": DOWNLOAD,
                "name": activity.name, "state": DONE,
                "detail": activity.detail,
                "done": activity.expected or activity.done,
                "expected": activity.expected, "started": activity.started,
                "waiting": 0, "log": [], "kids": [],
            }
            while len(self.fetched) > PLAN_NODES:
                self.fetched.popitem(last=False)
        if activity and activity.kind == BUILD and activity.log:
            self.recent[activity.name] = list(activity.log)
            while len(self.recent) > RECENT:
                self.recent.popitem(last=False)
            if activity.drv:
                self.tails[activity.drv] = list(activity.log)
                while len(self.tails) > PLAN_NODES:
                    self.tails.popitem(last=False)

    def result(self, event):
        ident, kind = event.get("id"), event.get("type")
        fields = event.get("fields") or []
        if kind == RES_PROGRESS and len(fields) > 1:
            owner = self.kinds.get(ident)
            if owner in (ACT_COPY_PATHS, ACT_BUILDS):
                self.totals[owner] = (fields[0], fields[1])
            elif owner == ACT_FILE_TRANSFER:
                # Bytes off the wire, which is what the cache quoted. The
                # copy-path above it counts unpacked bytes instead, and the
                # two differ by whatever the compression won.
                activity = self.live.get(self.parents.get(ident))
                if activity:
                    activity.done, activity.expected = fields[0], fields[1]
        elif kind == RES_BUILD_LOG_LINE and fields:
            activity = self.live.get(ident)
            if activity:
                activity.log.append(ANSI.sub("", str(fields[0])))
        elif kind == RES_SET_PHASE and fields:
            activity = self.live.get(ident)
            if activity:
                activity.detail = str(fields[0]).removesuffix("Phase")

    def take_plan(self, text):
        """Collect the listing nix prints before it builds anything.

        One message per line, so this is a small state machine: a heading
        opens the listing, indented store paths fill it, and anything else
        closes it.
        """
        if PLAN_HEADING.match(text):
            self.reading_plan = True
            return
        if not self.reading_plan:
            return
        entry = PLAN_ENTRY.match(text)
        if entry:
            self.planned.setdefault(entry.group(1), PLANNED)
            return
        self.reading_plan = False
        self.resolve_graph()

    def resolve_graph(self):
        """Work out the edges, off the thread that is reading the stream.

        One store query per planned derivation. That is nothing for the
        dozen a configuration change plans, but nix is writing into a pipe
        while this runs, and a reader that stops reading stops the build.
        """
        if self.grapher or not self.planned:
            return
        planned = list(self.planned)

        def work():
            edges, roots = build_forest(planned)
            with self.lock:
                self.edges, self.roots = edges, roots
                self.dirty = True

        self.grapher = threading.Thread(target=work, daemon=True)
        self.grapher.start()

    def message(self, event):
        text = ANSI.sub("", event["msg"]).rstrip()
        self.remember(text)
        self.take_plan(text)
        if event.get("level", LEVEL_WARN + 1) > LEVEL_WARN:
            return
        named = DRV_NAMED.search(text)
        if named and named.group(0) in self.planned:
            self.planned[named.group(0)] = FAILED
        name = package_name(named.group(0)) if named else None
        self.problems.append({
            "text": text,
            "error": event.get("level") == LEVEL_ERROR,
            "name": name,
            "log": self.recent.get(name, []),
        })

    # -- the plan, as a forest ------------------------------------------------
    def waiting_on(self, drv):
        """How much of a derivation's subtree is still outstanding.

        Distinct derivations, not a walk count: an input feeding two others
        is one thing to wait for, not two.
        """
        found, stack = set(), list(self.edges.get(drv, []))
        while stack:
            dep = stack.pop()
            if dep in found:
                continue
            found.add(dep)
            stack.extend(self.edges.get(dep, []))
        return sum(1 for dep in found if self.planned.get(dep) != DONE)

    def forest(self):
        """The plan as nested nodes, each derivation appearing once.

        A build graph is not a tree — an input can feed several derivations —
        so it has to be cut somewhere. nom cuts it at the second sighting and
        drops that node rather than drawing it again, which keeps one row per
        derivation; what the dropped edge was carrying still shows up in the
        parent's count of what it is waiting for.

        Nesting happens before the drawing because which sightings are second
        depends on the order of the walk, and the box characters have to know
        which child really is the last one.
        """
        seen = set()

        def nest(drv):
            if drv in seen:
                return None
            seen.add(drv)
            kids = [node for node in map(nest, self.edges.get(drv, []))
                    if node is not None]
            return (drv, kids)

        forest = [node for node in map(nest, self.roots) if node is not None]
        # Anything the graph did not reach still gets a row. nix lists what
        # it will build before it builds it, but a derivation that turns up
        # after the edges were worked out would otherwise be built in
        # silence — and silence is the one thing this page must not do.
        forest += [node for node in map(nest, self.planned) if node is not None]
        return forest

    def plan(self):
        """The forest as nested nodes, each carrying what a view needs.

        Both views read this one shape: the graph nests by "kids", and the
        list draws its connector lines off depth/last/pipes. Which child is
        the last one depends on the order of the walk, so it is decided here,
        once, rather than in each view.
        """
        nodes = []

        def carry(drv, kids, depth, last, pipes):
            if len(nodes) >= PLAN_NODES:
                return None
            activity = self.by_drv.get(drv)
            node = {
                "key": ("node", drv),
                "kind": BUILD,
                "name": package_name(drv),
                "state": self.planned.get(drv, PLANNED),
                "waiting": self.waiting_on(drv),
                "detail": activity.detail if activity else "",
                "started": activity.started if activity else 0,
                "log": (list(activity.log) if activity
                        else self.tails.get(drv, [])),
                "depth": depth,
                "last": last,
                "pipes": pipes,
                "kids": [],
            }
            nodes.append(node)
            below = pipes + ((not last,) if depth else ())
            for index, (kid, sub) in enumerate(kids):
                child = carry(kid, sub, depth + 1, index == len(kids) - 1,
                              below)
                if child is not None:
                    node["kids"].append(child)
            return node

        forest = self.forest()
        roots = []
        for index, (drv, kids) in enumerate(forest):
            root = carry(drv, kids, 0, index == len(forest) - 1, ())
            if root is not None:
                roots.append(root)
        return roots

    def downloads(self):
        """What this step fetched, as nodes — the ones still arriving and
        the ones already here.

        A download that finishes used to disappear: the activity was closed
        and the row went with it. For a rebuild that only moves a pin that
        is the whole story, so it is kept instead, and it hangs under the
        step that fetched it rather than in a list of its own.
        """
        live = [{"key": (DOWNLOAD, a.name), "kind": DOWNLOAD, "name": a.name,
                 "state": RUNNING, "detail": a.detail, "done": a.done,
                 "expected": a.expected, "started": a.started, "waiting": 0,
                 "log": [], "kids": []}
                for a in self.live.values() if a.kind == DOWNLOAD]
        done = [dict(row) for row in self.fetched.values()]
        return sorted(live + done, key=lambda row: row["started"])

    # -- read from the main loop ----------------------------------------------
    def snapshot(self):
        """Everything the page draws, taken at one instant, or None when
        nothing has happened since the last one."""
        with self.lock:
            if not self.dirty:
                return None
            self.dirty = False
            pending, self.pending = self.pending, []
            return {"plan": self.plan(), "downloads": self.downloads(),
                    "tail": list(self.raw)[-STEP_LINES:],
                    "problems": list(self.problems),
                    "fraction": self.fraction(), "summary": self.summary(),
                    "raw": pending}

    def archive(self, label):
        """This step as something that can be read back later.

        The same shape the page draws from, taken once the step is over: the
        plan with its states, what every derivation said, the problems, and
        nix's own output. A rebuild is worth re-reading — most of all the
        one that failed — and none of this survives the process otherwise.
        """
        with self.lock:
            return {
                "label": label,
                "plan": self.plan(),
                "downloads": self.downloads(),
                "problems": list(self.problems),
                "tail": list(self.raw)[-STEP_LINES:],
                "summary": self.summary(),
                "raw": list(self.raw),
            }

    def fraction(self):
        done = sum(v[0] for v in self.totals.values())
        expected = sum(v[1] for v in self.totals.values())
        return done / expected if expected else None

    def summary(self):
        builds = self.totals.get(ACT_BUILDS, (0, 0))
        copies = self.totals.get(ACT_COPY_PATHS, (0, 0))
        parts = []
        if builds[1]:
            parts.append(f"{builds[0]}/{builds[1]} built")
        if copies[1]:
            parts.append(f"{copies[0]}/{copies[1]} downloaded")
        return " · ".join(parts)
