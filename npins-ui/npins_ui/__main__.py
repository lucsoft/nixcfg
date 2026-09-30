"""Which of the two things this program is.

Both imports are deferred on purpose. --check runs on a six-hour timer and
wants the network and nix, not a toolkit; importing app at the top would
load Gtk, Adw, Gdk, Pango and cairo for a run that never draws anything.
"""

import os
import sys
from pathlib import Path

from .paths import LOCKFILE


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    repo = Path(args[0] if args
                else os.environ.get("NPINS_UI_REPO", Path.home() / "nixcfg"))
    if not (repo / LOCKFILE).is_file():
        print(f"npins-ui: no {LOCKFILE} under {repo}", file=sys.stderr)
        return 1
    if "--check" in sys.argv[1:]:
        from .headless import run_check
        return run_check(repo)
    from .app import Application
    return Application(repo).run([])


if __name__ == "__main__":
    sys.exit(main())
