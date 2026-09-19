# nixcfg

Personal Nix configuration for my NixOS machine. NixOS 26.05, channel-free,
no flakes — nixpkgs is pinned by commit in `system.nix`.

## Layout

| file | what it covers |
|---|---|
| `system.nix` | entry point — pins nixpkgs, imports `configuration.nix` |
| `configuration.nix` | the machine: kernel, GNOME, pipewire, Steam, user account |
| `hardware-configuration.nix` | generated hardware scan (filesystems, kernel modules) |
| `home.nix` | Home Manager — my packages, dotfiles and user settings |

`~/.config/home-manager` is a symlink to this repo, so Home Manager picks
`home.nix` up directly.

## Applying changes

```sh
home-manager switch                      # user config — no sudo
sudo nixos-rebuild switch --file ~/nixcfg   # system config
```

The `--file` flag matters: without it, `nixos-rebuild` falls back to
`/etc/nixos/configuration.nix`, which is not this file.

## Updating nixpkgs

Everything is pinned to one commit in `system.nix`, so the system never
drifts on its own. To move forward:

1. Pick a commit from <https://github.com/NixOS/nixpkgs/commits/nixos-26.05>
2. `nix-prefetch-url --unpack https://github.com/NixOS/nixpkgs/archive/<rev>.tar.gz`
3. Update `rev`, `sha256` and `versionSuffix` in `system.nix`, then rebuild

Home Manager still tracks its own `release-26.05` channel separately.

## Notes

- **Steam must be a system module** (`programs.steam.enable`), never a package
  in `home.packages`. It needs 32-bit graphics drivers, controller udev rules
  and firewall ports — Home Manager has no `programs.steam` and cannot provide
  any of that.
- `home.stateVersion` / `system.stateVersion` are compatibility markers, not
  versions to bump.
- NixOS 26.05 reaches end of life on 2026-12-31.
