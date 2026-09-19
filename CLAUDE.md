# CLAUDE.md

Personal NixOS configuration. See `README.md` for the layout and the two
apply commands.

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

## Before committing a .nix change

Always evaluate first — never commit a change that has not been built:

    nixos-rebuild dry-build --file ~/nixcfg   # system side
    home-manager build && rm -rf result       # user side

Applying is the user's job: `nixos-rebuild switch` needs sudo, which is not
available in an agent session.
