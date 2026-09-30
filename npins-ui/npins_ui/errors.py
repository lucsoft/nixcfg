"""An exception, as a sentence someone can read.

The two ways this app talks to the outside world are a subprocess and a URL,
and both have an unreadable default repr. Kept apart from either because the
check and the window both end up showing one.
"""

import subprocess
import urllib.error


def describe_error(error):
    if isinstance(error, subprocess.CalledProcessError):
        detail = (error.stderr or error.stdout or "").strip()
        return detail or f"{error.cmd[0]} exited with {error.returncode}"
    if isinstance(error, urllib.error.URLError):
        return f"Cannot reach the forge: {error.reason}"
    return f"{type(error).__name__}: {error}"
