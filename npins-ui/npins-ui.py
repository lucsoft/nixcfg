#!/usr/bin/env python3
"""Where npins-ui starts.

A launcher rather than the program: the package sits beside this file in a
checkout and on PYTHONPATH once installed, so `import npins_ui` finds it
either way and the installed binary stays a script with a shebang.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from npins_ui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
