"""The plan, as rows.

Between the stream and the two views that draw it. Everything here works on
plain dicts: the stream does not know a widget exists, and neither view
reads the stream.
"""

import time

from ..evaluate import human_size
from ..stream import BUILD, DONE, DOWNLOAD, FAILED, PLANNED, RUNNING
from .common import clock


def describe(row):
    """The line under a name: what this node is doing, or waiting for."""
    state = row.get("state")
    if state == PLANNED:
        waiting = row.get("waiting", 0)
        return f"waiting for {waiting}" if waiting else "queued"
    if state == DONE:
        if row.get("kind") != DOWNLOAD:
            return "built"
        size = human_size(row["expected"]) if row.get("expected") else ""
        return f"{size} downloaded".strip()
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


def walk_plan(nodes):
    for node in nodes:
        yield node
        yield from walk_plan(node["kids"])


def relayout(roots):
    """Re-stamp depth, last and pipes over a tree that has been rearranged.

    The stream works these out for the plan it knows about. The page hangs
    that plan under nodes of its own — the run, and a node per step — and
    the connector lines have to be told about the new shape.
    """
    def stamp(node, depth, last, pipes):
        node["depth"], node["last"], node["pipes"] = depth, last, pipes
        below = pipes + ((not last,) if depth else ())
        kids = node["kids"]
        for index, kid in enumerate(kids):
            stamp(kid, depth + 1, index == len(kids) - 1, below)

    for index, root in enumerate(roots):
        stamp(root, 0, index == len(roots) - 1, ())
    return roots


def download_group(index, rows):
    """Every download of one step, under one node.

    Downloads have no graph of their own — nothing waits for one, it just
    arrives — so they hang off the step that fetched them as a single
    branch rather than being scattered through a plan they are not part of.
    """
    arriving = [row for row in rows if row["state"] == RUNNING]
    return {
        "key": ("downloads", index),
        "kind": DOWNLOAD,
        "name": f"{len(rows)} download{'' if len(rows) == 1 else 's'}",
        "state": RUNNING if arriving else DONE,
        "waiting": len(arriving),
        "detail": "",
        "done": sum(row["done"] for row in rows),
        "expected": sum(row["expected"] for row in rows),
        "fraction": None,
        "started": min(row["started"] for row in rows),
        "log": [],
        "kids": rows,
    }


def compose(steps, started=0):
    """The whole rebuild as one tree.

    The run is the root, each step is a node under it, and each step's plan
    hangs under that. It is the same thing the progress bar used to say from
    outside the page — how far along, out of how much — except that now it
    is a node like everything else it is counting, and the two halves of a
    rebuild are on screen together instead of one replacing the other.
    """
    nodes = []
    for index, step in enumerate(steps):
        kids = list(step["plan"])
        if step.get("downloads"):
            kids.append(download_group(index, step["downloads"]))
        outstanding = [row for row in walk_plan(kids) if row["state"] != DONE]
        if any(row["state"] == FAILED for row in walk_plan(kids)):
            state = FAILED
        elif step["fraction"] is None:
            state = PLANNED
        elif step.get("running"):
            state = RUNNING
        else:
            state = DONE
        nodes.append({
            "key": ("step", index),
            "kind": BUILD,
            "name": step["label"],
            "state": state,
            "waiting": len(outstanding),
            "detail": step["summary"],
            "fraction": step["fraction"],
            "started": step.get("started", 0),
            "log": step.get("tail", []),
            "kids": kids,
        })

    done = sum(1 for node in nodes if node["state"] == DONE)
    live = next((node for node in nodes if node["state"] == RUNNING), None)
    if any(node["state"] == FAILED for node in nodes):
        state = FAILED
    elif nodes and done == len(nodes):
        state = DONE
    else:
        state = RUNNING
    root = {
        "key": ("rebuild",),
        "kind": BUILD,
        "name": "Rebuild",
        "state": state,
        "waiting": sum(1 for node in nodes if node["state"] != DONE),
        "detail": (live or nodes[-1] if nodes else {}).get("detail", ""),
        # Steps are the only thing the run itself can count: what is inside
        # them nix counts per invocation, and those counters start over.
        "fraction": ((done + (live["fraction"] or 0 if live else 0))
                     / len(nodes)) if nodes else None,
        "started": started,
        "log": [],
        "kids": nodes,
    }
    return relayout([root])
