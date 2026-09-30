"""Where things are, and what the categories are called.

The bottom of the package: everything imports this and it imports nothing
back.
"""

import os
from pathlib import Path

from gi.repository import GLib

APP_ID = "de.lucsoft.NpinsUi"
LOCKFILE = "npins/sources.json"
CATEGORIES = [("apps", "Apps"), ("kernel", "Kernel and firmware"),
              ("graphics", "Graphics and fonts"), ("system", "System"),
              ("dependencies", "Dependencies")]
CACHE = Path(GLib.get_user_cache_dir()) / "npins-ui"


def eval_expression():
    """Where versions.nix landed. The wrapper sets this; fall back to the
    source tree so the package also runs straight from a checkout."""
    return Path(os.environ.get(
        "NPINS_UI_EVAL", Path(__file__).parent.parent / "versions.nix"))


def sizes_expression():
    """sizes.nix is installed beside versions.nix, so one variable places
    both and the two cannot drift into different trees."""
    return eval_expression().parent / "sizes.nix"
