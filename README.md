# nixcfg

Personal Nix configuration for my NixOS machine.

## Layout

| file | what it covers |
|---|---|
| `home.nix` | Home Manager — my packages, dotfiles and user settings |

`~/.config/home-manager` is a symlink to this repo, so Home Manager picks
`home.nix` up directly.

## Applying changes

```sh
home-manager switch        # user config — no sudo
```

System-level config (kernel, drivers, GNOME, pipewire, Steam, user accounts)
still lives in `/etc/nixos/configuration.nix` and is applied with:

```sh
sudo nixos-rebuild switch
```

## Setting this up on a fresh machine

NixOS 26.05, channel-based (no flakes), standalone Home Manager:

```sh
nix-channel --add https://github.com/nix-community/home-manager/archive/release-26.05.tar.gz home-manager
nix-channel --update
git clone <this-repo> ~/nixcfg
ln -s ~/nixcfg ~/.config/home-manager
nix-shell '<home-manager>' -A install
```

## Notes

- **Steam is intentionally not in `home.nix`.** It needs 32-bit graphics
  drivers, controller udev rules and firewall ports, so it must stay a system
  module (`programs.steam.enable`). Home Manager has no `programs.steam`.
- `home.stateVersion` is a compatibility marker, not a version to bump.
