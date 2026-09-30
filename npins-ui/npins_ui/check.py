"""A check, and what the last one found.

survey() is the whole of a check, and the window and the background timer
both call it — two copies of that loop would quietly grow apart into two
shapes of it. What it finds is written to CACHE so the other one can open on
it instead of repeating the work.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from .paths import CACHE
from .errors import describe_error
from .npins import probe_updates
from .forge import closure_subjects, commit_age, compare
from .effect import reboot_needed
from .evaluate import download_estimate, package_changes, store_paths


def survey(repo, lockfile, workdir, report=lambda text: None):
    """Everything a check finds: which pins moved, how far, and what the two
    together change for this machine.

    One function for both callers, the window and the timer, because they
    now share the result — and two copies of this loop would quietly grow
    apart into two shapes of it.

    `report` is handed a line per step. A check that finds something runs
    for the better part of a minute — the forge, two evaluations and a
    question to the cache — and a window that says only "checking" for all
    of it is a window that looks stuck. The timer passes nothing and the
    lines go nowhere.
    """
    report("Looking for moved pins…")
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
        report(f"Reading what moved in {update['name']}…")
        try:
            result = compare(update["repo"], update["old_rev"], update["new_rev"],
                             report=report)
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
    report("Working out what changes for you…")
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
    report("Asking the cache how big this is…")
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
# Named for the file rather than the state: RUNNING is also what a
# derivation is doing while it builds, and the rebuild page owns that word.
CHECK_LOCK = CACHE / "check.lock"


@contextlib.contextmanager
def marker():
    """Hold the file that says a check is running, for as long as it runs."""
    fd, tmp = None, CACHE / "check.lock.new"
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.replace(tmp, CHECK_LOCK)
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
                CHECK_LOCK.unlink()
            os.close(fd)


def check_running():
    """Whether a check is in flight somewhere other than this process."""
    try:
        fd = os.open(CHECK_LOCK, os.O_RDONLY)
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


APPLIED = CACHE / "last-apply.json"


def save_apply(record):
    """Keep the rebuild that just ran, so it can be opened again.

    One record, replaced each time: this is the page from the last apply,
    not a history. It lives in the cache because it is a copy of something
    that already happened — losing it costs a page nobody can reprint, but
    nothing that was true stops being true.
    """
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = APPLIED.with_suffix(".json.new")
        tmp.write_text(json.dumps(record))
        os.replace(tmp, APPLIED)
    except OSError:
        pass          # a cache that will not be written is not worth an error


def applied_ago(when):
    """How long ago a record was written, in the words the window uses for
    the last check."""
    try:
        moment = datetime.fromisoformat(when)
    except (TypeError, ValueError):
        return "at some point"
    return ago((datetime.now(timezone.utc) - moment).total_seconds())


def load_apply():
    """The last rebuild, or None.

    json has no tuples: the keys the views index rows by and the columns the
    connector lines read come back as lists, and a list cannot be a dict
    key. They are put back on the way in, once, rather than guarded against
    everywhere they are used.
    """
    try:
        record = json.loads(APPLIED.read_text())
    except (OSError, ValueError):
        return None

    def revive(row):
        row["key"] = tuple(row["key"])
        if "pipes" in row:
            row["pipes"] = tuple(row["pipes"])
        for kid in row.get("kids", ()):
            revive(kid)

    for step in record.get("steps", []):
        for row in step.get("plan", []) + step.get("downloads", []):
            revive(row)
    return record


def ago(seconds):
    """A rough age, for a line that only has to say recent or not."""
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds / size)
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"
