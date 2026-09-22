# nixcfg

Personal Nix configuration for my NixOS machine. NixOS 26.05, channel-free,
no flakes — nixpkgs and Home Manager are pinned by [npins](https://github.com/andir/npins)
in `npins/sources.json`.

## The machine

| part | what |
|---|---|
| CPU | AMD Ryzen 7 7800X3D — 8 cores, 16 threads |
| GPU | Radeon RX 7800 XT, 16 GB (Navi 32) |
| iGPU | Raphael, on the 7800X3D die — present, not driving anything |
| RAM | 32 GB DDR5 — 2 × 16 GB ADATA XPG `AX5U6000C3016G`, EXPO 6000 MT/s CL30-40-40-76 |
| Board | ASRock B650I Lightning WiFi (mini-ITX), BIOS 4.43 |
| Storage | Samsung 990 PRO 2 TB NVMe — single ext4 root, no swap partition |
| Network | Realtek 2.5G (`r8169`), MediaTek MT7921 Wi-Fi/Bluetooth (`mt7921e`) |
| Display | Gigabyte M34WQ — 3440×1440 ultrawide, up to 144 Hz, over DisplayPort |

Both GPUs are AMD, so both run on in-tree `amdgpu` and Mesa. Nothing in this
repo configures graphics — there is no proprietary driver to pull in.

## Layout

| file | what it covers |
|---|---|
| `system.nix` | entry point — imports `configuration.nix` against the pinned nixpkgs |
| `configuration.nix` | the machine: boot, GNOME, pipewire, Steam, user account |
| `hardware-configuration.nix` | generated hardware scan (filesystems, kernel modules) |
| `power.nix` | suspend/resume workarounds — transitional, see the file |
| `home.nix` | Home Manager — my packages, dotfiles and user settings |
| `npins/sources.json` | the pins: nixpkgs, nixpkgs-unstable, home-manager |

`npins/default.nix` is generated — never edit it by hand.

`~/.config/home-manager` is a symlink to this repo, so Home Manager picks
`home.nix` up directly.
