"""Which of my packages a pin move changes.

The expensive half of a check. versions.nix and sizes.nix are evaluated
against the old pins and the new ones and the two answers are diffed; every
result is cached under CACHE keyed by the pins, the configs and the
expression, because the evaluation costs far more than the comparison.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .paths import CACHE, CATEGORIES, eval_expression, sizes_expression
from .npins import npins
from .effect import reboot_needed


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
