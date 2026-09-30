"""An Adwaita front end for npins.

Answers three questions, cheapest first: has anything moved, how far, and
which of the packages I actually installed does it change.

The package is layered bottom up and every import points down. paths holds
what everything shares; npins, forge and evaluate each answer one of those
three questions; effect turns an answer into what is still owed; check runs
the three together and writes the result down; stream parses a rebuild. None
of those import Gtk. The ui package draws them, and app opens the window.
"""
