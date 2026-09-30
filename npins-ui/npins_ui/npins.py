"""Talking to npins itself.

Everything that reads npins/sources.json or shells out to the npins CLI.
`probe_updates` is the important one: it works on a copy of the lock file in
a temporary directory, so asking what would move never moves anything.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


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
