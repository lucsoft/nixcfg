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
| RAM | 32 GB |
| Board | ASRock B650I Lightning WiFi (mini-ITX), BIOS 4.43 |
| Storage | Samsung 990 PRO 2 TB NVMe — single ext4 root, no swap partition |
| Network | Realtek 2.5G (`r8169`), MediaTek MT7921 Wi-Fi/Bluetooth (`mt7921e`) |
| Display | one, over DisplayPort |

Both GPUs are AMD, so both run on in-tree `amdgpu` and Mesa. Nothing in this
repo configures graphics — there is no proprietary driver to pull in.

What the hardware explains elsewhere in the config:

- `zramSwap.memoryPercent = 50` is a fraction of the 32 GB, so the compressed
  swap lands at ~15 GiB. The number moves if the RAM does.
- `power.nix` is entirely about this board's S3 suspend. BIOS 4.43 is the
  version that fixed it; anything older hangs on resume.
- `kvm-amd` and the AMD microcode line in `hardware-configuration.nix` come
  from the hardware scan and follow the CPU.

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

## Notes

- **zram, not a swap partition.** The machine had no swap at all, which
  means no way to evict anonymous pages — straight from thrashing the page
  cache to the OOM killer. The `vm.*` sysctls next to it exist to suit zram
  (`swappiness = 100`, `page-cluster = 0`) and are not meaningful without it.
- A CachyOS-style tuning specialisation — sched_ext, ananicy, `preempt=full`
  — lived here briefly and was removed in the commit after it was added. The
  benchmarks were inconclusive; see that commit message for the numbers, and
  `git show` it to get `performance.nix` and `bench.sh` back.
- **Steam must be a system module** (`programs.steam.enable`), never a package
  in `home.packages`. It needs 32-bit graphics drivers, controller udev rules
  and firewall ports — Home Manager has no `programs.steam` and cannot provide
  any of that.
- **A second nixpkgs pin exists for one package.** `nixpkgs-unstable` is there
  only for Bottles: the 63.2 in 26.05 makes User-Agent-less requests that
  Cloudflare rejects, so it reports itself permanently offline and can never
  install a runner. 67.4 fixes it. The pin and the override in `home.nix` go
  once stable catches up.
- `home.stateVersion` / `system.stateVersion` are compatibility markers, not
  versions to bump.
- NixOS 26.05 reaches end of life on 2026-12-31.
