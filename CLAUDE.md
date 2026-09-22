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

No channels, no flakes. Three pins live in `npins/sources.json`:

- **`nixpkgs`** — `nixos-26.05`, pinned against `releases.nixos.org` rather
  than GitHub, so it is the Hydra-tested channel release and the tarball
  carries `.git-revision` / `.version-suffix`. That is why `system.nix` does
  not set `system.nixos.revision` by hand.
- **`home-manager`** — `release-26.05`. `programs.home-manager.path` in
  `home.nix` bakes the pin into the installed CLI, so `home-manager switch`
  uses it instead of a `nix-channel` copy.
- **`nixpkgs-unstable`** — Bottles only; the comment in `home.nix` says why
  and when it can go.

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

Applying is the user's job: `nixos-rebuild switch` needs sudo, which is not
available in an agent session.

    home-manager switch                         # user side, no sudo
    sudo nixos-rebuild switch --file ~/nixcfg   # system side

`--file` matters: without it `nixos-rebuild` falls back to
`/etc/nixos/configuration.nix`, which is not this repo.

To see what a pin actually changed, before switching:

    nixos-rebuild build --file ~/nixcfg
    nix --extra-experimental-features nix-command \
        store diff-closures /run/current-system ./result

`nix-command` is not enabled on this machine, hence the flag.
