"""How far behind a pin is, and the commits in between.

The unauthenticated GitHub compare API. It is the cheap half of a check —
one request per moved pin — and the half that can fail on its own without
costing the rest of the answer.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone


def github(path):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "npins-ui"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def compare(repo, old_rev, new_rev, report=lambda text: None):
    """Commit subjects between two revisions, and how many there are.

    The compare endpoint caps its commits array at 250, so a range wider
    than that has to be paged or the changelog silently loses its tail.

    The first page says how many there are in total, which makes this the
    one step of a check that can say how far along it is rather than only
    what it is doing.
    """
    first = github(f"/repos/{repo}/compare/{old_rev}...{new_rev}?per_page=250")
    total = first.get("total_commits", 0)
    commits = list(first.get("commits", []))
    page = 2
    while len(commits) < total and page <= 8:
        report(f"Reading {len(commits)} of {total} commits…")
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
