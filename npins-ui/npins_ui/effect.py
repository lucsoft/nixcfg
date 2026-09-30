"""What is left to do, in four answers.

Almost everything a pin move brings is live the moment the rebuild finishes:
a new binary is picked up the next time it starts, and switch-to-configuration
has already restarted the services it had to. Two things outlast the switch —
what the session loaded at login, and what the kernel came up with. REBUILD is
the odd one out: not a rebuild that has yet to take effect, but one that never
ran. It is spelled out rather than BUILD because the rebuild page calls one
derivation's worth of work a build.
"""

import os
import re
from pathlib import Path

from gi.repository import Gio, GLib

from .npins import pin_revision, read_pins


NOTHING, SESSION, REBOOT, REBUILD = 0, 1, 2, 3

TIER_ACTION = {
    NOTHING: "",
    SESSION: "Log out and back in to finish",
    REBOOT: "Reboot to finish",
    REBUILD: "Rebuild to install",
}
TIER_ICON = {
    NOTHING: "object-select-symbolic",
    SESSION: "system-log-out-symbolic",
    REBOOT: "system-reboot-symbolic",
    REBUILD: "software-update-available-symbolic",
}

# Why the status page is asking. The session tiers are about a rebuild that
# happened; REBUILD is about one that did not.
AFTER_SWITCH = ("An earlier rebuild is waiting on it. Whether the pins "
                "have moved is a separate question.")
TIER_PENDING = {
    SESSION: AFTER_SWITCH,
    REBOOT: AFTER_SWITCH,
    REBUILD: ("The pins on disk have never been built — applying was "
              "interrupted, or npins moved them from a terminal."),
}

STORE_ROOT = re.compile(r"^(/nix/store/[a-z0-9]{32}-[^/]+)")

# The four things in a system generation that only a reboot can swap.
BOOT_PARTS = ("kernel", "initrd", "kernel-modules", "firmware")


def boot_paths(generation):
    """The store paths a generation would boot from.

    Cut back to the store path, because the links do not agree on depth:
    `kernel` points at the bzImage *inside* the kernel while `kernel-modules`
    points at the package itself. versions.nix reports packages, so both
    sides have to be packages to compare at all.
    """
    found = {}
    for part in BOOT_PARTS:
        match = STORE_ROOT.match(str(Path(generation, part).resolve()))
        if match:
            found[part] = match.group(1)
    return found


def reboot_needed(target, baseline="/run/booted-system"):
    """Which boot components `target` has that `baseline` does not.

    Against /run/booted-system, the default, the answer is what a reboot
    would still be for — the only honest record of how this kernel came up,
    and cumulative: a rebuild done last week and never rebooted still counts.
    That is what lets the answer survive the app being closed without any
    bookkeeping of its own.

    Against /run/current-system it is the narrower question of what an
    update adds on top of what is already installed.
    """
    have = boot_paths(baseline)
    if not have:
        return []          # nothing to compare against; do not invent one
    return [part for part in BOOT_PARTS
            if part in have and target.get(part)
            and have[part] != target[part]]


def session_marker():
    """A "you still have to log out" flag with exactly the right lifetime.

    XDG_RUNTIME_DIR is wiped when the user's last session ends, so the flag
    clears itself on logout and survives everything shorter, the app being
    closed and reopened included.

    The alternative was to measure it the way the reboot half is measured, by
    looking for outdated store paths in the maps of running processes. That
    does not work here: home.nix takes one package from a second nixpkgs, and
    its private copy of mesa would read as a stale session forever.
    """
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base, "npins-ui-session-stale") if base else None


def mark_session_stale():
    marker = session_marker()
    if marker:
        marker.touch()


def session_stale():
    marker = session_marker()
    return bool(marker and marker.exists())


def change_tier(changes):
    """What will be owed once a change set has been applied.

    The reboot half does not come from the version diff — `changes["reboot"]`
    was measured against the running kernel when the change set was built,
    which also catches a kernel rebuilt at an unchanged version.
    """
    if not changes:
        return NOTHING
    if changes.get("reboot"):
        return REBOOT
    if changes.get("graphics"):
        return SESSION
    return NOTHING


def update_tier(changes):
    """What an update costs by itself, rather than what will be owed after it.

    The two differ once a reboot is already owed. That one belongs in the
    window, where it is the answer to "what do I have to do" — but not in a
    notification, which would then repeat it every time the timer runs, and
    not in a commit message, which is read on days and machines where this
    one's booted kernel means nothing.
    """
    if not changes:
        return NOTHING
    if changes.get("reboot_added"):
        return REBOOT
    if changes.get("graphics"):
        return SESSION
    return NOTHING


# What the running system was built from. /run/current-system is a symlink,
# so this reads as the new value the moment a switch lands.
SYSTEM_VERSION = Path("/run/current-system/nixos-version")


def system_revision():
    """Which nixpkgs commit /run/current-system came from.

    The pin is the Hydra channel release, whose tarball carries
    .version-suffix, so this file ends in the short revision of the very
    commit the lock file names: 26.05.10529.c508844df6c2.
    """
    try:
        label = SYSTEM_VERSION.read_text().strip()
    except OSError:
        return None
    return label.rsplit(".", 1)[-1] or None


def rebuild_owed(lockfile):
    """Whether what the lock file says has never been built.

    This is what a dismissed password dialog leaves behind. The pins are
    written before the rebuild starts, because nixos-rebuild reads them off
    the disk, so cancelling at the prompt keeps the write and loses the
    install; `npins update` in a terminal leaves the same state. Both halves
    of the comparison are read off the machine, so the answer survives the
    window being closed, the way the reboot one does.

    Only nixpkgs is asked about: it is the only pin the system is built
    from, and the system is the half that needs a password and so the half
    that gets abandoned. A home-manager move on its own goes unnoticed here.
    """
    try:
        pinned = pin_revision(read_pins(lockfile).get("nixpkgs", {}))
    except (OSError, ValueError, KeyError):
        return False
    running = system_revision()
    if not pinned or not running:
        return False
    # Channel pins carry the short revision, git pins the full one.
    return not (pinned.startswith(running) or running.startswith(pinned))


def pending_tier(lockfile=None):
    """What is owed right now, with nothing pending to apply.

    A rebuild outranks the other two: logging out of or rebooting into a
    system that was never built finishes nothing.
    """
    if lockfile and rebuild_owed(lockfile):
        return REBUILD
    if reboot_needed(boot_paths("/run/current-system")):
        return REBOOT
    return SESSION if session_stale() else NOTHING


# gnome-session rather than logind, for both of these. Its Reboot() puts up
# the confirmation everyone expects from the system menu and lets an app with
# unsaved work inhibit it; calling logind directly would walk past both.
#
# CanReboot() is not asked first. It answers with a uint whose values this
# code has no way to pin down, and guessing at an enum to grey out a button
# is worse than letting the call fail and saying why.
SESSION_MANAGER = ("org.gnome.SessionManager", "/org/gnome/SessionManager",
                   "org.gnome.SessionManager")

# Logout(0) is the mode that asks; 1 and 2 skip the dialog and force it.
LOGOUT_ASKING = 0


def end_session(tier):
    """Hand the session manager what the tier says is left to do."""
    method, args = (("Reboot", None) if tier == REBOOT
                    else ("Logout", GLib.Variant("(u)", (LOGOUT_ASKING,))))
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync(*SESSION_MANAGER, method, args, None,
                  Gio.DBusCallFlags.NONE, -1, None)
