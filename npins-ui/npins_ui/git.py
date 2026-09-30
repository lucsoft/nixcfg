"""Writing the move down.

One commit for a pin move, with what it changed in the body. The subject
follows the same nixpkgs convention the rest of this repository does.
"""

import subprocess

from .paths import CATEGORIES, LOCKFILE
from .effect import TIER_ACTION, update_tier


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
