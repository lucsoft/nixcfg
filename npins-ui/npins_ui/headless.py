"""The check the background timer runs.

No window, no Gtk: this path is reached without importing any of it, which
is the point of it being its own module. Exits 10 when there is something
worth a notification, and home.nix turns that into one.
"""

import tempfile
from pathlib import Path

from .paths import CATEGORIES, LOCKFILE
from .effect import rebuild_owed, TIER_ACTION, update_tier
from .check import marker, save_check, survey


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
