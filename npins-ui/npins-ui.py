#!/usr/bin/env python3
"""An Adwaita front end for npins.

Answers three questions, cheapest first: has anything moved, how far, and
which of the packages I actually installed does it change.
"""

import collections
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "de.lucsoft.NpinsUi"
LOCKFILE = "npins/sources.json"
CATEGORIES = [("apps", "Apps"), ("kernel", "Kernel and firmware"),
              ("graphics", "Graphics and fonts"), ("system", "System"),
              ("dependencies", "Dependencies")]
CACHE = Path(GLib.get_user_cache_dir()) / "npins-ui"


def eval_expression():
    """Where versions.nix landed. The wrapper sets this; fall back to the
    source tree so the script also runs straight from a checkout."""
    return Path(os.environ.get("NPINS_UI_EVAL", Path(__file__).parent / "versions.nix"))


def sizes_expression():
    """sizes.nix is installed beside versions.nix, so one variable places
    both and the two cannot drift into different trees."""
    return eval_expression().parent / "sizes.nix"


# -----------------------------------------------------------------------------
# npins
# -----------------------------------------------------------------------------
def npins(*args, lockfile=None):
    cmd = ["npins"]
    if lockfile:
        cmd += ["--lock-file", str(lockfile)]
    return subprocess.run(
        cmd + list(args), check=True, capture_output=True, text=True
    ).stdout.strip()


def pin_revision(pin):
    """The commit a pin sits on, short form.

    Channel pins do not store a revision field, but the release directory in
    their URL ends in one — nixos-26.05.10402.1e8bc658fc98 — and the forge
    API accepts that short form directly.
    """
    if pin.get("type") == "Channel":
        segments = [s for s in urlparse(pin.get("url", "")).path.split("/") if s]
        if len(segments) >= 2:
            return segments[-2].rsplit(".", 1)[-1]
        return None
    return pin.get("revision")


def pin_version(pin):
    kind = pin.get("type")
    if kind == "Channel":
        segments = [s for s in urlparse(pin.get("url", "")).path.split("/") if s]
        if len(segments) >= 2:
            return segments[-2].removeprefix("nixos-")
    if kind == "Git":
        return pin.get("revision", "?")[:12]
    return pin.get("version") or pin.get("revision") or "?"


def pin_repo(pin):
    """owner/repo on GitHub, or None when the pin is not from there."""
    if pin.get("type") == "Channel":
        return "NixOS/nixpkgs"
    repo = pin.get("repository", {})
    if repo.get("type") == "GitHub":
        return f"{repo['owner']}/{repo['repo']}"
    return None


def pin_branch(pin):
    """The branch a pin follows. Channel pins keep it under `name`
    (nixos-26.05), git pins under `branch` (release-26.05); both happen to
    be branch names on the forge."""
    return pin.get("branch") or pin.get("name")


def pin_url(pin, update=None):
    """Where to read the commits for a pin.

    With an update pending that is the compare view — exactly the range the
    app is reporting on. Without one it is the branch the pin follows, which
    is where anything new will show up; the frozen history at the pinned
    revision holds no news by definition.
    """
    repo = pin_repo(pin)
    if not repo:
        return None
    if update and update.get("old_rev") and update.get("new_rev"):
        return (f"https://github.com/{repo}/compare/"
                f"{update['old_rev']}...{update['new_rev']}")
    target = pin_branch(pin) or pin_revision(pin)
    if not target:
        return f"https://github.com/{repo}"
    return f"https://github.com/{repo}/commits/{target}"


def read_pins(lockfile):
    return json.loads(Path(lockfile).read_text())["pins"]


def probe_updates(lockfile, workdir):
    """Update a copy of the lock file and report what changed.

    npins has a --dry-run, but it prints nothing at all — only "Dry run
    successful.", whether or not anything moved, so there is no output to
    parse. Lockfile mode is the way in: --lock-file makes npins work on an
    arbitrary sources.json and write nothing else, so updating a throwaway
    copy and diffing the two JSONs gives the answer as structured data while
    the repo stays untouched.

    The copy is kept afterwards, because resolving the new store paths for
    the version diff needs a lock file to point npins at.
    """
    probe = Path(workdir) / "sources.json"
    shutil.copy(lockfile, probe)
    npins("update", lockfile=probe)

    before, after = read_pins(lockfile), read_pins(probe)
    updates = [
        {
            "name": name,
            "old": pin_version(before[name]),
            "new": pin_version(after[name]),
            "old_rev": pin_revision(before[name]),
            "new_rev": pin_revision(after[name]),
            "repo": pin_repo(before[name]),
        }
        for name in sorted(before)
        if name in after and before[name] != after[name]
    ]
    # Keep npins' own bytes so applying cannot reformat the file.
    return updates, probe.read_text()


def write_lockfile(lockfile, text):
    """Replace the lock file atomically, so a crash cannot truncate it."""
    lockfile = Path(lockfile)
    tmp = lockfile.with_suffix(".json.new")
    tmp.write_text(text)
    os.replace(tmp, lockfile)


# -----------------------------------------------------------------------------
# forge — how far behind, and the commits in between
# -----------------------------------------------------------------------------
def github(path):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "npins-ui"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def compare(repo, old_rev, new_rev):
    """Commit subjects between two revisions, and how many there are.

    The compare endpoint caps its commits array at 250, so a range wider
    than that has to be paged or the changelog silently loses its tail.
    """
    first = github(f"/repos/{repo}/compare/{old_rev}...{new_rev}?per_page=250")
    total = first.get("total_commits", 0)
    commits = list(first.get("commits", []))
    page = 2
    while len(commits) < total and page <= 8:
        more = github(
            f"/repos/{repo}/compare/{old_rev}...{new_rev}?per_page=250&page={page}"
        )
        batch = more.get("commits", [])
        if not batch:
            break
        commits += batch
        page += 1

    subjects = [c["commit"]["message"].split("\n")[0].strip() for c in commits]
    return {"total": total, "subjects": subjects, "complete": len(commits) >= total}


# Which pins can explain what is installed. versions.nix evaluates the two
# configs against nixpkgs and home-manager and against nothing else, so a
# commit from any other pin cannot be attributed to a package on this
# machine. nixpkgs-unstable is the reason this matters: it feeds one
# sandboxed program, but its commits name the same packages the stable tree
# carries, and matching those against the closure reports a bump that is not
# coming. Leaving them out hides nothing — the pin still shows as moved.
CLOSURE_PINS = ("nixpkgs", "home-manager")


def closure_subjects(by_pin):
    """The commit subjects that may be matched against this machine."""
    return [subject for pin in CLOSURE_PINS for subject in by_pin.get(pin, [])]


def commit_age(repo, rev):
    stamp = github(f"/repos/{repo}/commits/{rev}")["commit"]["committer"]["date"]
    when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - when).days
    if days <= 0:
        return "pinned today"
    return f"pinned {days} day{'s' if days > 1 else ''} ago"


def changelog_for(package, subjects):
    """nixpkgs writes `curl: 8.21.0 -> 8.22.0`, so the package name before
    the colon is enough to pull a package's own commits out of the range."""
    prefix = f"{package.lower()}:"
    hits = []
    for subject in subjects:
        body = subject
        if body.startswith("["):  # [backport staging-26.05] curl: ...
            body = body.split("]", 1)[-1].strip()
        if body.lower().startswith(prefix):
            hits.append(body)
    return hits


# -----------------------------------------------------------------------------
# evaluation — which of my packages change
# -----------------------------------------------------------------------------
def eval_cache(prefix, nixpkgs, home_manager, repo, expression):
    """Where the answer for one pins-plus-configs-plus-expression triple goes.

    A pin is an immutable store path and the two config files decide what is
    in play, so an answer only goes stale when one of those changes. The
    expression counts as one of them: leaving it out means a changed .nix
    file keeps being answered from a cache the old one built — which fails
    silently, as an empty diff rather than an error.
    """
    key = hashlib.sha256()
    for part in (nixpkgs, home_manager):
        key.update(str(part).encode())
    for name in ("configuration.nix", "home.nix"):
        key.update(Path(repo, name).read_bytes())
    key.update(Path(expression).read_bytes())
    return CACHE / f"{prefix}-{key.hexdigest()[:16]}.json"


def trim_cache(prefix):
    """One entry per pin pair per config revision, and pins move every week.
    Nothing here is precious — it is all re-derivable — so keep a handful."""
    entries = sorted(CACHE.glob(f"{prefix}-*.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in entries[20:]:
        stale.unlink(missing_ok=True)


def package_versions(nixpkgs, home_manager, repo):
    """Top-level package versions for one pin set, cached."""
    cached = eval_cache("versions", nixpkgs, home_manager, repo,
                        eval_expression())
    if cached.is_file():
        return json.loads(cached.read_text())

    out = subprocess.run(
        [
            "nix-instantiate", "--eval", "--strict", "--json",
            "--argstr", "nixpkgs", str(nixpkgs),
            "--argstr", "homeManager", str(home_manager),
            "--argstr", "repo", str(repo),
            str(eval_expression()),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(out)
    trim_cache("versions")
    return json.loads(out)


# nix prints this for a derivation it would have to fetch, and prints nothing
# at all when there is nothing to fetch.
FETCH_SIZES = re.compile(
    r"will be fetched \(([\d.]+ [KMGTP]?i?B) download, ([\d.]+ [KMGTP]?i?B) unpacked\)")

# Long enough for the substituters to be asked about a few thousand paths,
# short enough that a cache which has stopped answering cannot hold up the
# check. Losing the estimate costs one row; waiting on it costs the answer.
DRY_RUN_TIMEOUT = 120


def download_estimate(nixpkgs, home_manager, repo):
    """What a rebuild would pull in, without pulling any of it.

    nix answers this for a derivation it has never built: --dry-run asks the
    substituters what they hold and prints both sizes. Two calls, because
    they are two different costs — instantiating the pair is about fourteen
    seconds of pure evaluation, and querying the caches is network.

    Returns {"download", "unpacked"} as nix formatted them, or None when
    there is nothing to fetch.
    """
    cached = eval_cache("download", nixpkgs, home_manager, repo,
                        sizes_expression())
    if cached.is_file():
        return json.loads(cached.read_text()) or None

    drvs = subprocess.run(
        [
            "nix-instantiate", "-A", "system", "-A", "home",
            "--argstr", "nixpkgs", str(nixpkgs),
            "--argstr", "homeManager", str(home_manager),
            "--argstr", "repo", str(repo),
            str(sizes_expression()),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.split()

    # The sizes land on stderr, as the running commentary they are for a
    # human. --dry-run means nothing is built or fetched either way.
    done = subprocess.run(
        ["nix-store", "--realise", "--dry-run", *drvs],
        capture_output=True, text=True, timeout=DRY_RUN_TIMEOUT,
    )
    # Silence from a run that failed is not the same news as silence from a
    # run that found nothing, and writing the first one down as the second
    # would keep saying it until the pins move again.
    done.check_returncode()

    found = FETCH_SIZES.search(done.stderr)
    answer = {"download": found.group(1), "unpacked": found.group(2)} if found else {}
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(answer))
    trim_cache("download")
    return answer or None


def store_paths(lockfile):
    return (npins("get-path", "nixpkgs", lockfile=lockfile),
            npins("get-path", "home-manager", lockfile=lockfile))


def prefix_set(store_names):
    """Every dash-boundary prefix of each store path name, so that asking
    "is there a curl in here" is a set lookup rather than a scan."""
    prefixes = set()
    for name in store_names:
        name = name.split("-", 1)[1] if "-" in name else name
        parts = name.split("-")
        for i in range(1, len(parts) + 1):
            prefixes.add("-".join(parts[:i]).lower())
    return prefixes


def launcher_prefixes():
    """Packages that ship a desktop launcher, read off the built profiles.

    This is what separates an app from a system package, and it is the only
    honest signal available: where a package is *declared* says nothing.
    Firefox comes from a NixOS module and would otherwise read as a system
    package, while btop sits in home.packages and would read as an app.
    """
    targets, execs = [], set()
    for directory in (Path("/run/current-system/sw/share/applications"),
                      Path.home() / ".nix-profile/share/applications",
                      Path.home() / ".local/share/applications"):
        try:
            entries = list(directory.glob("*.desktop"))
        except OSError:
            continue
        for entry in entries:
            try:
                resolved = entry.resolve()
                text = entry.read_text(errors="replace")
            except OSError:
                continue
            parts = resolved.parts
            if "store" in parts:
                # Some entries are a bare .desktop derivation rather than a
                # file inside a package, so the name carries the suffix.
                targets.append(parts[parts.index("store") + 1]
                               .removesuffix(".desktop"))
            # The Exec line names the binary, which is usually the package.
            # It is the only link for entries that are their own derivation
            # or a hand-written override — Discord and Signal both are.
            for line in text.splitlines():
                if line.startswith("Exec="):
                    command = line[5:].strip().split()
                    if command:
                        execs.add(Path(command[0]).name.lower())
                    break
    return prefix_set(targets) | execs


OUTPUT_SUFFIXES = ("bin", "dev", "doc", "man", "info", "lib", "out",
                   "static", "debug", "devdoc")


def profiles():
    """The two roots this machine's closure hangs off."""
    return [p for p in ("/run/current-system",
                        str(Path.home() / ".local/state/nix/profiles/home-manager"))
            if Path(p).exists()]


def closure_contents():
    """Every package anywhere in the running closure — the dependencies, not
    just the things named in the config. Costs under a tenth of a second.

    Returns (prefix set, {package: installed version}).
    """
    roots = profiles()
    if not roots:
        return set(), {}
    out = subprocess.run(["nix-store", "-q", "--requisites", *roots],
                         capture_output=True, text=True, check=True).stdout

    names = [line.rsplit("/", 1)[-1] for line in out.splitlines()]
    versions = {}
    for name in names:
        stem = name.split("-", 1)[1] if "-" in name else name
        # Split pname from version at the first part that starts with a
        # digit; trailing parts are output suffixes, not version.
        parts = stem.split("-")
        for i, part in enumerate(parts):
            if i and part[:1].isdigit():
                pname = "-".join(parts[:i])
                rest = [p for p in parts[i:] if p not in OUTPUT_SUFFIXES]
                versions.setdefault(pname.lower(), "-".join(rest))
                break
    return prefix_set(names), versions


def closure_stats(roots):
    """How many paths a closure has and what they weigh.

    The two numbers nvd and nh print after a rebuild, read where they read
    them: the nar sizes nix recorded when it took each path in, not the disk.
    A whole system is a fifth of a second, because it is two queries against
    a database and no file is opened.
    """
    live = [str(r) for r in roots if Path(r).exists()]
    if not live:
        return None
    try:
        paths = sorted(set(subprocess.run(
            ["nix-store", "-q", "--requisites", *live],
            check=True, capture_output=True, text=True).stdout.split()))
        if not paths:
            return None
        sizes = subprocess.run(
            ["nix-store", "-q", "--size", *paths],
            check=True, capture_output=True, text=True).stdout.split()
    except (OSError, subprocess.CalledProcessError, ValueError):
        # A number the page would have been nicer for is not worth an error
        # on the page that says the rebuild worked.
        return None
    return len(paths), sum(int(size) for size in sizes)


def human_size(count, sign=False):
    """Binary units, the way nix and nvd report store sizes."""
    value, unit = float(count), "B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024 or unit == "TiB":
            break
        value /= 1024
    mark = "+" if sign and count > 0 else ""
    return f"{mark}{value:.0f} {unit}" if unit == "B" else f"{mark}{value:.2f} {unit}"


def closure_delta(before, after):
    """What the switch did to the store, in one line, or None if unknowable."""
    if not before or not after:
        return None
    (old_paths, old_bytes), (new_paths, new_bytes) = before, after
    if (old_paths, old_bytes) == (new_paths, new_bytes):
        return "The store is unchanged."
    return (f"{old_paths} → {new_paths} paths · "
            f"{human_size(old_bytes)} → {human_size(new_bytes)} "
            f"({human_size(new_bytes - old_bytes, sign=True)})")


VERSION_BUMP = re.compile(r"(\S+)\s*->\s*(\S+)\s*(?:\(#\d+\))?$")


SUBJECT_PKG = re.compile(r"^(?:\[[^\]]*\]\s*)?([A-Za-z0-9][A-Za-z0-9._+-]*)\s*:")


def subject_package(subject):
    """nixpkgs writes `curl: 8.21.0 -> 8.22.0`, sometimes behind a backport
    tag. Returns (package, subject-without-tag) or (None, subject)."""
    body = subject
    if body.startswith("["):
        body = body.split("]", 1)[-1].strip()
    match = SUBJECT_PKG.match(body)
    return (match.group(1) if match else None), body


def dependency_changes(subjects, already_shown):
    """Packages in the closure that a commit subject names, matched by name.

    Version comparison cannot see most of these — a library is nobody's
    top-level package — so the evidence is the commit itself. Heuristic, and
    it says so: it rests on nixpkgs' `package: old -> new` convention and on
    the closure that is installed *now*, not the one being built.

    `already_shown` is what the version diff has already reported, so that
    a package is not listed twice. Everything else comes back, declared or
    not; the caller is what decides which heading it belongs under.
    """
    prefixes, installed = closure_contents()
    found = {}
    for subject in subjects:
        name, body = subject_package(subject)
        if not name or name.lower() in already_shown:
            continue
        if name.lower() not in prefixes:
            continue
        found.setdefault(name, []).append(body)

    entries = []
    for name, bodies in sorted(found.items()):
        entry = {"name": name, "subjects": bodies,
                 "installed": installed.get(name.lower(), "")}
        # A version pair is often right there in the subject. When it is not
        # — a patch or a CVE backport — the installed version is still worth
        # more than repeating the category name.
        for body in bodies:
            bump = VERSION_BUMP.search(body)
            if bump:
                entry["old"], entry["new"] = bump.group(1), bump.group(2)
                break
        entries.append(entry)
    return entries


def package_changes(repo, old_lockfile, new_lockfile, subjects=()):
    """Per category, what actually changes for this machine.

    Two kinds of evidence feed the same four categories: a version pair from
    comparing the two evaluations, and a commit subject for everything that
    comparison cannot see. Which category an entry lands in is decided by
    whether the configs declare it — never by which evidence found it.
    """
    before = package_versions(*store_paths(old_lockfile), repo)
    after = package_versions(*store_paths(new_lockfile), repo)
    launchers = launcher_prefixes()

    def diff(key):
        old = {p["name"]: p["version"] for p in before.get(key, []) if p["version"]}
        new = {p["name"]: p["version"] for p in after.get(key, []) if p["version"]}
        return [{"name": name, "old": old[name], "new": new[name]}
                for name in sorted(old)
                if name in new and old[name] != new[name]]

    changes = {"apps": [], "system": [], "dependencies": [],
               "kernel": diff("kernel"), "graphics": diff("graphics")}

    # Anything carried by one of those two is reported there, and more
    # precisely: under a heading that says what to do about it.
    carried = {p["name"]: key for key in ("kernel", "graphics")
               for p in after.get(key, [])}

    for entry in diff("declared"):
        if entry["name"] in carried:
            continue
        bucket = "apps" if entry["name"].lower() in launchers else "system"
        changes[bucket].append(entry)

    # What the version diff could not speak for. diff() needs a version
    # string on both sides and a change between them, so it is blind to a
    # declared package carrying no version at all (nixos-enter) and to one
    # patched without a bump (gnome-shell). Those are not dependencies —
    # something names them — so route the subject match by where the package
    # comes from, rather than filtering it and losing the news.
    #
    # Most specific first. A driver is named by hardware.graphics or
    # boot.kernelPackages and never by the two package lists, so testing
    # `declared` ahead of `carried` would file every one of them as a
    # dependency and never reach the heading it belongs under.
    declared = {p["name"].lower() for p in after.get("declared", [])}
    reported = {e["name"].lower() for key, _ in CATEGORIES for e in changes[key]}

    for entry in dependency_changes(subjects, reported):
        name = entry["name"]
        if name in carried:
            changes[carried[name]].append(entry)
        elif name.lower() in declared:
            changes["apps" if name.lower() in launchers else "system"].append(entry)
        else:
            changes["dependencies"].append(entry)

    # Not categories — the verdict, measured rather than inferred from the
    # version numbers above, which is what makes it right even when a kernel
    # is rebuilt without its version moving. Two baselines because the window
    # and a notification are asking different things; see update_tier.
    boot = after.get("boot", {})
    changes["reboot"] = reboot_needed(boot)
    changes["reboot_added"] = reboot_needed(boot, "/run/current-system")
    # Kept so that a stored check can redo those two comparisons later: they
    # are the one part of a change set that goes out of date on its own, by
    # the machine being rebooted rather than by anything moving.
    changes["boot"] = boot
    return changes


# -----------------------------------------------------------------------------
# taking effect — nothing, log out, reboot, or build
# -----------------------------------------------------------------------------
# What is left to do, in four answers. Almost everything a pin move brings is
# live the moment the rebuild finishes: a new binary is picked up the next
# time it starts, and switch-to-configuration has already restarted the
# services it had to. Two things outlast the switch — what the session loaded
# at login, and what the kernel came up with. REBUILD is the odd one out: not
# a rebuild that has yet to take effect, but one that never ran. It is spelled
# out rather than BUILD because the rebuild page below calls one derivation's
# worth of work a build.
NOTHING, SESSION, REBOOT, REBUILD = 0, 1, 2, 3

TIER_ACTION = {
    NOTHING: "",
    SESSION: "Log out and back in to finish",
    REBOOT: "Reboot to finish",
    REBUILD: "Rebuild to install",
}
TIER_ICON = {
    NOTHING: "object-select-symbolic",
    SESSION: "system-log-out-symbolic",
    REBOOT: "system-reboot-symbolic",
    REBUILD: "software-update-available-symbolic",
}

# Why the status page is asking. The session tiers are about a rebuild that
# happened; REBUILD is about one that did not.
AFTER_SWITCH = ("An earlier rebuild is waiting on it. Whether the pins "
                "have moved is a separate question.")
TIER_PENDING = {
    SESSION: AFTER_SWITCH,
    REBOOT: AFTER_SWITCH,
    REBUILD: ("The pins on disk have never been built — applying was "
              "interrupted, or npins moved them from a terminal."),
}

STORE_ROOT = re.compile(r"^(/nix/store/[a-z0-9]{32}-[^/]+)")

# The four things in a system generation that only a reboot can swap.
BOOT_PARTS = ("kernel", "initrd", "kernel-modules", "firmware")


def boot_paths(generation):
    """The store paths a generation would boot from.

    Cut back to the store path, because the links do not agree on depth:
    `kernel` points at the bzImage *inside* the kernel while `kernel-modules`
    points at the package itself. versions.nix reports packages, so both
    sides have to be packages to compare at all.
    """
    found = {}
    for part in BOOT_PARTS:
        match = STORE_ROOT.match(str(Path(generation, part).resolve()))
        if match:
            found[part] = match.group(1)
    return found


def reboot_needed(target, baseline="/run/booted-system"):
    """Which boot components `target` has that `baseline` does not.

    Against /run/booted-system, the default, the answer is what a reboot
    would still be for — the only honest record of how this kernel came up,
    and cumulative: a rebuild done last week and never rebooted still counts.
    That is what lets the answer survive the app being closed without any
    bookkeeping of its own.

    Against /run/current-system it is the narrower question of what an
    update adds on top of what is already installed.
    """
    have = boot_paths(baseline)
    if not have:
        return []          # nothing to compare against; do not invent one
    return [part for part in BOOT_PARTS
            if part in have and target.get(part)
            and have[part] != target[part]]


def session_marker():
    """A "you still have to log out" flag with exactly the right lifetime.

    XDG_RUNTIME_DIR is wiped when the user's last session ends, so the flag
    clears itself on logout and survives everything shorter, the app being
    closed and reopened included.

    The alternative was to measure it the way the reboot half is measured, by
    looking for outdated store paths in the maps of running processes. That
    does not work here: home.nix takes one package from a second nixpkgs, and
    its private copy of mesa would read as a stale session forever.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base, "npins-ui-session-stale") if base else None


def mark_session_stale():
    marker = session_marker()
    if marker:
        marker.touch()


def session_stale():
    marker = session_marker()
    return bool(marker and marker.exists())


def change_tier(changes):
    """What will be owed once a change set has been applied.

    The reboot half does not come from the version diff — `changes["reboot"]`
    was measured against the running kernel when the change set was built,
    which also catches a kernel rebuilt at an unchanged version.
    """
    if not changes:
        return NOTHING
    if changes.get("reboot"):
        return REBOOT
    if changes.get("graphics"):
        return SESSION
    return NOTHING


def update_tier(changes):
    """What an update costs by itself, rather than what will be owed after it.

    The two differ once a reboot is already owed. That one belongs in the
    window, where it is the answer to "what do I have to do" — but not in a
    notification, which would then repeat it every time the timer runs, and
    not in a commit message, which is read on days and machines where this
    one's booted kernel means nothing.
    """
    if not changes:
        return NOTHING
    if changes.get("reboot_added"):
        return REBOOT
    if changes.get("graphics"):
        return SESSION
    return NOTHING


# What the running system was built from. /run/current-system is a symlink,
# so this reads as the new value the moment a switch lands.
SYSTEM_VERSION = Path("/run/current-system/nixos-version")


def system_revision():
    """Which nixpkgs commit /run/current-system came from.

    The pin is the Hydra channel release, whose tarball carries
    .version-suffix, so this file ends in the short revision of the very
    commit the lock file names: 26.05.10529.c508844df6c2.
    """
    try:
        label = SYSTEM_VERSION.read_text().strip()
    except OSError:
        return None
    return label.rsplit(".", 1)[-1] or None


def rebuild_owed(lockfile):
    """Whether what the lock file says has never been built.

    This is what a dismissed password dialog leaves behind. The pins are
    written before the rebuild starts, because nixos-rebuild reads them off
    the disk, so cancelling at the prompt keeps the write and loses the
    install; `npins update` in a terminal leaves the same state. Both halves
    of the comparison are read off the machine, so the answer survives the
    window being closed, the way the reboot one does.

    Only nixpkgs is asked about: it is the only pin the system is built
    from, and the system is the half that needs a password and so the half
    that gets abandoned. A home-manager move on its own goes unnoticed here.
    """
    try:
        pinned = pin_revision(read_pins(lockfile).get("nixpkgs", {}))
    except (OSError, ValueError, KeyError):
        return False
    running = system_revision()
    if not pinned or not running:
        return False
    # Channel pins carry the short revision, git pins the full one.
    return not (pinned.startswith(running) or running.startswith(pinned))


def pending_tier(lockfile=None):
    """What is owed right now, with nothing pending to apply.

    A rebuild outranks the other two: logging out of or rebooting into a
    system that was never built finishes nothing.
    """
    if lockfile and rebuild_owed(lockfile):
        return REBUILD
    if reboot_needed(boot_paths("/run/current-system")):
        return REBOOT
    return SESSION if session_stale() else NOTHING


# gnome-session rather than logind, for both of these. Its Reboot() puts up
# the confirmation everyone expects from the system menu and lets an app with
# unsaved work inhibit it; calling logind directly would walk past both.
#
# CanReboot() is not asked first. It answers with a uint whose values this
# code has no way to pin down, and guessing at an enum to grey out a button
# is worse than letting the call fail and saying why.
SESSION_MANAGER = ("org.gnome.SessionManager", "/org/gnome/SessionManager",
                   "org.gnome.SessionManager")

# Logout(0) is the mode that asks; 1 and 2 skip the dialog and force it.
LOGOUT_ASKING = 0


def end_session(tier):
    """Hand the session manager what the tier says is left to do."""
    method, args = (("Reboot", None) if tier == REBOOT
                    else ("Logout", GLib.Variant("(u)", (LOGOUT_ASKING,))))
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync(*SESSION_MANAGER, method, args, None,
                  Gio.DBusCallFlags.NONE, -1, None)


# -----------------------------------------------------------------------------
# a check, and what the last one found
# -----------------------------------------------------------------------------
def survey(repo, lockfile, workdir):
    """Everything a check finds: which pins moved, how far, and what the two
    together change for this machine.

    One function for both callers, the window and the timer, because they
    now share the result — and two copies of this loop would quietly grow
    apart into two shapes of it.
    """
    updates, text = probe_updates(lockfile, workdir)
    detail = {"subjects": []}
    if not updates:
        return updates, text, detail

    # Kept per pin while gathering, because how far a pin moved is reported
    # for every pin while its commits may only be matched against the
    # closure for some; see CLOSURE_PINS.
    by_pin = {}
    for update in updates:
        if not (update["repo"] and update["old_rev"] and update["new_rev"]):
            continue
        try:
            result = compare(update["repo"], update["old_rev"], update["new_rev"])
            detail[update["name"]] = {
                "behind": result["total"],
                "age": commit_age(update["repo"], update["new_rev"]),
            }
            by_pin[update["name"]] = result["subjects"]
        except (urllib.error.URLError, KeyError, ValueError):
            # The forge is a nicety; the pin diff already stands.
            pass

    # Scoped once, here: the changelog shown per package reads from the same
    # list the dependency match does.
    detail["subjects"] = closure_subjects(by_pin)

    probed = Path(workdir) / "sources.json"
    try:
        detail["changes"] = package_changes(
            repo, lockfile, probed, detail["subjects"])
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        # A lock file without the configs next to it still has a usable pin
        # diff; only the "affects you" part is lost.
        detail["changes_error"] = describe_error(error)

    # Last, and allowed to fail quietly: it is the most expensive question
    # asked here and the least load-bearing answer. Everything above still
    # stands without it — the window simply does not say how big this is.
    try:
        detail["download"] = download_estimate(*store_paths(probed), repo)
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, ValueError):
        pass
    return updates, text, detail


# The timer runs the same check every six hours and used to throw the answer
# away, so the window opened blank and fetched it again. It is written down
# instead. Only the parts that cost network are in here: the nix evaluation
# has its own cache already, keyed by the pins it ran against.
STATE = CACHE / "last-check.json"

# A check running outside the window — the timer's — is something the window
# has to be able to see, or its own Check button would start a second one
# racing the first for this same file, and one of the two answers would be
# thrown away. The marker is renamed into place already locked, so it never
# shows up unheld; and the lock is what a killed check cannot leave behind,
# because the kernel drops it. A file nobody holds therefore reads as free.
RUNNING = CACHE / "check.lock"


@contextlib.contextmanager
def marker():
    """Hold the file that says a check is running, for as long as it runs."""
    fd, tmp = None, CACHE / "check.lock.new"
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.replace(tmp, RUNNING)
    except OSError:
        # A marker that will not be written is a hint the window does not
        # get, not a reason to skip the check.
        if fd is not None:
            os.close(fd)
            fd = None
        with contextlib.suppress(OSError):
            tmp.unlink()
    try:
        yield
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                RUNNING.unlink()
            os.close(fd)


def check_running():
    """Whether a check is in flight somewhere other than this process."""
    try:
        fd = os.open(RUNNING, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


# How long the stored answer counts as current — the timer's own interval
# from home.nix, because that is the promise being leaned on. Past it the
# state is not stale by a little, it is unattended, and the window goes and
# looks for itself.
FRESH_FOR = 6 * 3600


def lockfile_digest(lockfile):
    """What the stored answer was computed from. The pins moving underneath
    it — an apply, an edit, a checkout — is what makes it wrong rather than
    merely old."""
    try:
        return hashlib.sha256(Path(lockfile).read_bytes()).hexdigest()
    except OSError:
        return ""


def save_check(repo, lockfile, updates, text, detail):
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".json.new")
        tmp.write_text(json.dumps({
            "stamp": int(time.time()), "repo": str(repo),
            "digest": lockfile_digest(lockfile),
            "updates": updates, "text": text, "detail": detail,
        }))
        os.replace(tmp, STATE)
    except OSError:
        pass          # a cache that will not be written is not worth an error


def load_check(repo, lockfile):
    """The last check, if it still describes this repo's pins.

    Returns (stamp, updates, probed lock file, detail), or None. The stamp
    rather than an age because the window also uses it to tell a check it
    wrote itself from one that landed underneath it.
    """
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None
    if (state.get("repo") != str(repo)
            or state.get("digest") != lockfile_digest(lockfile)):
        return None

    detail = state.get("detail", {})
    changes = detail.get("changes")
    if changes is not None:
        # Redone rather than restored: these were measured against the
        # running system, which may have been rebooted since.
        boot = changes.get("boot", {})
        changes["reboot"] = reboot_needed(boot)
        changes["reboot_added"] = reboot_needed(boot, "/run/current-system")

    return (state.get("stamp", 0), state.get("updates", []),
            state.get("text"), detail)


def ago(seconds):
    """A rough age, for a line that only has to say recent or not."""
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds / size)
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"


# -----------------------------------------------------------------------------
# rebuild — actually installing what the pins point at
# -----------------------------------------------------------------------------
# nix --log-format internal-json emits "@nix {...}" on stderr, and everything
# this page shows comes out of it. Activities open, carry results, and stop;
# the id is the thread that ties the three together, and `parent` nests them.
# The types that carry something worth showing:
#
#   104 builds        opened once, holds the [done, expected] build counter
#   103 copy-paths    the same for downloads
#   105 build         one per derivation, fields[0] is the .drv being built
#   108 substitute    one per path fetched, with 100 and 101 nested under it
#   100 copy-path     fields[0] the path, fields[1] where from, unpacked bytes
#   101 file-transfer fields[0] the URL, and the bytes actually off the wire
#
# and the results that hang off an activity's id:
#
#   101 build-log-line  what the builder printed — the only place a compile
#                       error exists before nix summarises it
#   104 set-phase       unpackPhase, configurePhase, buildPhase, …
#   105 progress        [done, expected, running, failed]
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
# whole reason the rows above exist.
RAW_LINES = 2000

# Before it builds anything, nix says what it is about to build, as a heading
# and one indented store path per line. That listing is the build plan, and
# it is the only place the plan exists — the activity stream announces each
# build as it starts and never says what is still to come.
PLAN_HEADING = re.compile(r"^(?:this|these \d+) derivations? will be built:")
PLAN_ENTRY = re.compile(r"^\s+(/nix/store/\S+\.drv)$")

# What a node in the build tree can be. Planned is what the listing above
# hands over; the rest the activity stream moves it through.
PLANNED, RUNNING, DONE, FAILED = "planned", "running", "done", "failed"

# The tree is drawn with the same box characters nom uses, in a column of
# their own so the titles still line up as Adwaita titles.
TREE_LAST, TREE_MORE, TREE_PIPE, TREE_GAP = "└─", "├─", "│ ", "  "

# A tree taller than this is not a tree anyone reads. nom cuts to the height
# of the terminal; this is a window that scrolls, so the cut is only a guard
# against a rebuild that plans hundreds of derivations.
TREE_ROWS = 80

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
        if activity and activity.kind == BUILD and activity.log:
            self.recent[activity.name] = list(activity.log)
            while len(self.recent) > RECENT:
                self.recent.popitem(last=False)

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

    def tree(self):
        """The forest flattened into rows, each carrying its own indent."""
        rows = []

        def draw(node, prefix, last, depth):
            if len(rows) >= TREE_ROWS:
                return
            drv, kids = node
            activity = self.by_drv.get(drv)
            lead = "" if not depth else prefix + (TREE_LAST if last
                                                  else TREE_MORE)
            rows.append({
                "key": ("node", drv),
                "kind": BUILD,
                "lead": lead,
                "name": package_name(drv),
                "state": self.planned.get(drv, PLANNED),
                "waiting": self.waiting_on(drv),
                "detail": activity.detail if activity else "",
                "started": activity.started if activity else 0,
                "log": list(activity.log) if activity else [],
            })
            below = prefix + ("" if not depth else
                              TREE_GAP if last else TREE_PIPE)
            for index, kid in enumerate(kids):
                draw(kid, below, index == len(kids) - 1, depth + 1)

        forest = self.forest()
        for index, node in enumerate(forest):
            draw(node, "", index == len(forest) - 1, 0)
        return rows

    # -- read from the main loop ----------------------------------------------
    def snapshot(self):
        """Everything the page draws, taken at one instant, or None when
        nothing has happened since the last one."""
        with self.lock:
            if not self.dirty:
                return None
            self.dirty = False
            tree = self.tree()
            # Downloads have no graph — nothing is waiting for one, they are
            # just arriving — so they stay a list under the tree, the way nom
            # keeps them to their own column. When there is no tree at all,
            # builds join them: a step that plans nothing still has something
            # to show while it runs.
            wanted = (DOWNLOAD,) if tree else (BUILD, DOWNLOAD)
            rows = sorted(
                ({"key": (a.kind, a.name), "kind": a.kind, "name": a.name,
                  "detail": a.detail, "done": a.done, "expected": a.expected,
                  "started": a.started, "log": list(a.log)}
                 for a in self.live.values() if a.kind in wanted),
                key=lambda row: row["started"])
            pending, self.pending = self.pending, []
            return {"tree": tree, "rows": rows, "problems": list(self.problems),
                    "fraction": self.fraction(), "summary": self.summary(),
                    "raw": pending}

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


# -----------------------------------------------------------------------------
# git
# -----------------------------------------------------------------------------
def entry_detail(entry):
    """What an entry changed, in words.

    Not every entry has a version pair. One that the version diff could not
    speak for is here because a commit subject named it — a package carrying
    no version, or one patched without a bump — and for those the commits
    are the whole of the evidence. The window says this in a subtitle; the
    commit body says it in the same order for the same reason.
    """
    if entry.get("old"):
        return f"{entry['old']} -> {entry['new']}"
    if entry.get("installed"):
        return f"{entry['installed']} installed, patched"
    count = len(entry.get("subjects", []))
    return f"{count} commit{'' if count == 1 else 's'}"


def table(rows):
    """Name and detail per line, names padded to one column."""
    width = max(len(name) for name, _ in rows)
    return "\n".join(f"  {name:<{width}}  {detail}" for name, detail in rows)


def change_blocks(changes):
    """What this pin move does to the machine, for the commit body.

    Everything the config names gets its own line — a year on, that list is
    the reason to reach for this commit at all. Dependencies are the one
    exception: they run to dozens of packages nobody asked for, and a name
    without context is no help, so they get the same one-line summary the
    window shows.
    """
    blocks = []
    for key, label in CATEGORIES:
        entries = changes.get(key, [])
        if not entries:
            continue
        if key == "dependencies":
            cves = sum(1 for e in entries
                       if any("cve-" in s.lower() for s in e.get("subjects", [])))
            line = f"{len(entries)} package{'' if len(entries) == 1 else 's'}"
            if cves:
                line += f", {cves} with a CVE fix"
            blocks.append(f"{label}:\n  {line}")
            continue
        blocks.append(f"{label}:\n" + table(
            [(e["name"], entry_detail(e)) for e in entries]))

    action = TIER_ACTION[update_tier(changes)]
    if action:
        blocks.append(f"{action}.")
    return blocks


def commit_message(updates, changes=None):
    names = [u["name"] for u in updates]
    if len(names) == 1:
        subject = f"npins: update {names[0]}"
    elif len(names) == 2:
        subject = f"npins: update {names[0]} and {names[1]}"
    else:
        subject = f"npins: update {len(names)} pins"
    if len(subject) > 60:
        subject = f"npins: update {len(names)} pins"

    # The pins moved and that is the diff; what follows is what the diff
    # does, which the diff itself cannot show.
    width = max(len(n) for n in names)
    body = ["\n".join(f"{u['name']:<{width}}  {u['old']} -> {u['new']}"
                      for u in updates)]
    if changes:
        body += change_blocks(changes)
    return f"{subject}\n\n" + "\n\n".join(body) + "\n"


def commit_lockfile(repo, updates, changes=None):
    """Commit the lock file and nothing else.

    The pathspec is not optional. This repo regularly carries unrelated
    half-finished work in the tree, and a bare `git commit -a` would sweep
    it into a pin bump. Passing the path commits that file's worktree
    content and leaves both the index and every other file alone.
    """
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", commit_message(updates, changes),
         "--", LOCKFILE],
        check=True, capture_output=True, text=True,
    )


def describe_error(error):
    if isinstance(error, subprocess.CalledProcessError):
        detail = (error.stderr or error.stdout or "").strip()
        return detail or f"{error.cmd[0]} exited with {error.returncode}"
    if isinstance(error, urllib.error.URLError):
        return f"Cannot reach the forge: {error.reason}"
    return f"{type(error).__name__}: {error}"


# -----------------------------------------------------------------------------
# headless check, for the background timer
# -----------------------------------------------------------------------------
SYSTEM_NOISE_FLOOR = 20
NOUNS = {
    "dependencies": ("dependency", "dependencies"),
    "apps": ("app", "apps"),
    "system": ("system package", "system packages"),
    "kernel": ("kernel package", "kernel packages"),
    "graphics": ("graphics package", "graphics packages"),
}


def worth_notifying(changes):
    """Whether a pin move is worth interrupting someone over.

    A stable channel moves base packages constantly and none of it is news.
    An app or a driver changing is; a system bump only once enough of them
    pile up that the next rebuild is going to be a big one.
    """
    counts = {key: len(changes.get(key, [])) for key, _ in CATEGORIES}
    parts = [
        f"{n} {NOUNS[key][0] if n == 1 else NOUNS[key][1]}"
        for key, _ in CATEGORIES
        if (n := counts[key])
    ]
    # A security fix in a library never clears the count thresholds — it is
    # one dependency among dozens — but it is exactly the thing not to miss.
    # Counted in packages, not commits — two commits fixing one library is
    # one thing to know about, and the window counts it the same way.
    # Every category, not just Dependencies: a subject-matched entry is
    # filed by whether the configs declare it, and a CVE fix can land in a
    # declared package just as easily.
    cves = sum(1 for key, _ in CATEGORIES for entry in changes.get(key, [])
               if any("cve-" in s.lower() for s in entry.get("subjects", [])))
    if cves:
        parts.append(f"{cves} with a CVE fix")

    worth = (counts["apps"] or counts["kernel"] or counts["graphics"] or cves
             or counts["system"] >= SYSTEM_NOISE_FLOOR)
    summary = ", ".join(parts) or "nothing you installed"

    # An update that ends in a reboot is worth saying so up front: that is
    # the one the reader might want to postpone rather than take now.
    action = TIER_ACTION[update_tier(changes)]
    if action:
        summary += f" · {action.lower()}"
        worth = True
    return bool(worth), summary


def run_check(repo):
    repo = Path(repo)
    lockfile = repo / LOCKFILE
    with tempfile.TemporaryDirectory() as workdir, marker():
        # The commit range is what surfaces dependency and CVE changes, so
        # the headless check pays for it too. A forge that is down costs the
        # dependency half, not the whole answer.
        updates, text, detail = survey(repo, lockfile, workdir)

        # Written down whether or not anything moved: "all current" is an
        # answer the window can open on too, and is the common case.
        save_check(repo, lockfile, updates, text, detail)

        if not updates:
            # Current pins and an installed system are different claims.
            print("All pins current, but not installed — a rebuild is owed."
                  if rebuild_owed(lockfile) else "All pins current.")
            return 0
        if "changes" not in detail:
            # Without the version diff there is no way to judge, so say the
            # pins moved and let the user decide.
            for update in updates:
                print(f"{update['name']}: {update['old']} -> {update['new']}")
            return 10

        worth, summary = worth_notifying(detail["changes"])
        print(summary)
        return 10 if worth else 0


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
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


class ActivityRow(Adw.ExpanderRow):
    """One node of the build tree, or one download, updated in place.

    In place, because the page redraws four times a second and an expander
    the user opened to watch a compile has to survive the next redraw.
    """

    def __init__(self, row):
        super().__init__(title=row["name"])
        # The tree lines get a column of their own instead of going into the
        # title, so the titles still line up the way Adwaita titles do while
        # the box characters line up the way box characters have to.
        self.lead = Gtk.Label(label="", valign=Gtk.Align.CENTER,
                              css_classes=["monospace", "dim-label"])
        self.add_prefix(self.lead)
        self.icon = Gtk.Image()
        self.add_prefix(self.icon)
        self.output = output_label("")
        self.add_row(self.output)

    def update(self, row):
        lead = row.get("lead", "")
        self.lead.set_label(lead)
        self.lead.set_visible(bool(lead))

        state = row.get("state")
        self.icon.set_from_icon_name(
            STATE_ICON[state] if state else "folder-download-symbolic")
        if state == FAILED:
            self.icon.add_css_class("error")
        else:
            self.icon.remove_css_class("error")

        self.set_subtitle(self.describe(row))
        # A download has no output, and a build has none until it starts
        # talking; either way an empty expander should say so rather than
        # open onto nothing.
        self.output.set_label("\n".join(row["log"]) or "No output yet")

    @staticmethod
    def describe(row):
        """The line under the name — what this node is doing, or waiting for."""
        state = row.get("state")
        if state == PLANNED:
            waiting = row.get("waiting", 0)
            return f"waiting for {waiting}" if waiting else "queued"
        if state == DONE:
            return "built"
        if state == FAILED:
            return "failed"

        parts = [row["detail"]] if row.get("detail") else []
        if row.get("expected"):
            parts.append(f"{human_size(row['done'])} / {human_size(row['expected'])}")
        if row.get("started"):
            elapsed = time.monotonic() - row["started"]
            if elapsed >= 2:
                parts.append(clock(elapsed))
        return " · ".join(parts)


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


class Window(Adw.ApplicationWindow):
    def __init__(self, app, repo):
        super().__init__(application=app, title="npins",
                         default_width=820, default_height=680)
        self.repo = Path(repo)
        self.lockfile = self.repo / LOCKFILE
        self.workdir = Path(tempfile.mkdtemp(prefix="npins-ui-"))
        self.pending_text = None
        self.updates = []
        self.detail = {}
        # When the check on screen was made, so a state file written while
        # the window is open can be told from the one it already shows.
        self.state_stamp = 0
        self.working = False
        self._banner_timer = 0
        self.proc = None
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

        menu = Gio.Menu()
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
        # The rebuild page: a progress bar fed by nix's own counters, over a
        # list of what it is counting. The list is the point — the log this
        # replaced could show the same events, but only as one stream of
        # them, with a dozen parallel builds shredded into each other.
        self.progress = Gtk.ProgressBar(show_text=True, margin_top=12,
                                        margin_start=12, margin_end=12)
        self.activity = boxed_list()
        self.problems = boxed_list()
        self.problems_heading = section("Problems")
        self.rows = {}
        self.tree_shape = ()
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
        self.rebuild_body.append(self.activity)
        self.rebuild_body.append(self.problems_heading)
        self.rebuild_body.append(self.problems)
        self.rebuild_body.append(section("Details"))
        self.rebuild_body.append(log_group)
        rebuild_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        rebuild_page.append(self.progress)
        rebuild_page.append(Gtk.ScrolledWindow(
            child=Adw.Clamp(child=self.rebuild_body, maximum_size=700),
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True,
        ))

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
        header.pack_end(self.spinner)

        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        view.add_top_bar(self.banner)

        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        for name, handler in (
            ("apply-only", lambda *_: self.apply(commit=False, rebuild=True)),
            ("write-only", lambda *_: self.apply(commit=True, rebuild=False)),
            ("sources", lambda *_: self.sources()),
            ("about", lambda *_: self.about()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        # Open on what the timer already found rather than on nothing. It ran
        # the same check this window would, so repeating it on every launch
        # was two fetches for one answer.
        restored = load_check(self.repo, self.lockfile)
        if restored:
            age = self.adopt(restored)

        self.render()
        self.sync_apply()

        if not restored or age > FRESH_FOR:
            # Nothing kept, or kept longer than the timer promises to keep it
            # current. Either way the answer on screen is not one to stand on.
            self.check()
        elif self.updates:
            self.say(f"{self.verdict()} · checked {ago(age)}")
        else:
            self.show_current(age)

        self.watch_state()

    # -- helpers --------------------------------------------------------------
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def offer(self, tier):
        """Put what is owed on the status page as something to press."""
        self.finish_tier = tier
        self.finish_button.set_visible(tier != NOTHING)
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
        if message:
            self.say(message, seconds=0)

    def open_url(self, url):
        Gtk.UriLauncher(uri=url).launch(self, None, None, None)

    def sync_apply(self, busy=False):
        """There is nothing to apply until a check finds something, so the
        button is absent rather than present-and-greyed."""
        ready = bool(self.pending_text)
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
        self.check_watch = Gio.File.new_for_path(str(RUNNING)).monitor_file(
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
        busy = self.working or self.proc is not None
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
        if self.working or self.proc:
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

        def work():
            found = survey(self.repo, self.lockfile, self.workdir)
            save_check(self.repo, self.lockfile, *found)
            return found

        self.run_async(work, self.checked)

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
        self.steps = rebuild_steps(self.repo)
        self.logbuf.set_text("")
        self.progress.set_fraction(0)
        self.carried = []
        # Measured before the switch, because afterwards there is nothing
        # left that remembers what the store weighed.
        self.closure_before = closure_stats(profiles())
        self.stack.set_visible_child_name("rebuild")
        self.check_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.back_button.set_visible(False)
        self.ticker = GLib.timeout_add(self.TICK, self.tick)
        self.run_step(0)

    def run_step(self, index):
        if index >= len(self.steps):
            self.rebuild_done(None)
            return

        label, command = self.steps[index]
        self.step_index = index
        self.say(f"{label}…", seconds=0)
        self.progress.set_fraction(0)
        self.progress.set_text(label)
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

    def clear_activity(self):
        for widget in self.rows.values():
            self.activity.remove(widget)
        self.rows = {}
        self.tree_shape = ()
        self.activity.set_visible(False)

    def draw_rebuild(self, snapshot):
        """Bring the page up to date with one instant of the stream."""
        if snapshot["fraction"] is not None:
            self.progress.set_fraction(min(snapshot["fraction"], 1.0))
        label = self.steps[self.step_index][0] if self.steps else ""
        summary = snapshot["summary"]
        self.progress.set_text(f"{label} — {summary}" if summary else label)

        # The tree arrives whole, a second or so into the step, when the
        # edges have been worked out. A list box cannot be reordered without
        # taking it apart, so when the shape changes it is taken apart once,
        # here, rather than drifting out of order for the rest of the build.
        shape = tuple(row["key"] for row in snapshot["tree"])
        if shape != self.tree_shape:
            self.clear_activity()
            self.tree_shape = shape

        # Rows are kept and updated rather than rebuilt, so that an expander
        # opened to watch a compile is not closed again a quarter-second later.
        wanted = {row["key"]: row for row in snapshot["tree"] + snapshot["rows"]}
        for key in [k for k in self.rows if k not in wanted]:
            self.activity.remove(self.rows.pop(key))
        for key, row in wanted.items():
            widget = self.rows.get(key)
            if widget is None:
                widget = ActivityRow(row)
                self.rows[key] = widget
                self.activity.append(widget)
            widget.update(row)
        self.activity.set_visible(bool(self.rows))

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
        self.progress.set_fraction(1.0)
        self.run_step(index + 1)
        return GLib.SOURCE_REMOVE

    def cancel_rebuild(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def leave_rebuild(self):
        """Off the failed rebuild's page and back to the pins."""
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
        self.clear_activity()
        self.progress.set_fraction(0)
        self.progress.set_text(str(error))
        self.say(f"{error} What went wrong is below.", seconds=0)
        self.back_button.set_visible(True)
        if not self.problem_count:
            # nix said nothing a row was made of — a step that died before
            # it started, or was killed. The full output is all there is.
            self.logrow.set_expanded(True)

    def rebuild_done(self, error, cancelled=False):
        self.proc = None
        self.cancelled = False
        self.cancel_button.set_visible(False)
        if self.ticker:
            GLib.source_remove(self.ticker)
            self.ticker = 0
        self.sync_check()

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


class Application(Adw.Application):
    def __init__(self, repo):
        # NON_UNIQUE because the repo is per-process state: with the default
        # single-instance behaviour a second launch just raises the first
        # window and drops its repo argument on the floor.
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.repo = repo

    def do_activate(self):
        window = self.props.active_window or Window(self, self.repo)
        window.present()


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    repo = Path(args[0] if args
                else os.environ.get("NPINS_UI_REPO", Path.home() / "nixcfg"))
    if not (repo / LOCKFILE).is_file():
        print(f"npins-ui: no {LOCKFILE} under {repo}", file=sys.stderr)
        return 1
    if "--check" in sys.argv[1:]:
        return run_check(repo)
    return Application(repo).run([])


if __name__ == "__main__":
    sys.exit(main())
