# CLAUDE.md

Personal NixOS configuration. See `README.md` for the machine and the
layout.

## Language

**Everything committed to this repository is written in English**, no matter
what language the conversation happens in:

- commit messages
- comments inside `.nix` files
- documentation, including this file

The user may write in German. The repository stays English.

## Commit messages

Follow the nixpkgs convention:

    <scope>: <imperative summary>

    <optional body explaining WHY, wrapped at 72 columns>

Rules:

- `<scope>` is lowercase and names the thing being changed: a program
  (`firefox`, `steam`), a file (`home`, `system`), or an area (`git`, `docs`).
- The summary is imperative mood and lowercase after the colon, with no
  trailing period — "add German language pack", not "Added a language pack."
- Keep the summary under ~60 characters.
- The body explains *why*; the diff already shows *what*.
- No attribution trailers. No `Co-Authored-By`, no tool signatures.

Examples:

    firefox: add German language pack
    steam: enable system module for 32-bit drivers
    home: move user packages out of configuration.nix

## Hard constraints

- **This repository is public.** Never commit secrets, tokens, or the user's
  work email address. The git identity here is `lucsoft <mail@lucsoft.de>`.
- `stateVersion` in both `home.nix` and `configuration.nix` is a
  compatibility marker, not a version to bump.

## Pins

No channels, no flakes. Multiple pins live in `npins/sources.json`:

- **`nixpkgs`** — `nixos-26.05`, pinned against `releases.nixos.org` rather
  than GitHub, so it is the Hydra-tested channel release and the tarball
  carries `.git-revision` / `.version-suffix`. That is why `system.nix` does
  not set `system.nixos.revision` by hand.
- **`home-manager`** — `release-26.05`. `programs.home-manager.path` in
  `home.nix` bakes the pin into the installed CLI, so `home-manager switch`
  uses it instead of a `nix-channel` copy.
- **`nixpkgs-unstable`** — Bottles only; the comment in `home.nix` says why
  and when it can go.
- **`helium`** — `oxcl/nix-flake-helium-browser`, a third party's packaging of
  the Helium browser, which no channel carries. It is a flake, but nothing
  here treats it as one: `home.nix` calls its `helium.nix` through
  `callPackage`, which is all its `flake.nix` does too, so the package builds
  against the nixpkgs pinned above rather than the unstable its `flake.lock`
  names. Pinned to `main`, because the repo cuts no releases. The browser
  version is a literal inside `helium.nix`, so `npins update helium` is also
  what updates the browser.
- **`gnome-rounded-blur`** — the `gi://Blur` library blur-my-shell imports to
  round the corners of its blur; no channel carries it. Pinned to the release
  tag. `rounded-blur/default.nix` builds it against the pinned mutter, and
  `meson.build` names `libmutter-18` literally — that is mutter 50's ABI, so
  a mutter bump fails to configure here until upstream moves the number.
- **`steamos-manager`** — Valve's own, from `gitlab.steamos.cloud`, and no
  channel carries it. It is the D-Bus API the Steam client probes to decide
  which power settings its Deck UI may show, which is the only way to get a
  TDP or GPU clock control there. Pinned to the release tag.
  `steamos-manager/default.nix` builds it; `steamos-manager/device.toml`
  describes this board, because upstream's own device table is handhelds only.

`nix.nixPath` in `configuration.nix` aims `<nixpkgs>` at the same pin, because
that path is what standalone Home Manager builds against.

Moving a pin is `npins`, never a hand-edited rev or hash:

    npins update --dry-run   # what would move, nothing written
    npins update             # fetch new revs + hashes
    npins show               # where the pins stand right now
    npins update nixpkgs     # or move just one

`npins/default.nix` is generated — never edit it by hand. Same for
`hardware-configuration.nix`.

## Building and applying

Always evaluate first — never commit a change that has not been built:

    nixos-rebuild dry-build --file ~/nixcfg   # system side
    home-manager build && rm -rf result       # user side

Then apply. The user side needs no sudo, so an agent session runs it itself —
build first, switch second, no need to ask. The system side does need sudo,
which an agent session does not have, so that one stays the user's job.

    home-manager switch                         # user side, no sudo — go ahead
    sudo nixos-rebuild switch --file ~/nixcfg   # system side — ask the user

Work happens directly on `main`, and committing and pushing there is part of
finishing a change rather than something to ask about each time.

A newly added GNOME Shell extension will not show up after a switch. The Shell
scans its extension directories once, at startup, and the one D-Bus method that
looks like it would help — `org.gnome.Shell.Extensions.ReloadExtension` —
answers `NotSupported: deprecated and does not work`. On Wayland there is no
way to restart the Shell either, so it takes a logout. Say so instead of
leaving it looking broken.

The same goes for `shaderbg/lib`, the C half of shaderbg that the extension
imports as `gi://ShaderBg`. It reaches the Shell through
`systemd.user.sessionVariables.GI_TYPELIB_PATH` in `home.nix`, which
environment.d only re-reads at login, so a rebuilt typelib needs a logout too.
Its `meson.build` names `libmutter-18` literally, exactly as `rounded-blur`
does, so a mutter bump fails to configure rather than building something the
Shell would refuse to load.

`--file` matters: without it `nixos-rebuild` falls back to
`/etc/nixos/configuration.nix`, which is not this repo.

To see what a pin actually changed, before switching:

    nixos-rebuild build --file ~/nixcfg
    nix --extra-experimental-features nix-command \
        store diff-closures /run/current-system ./result

`nix-command` is not enabled on this machine, hence the flag.

## Previewing the boot splash

The theme in `plymouth/` can be looked at without rebooting: `plymouthd`
picks its X11 renderer whenever `DISPLAY` is set, and draws into a window
instead of the framebuffer. It insists on being root and on `/run/plymouth`,
both of which a user namespace can fake:

    bwrap --dev-bind / / --unshare-user --uid 0 --gid 0 \
      --tmpfs /run --bind /run/user/1000 /run/user/1000 \
      --tmpfs /etc --bind /etc/fonts /etc/fonts --bind "$conf" /etc/plymouth \
      sh -c 'mkdir -p /run/plymouth
             ln -s "$theme"/share/plymouth/themes /run/plymouth/themes
             ln -s "$plymouth"/lib/plymouth /run/plymouth/plugins
             plymouthd --no-daemon --mode=boot'

`$conf` is a directory holding a `plymouthd.conf` with `Theme=nixos` and the
`logo.png`; `/run` has to be a tmpfs because the real one is root-owned, which
also means `PATH` loses `/run/current-system/sw/bin`. Then, from outside:

    plymouth show-splash
    plymouth update --status=NetworkManager.service   # what systemd sends
    plymouth display-message --text="..."
    plymouth quit

Screenshot the window with `import -window "$(xwininfo -root -children |
grep plymouthd)"`. Errors from the theme script only show up with
`--kernel-command-line='splash plymouth.debug=stream:/tmp/plyd.log'`, because
`--debug` alone tries to write to `/dev/tty`.

## Worth knowing

- **NixOS 26.05 reaches end of life on 2026-12-31.** The pins, both
  `stateVersion` markers and the Bottles workaround are all tied to that
  release.
- **A CachyOS-style tuning specialisation has already been tried** —
  sched_ext, ananicy, `preempt=full`. It lived in the tree briefly and was
  removed in the commit right after the one that added it, because the
  benchmarks came out inconclusive; that commit message carries the numbers.
  `git log --oneline --all -- performance.nix` finds it, and `git show` on
  that commit brings `performance.nix` and `bench.sh` back. Do not re-add any
  of it without new measurements.
