# nixcfg

Personal Nix configuration for my NixOS machine. NixOS 26.05, channel-free,
no flakes — nixpkgs is pinned by commit in `system.nix`, plus a second pin in
`home.nix` for one package.

## Layout

| file | what it covers |
|---|---|
| `system.nix` | entry point — pins nixpkgs, imports `configuration.nix` |
| `configuration.nix` | the machine: boot, GNOME, pipewire, Steam, user account |
| `hardware-configuration.nix` | generated hardware scan (filesystems, kernel modules) |
| `power.nix` | suspend/resume workarounds — transitional, see the file |
| `performance.nix` | CachyOS-style tuning, as an opt-in `cachy` boot entry |
| `bench.sh` | A/B benchmark harness for that entry |
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

### The second pin

`home.nix` pins a *second* nixpkgs, on `nixos-unstable`, used for exactly one
package: Bottles. The 63.2 that 26.05 ships is unusable — Cloudflare rejects
the User-Agent-less requests it makes, so it reports itself permanently
offline and can never install a runner. 67.4 fixes that upstream.

It moves the same way as the main pin, against
<https://github.com/NixOS/nixpkgs/commits/nixos-unstable>, and the whole `let`
block should be deleted once the stable channel carries 67.4 or newer.


## Performance tuning

`performance.nix` carries a CachyOS-style tuning set — sched_ext, zram,
CachyOS's own ananicy rules, their sysctls, `preempt=full`. It is not applied
to the running system. It is a `specialisation`, so a rebuild adds a second
entry to the boot menu:

    NixOS
    NixOS (cachy)          <- the tuned one

Both entries share one userland, down to the store path of every binary. That
makes the tuning measurable in a way a CachyOS-vs-NixOS comparison never is,
because only the tuned knobs differ between the two boots.

    ./bench.sh             # run the suite, tagged with whichever entry booted
    ./bench.sh compare     # newest baseline run vs newest cachy run

Results land in `bench-results/` (gitignored). The suite takes about four
minutes and saturates every core, so run it on an idle machine. It opens with
two control metrics that the tuning does not touch — if those move between
boots, the run was noisy and nothing else in the table is worth reading.

To promote the tuning to the default once it has earned it, move `tuning` out
of `specialisation` and into the module's own body; the file is written so
that is the only edit needed.

`bench-results/baseline-20260920-121826.tsv` is a first baseline measured
while this was being set up, not on a fully quiet machine. Re-run it before
trusting a close result.
## Notes

- **Steam must be a system module** (`programs.steam.enable`), never a package
  in `home.packages`. It needs 32-bit graphics drivers, controller udev rules
  and firewall ports — Home Manager has no `programs.steam` and cannot provide
  any of that.
- `home.stateVersion` / `system.stateVersion` are compatibility markers, not
  versions to bump.
- NixOS 26.05 reaches end of life on 2026-12-31.
