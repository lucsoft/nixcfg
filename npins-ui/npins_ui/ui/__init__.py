"""The widgets.

The version calls live here rather than in each module below: importing any
of them imports this package first, so `from gi.repository import Gtk` in a
submodule is always reached with the versions already pinned.
"""

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
