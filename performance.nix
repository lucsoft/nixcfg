# CachyOS-style tuning, as an opt-in boot entry.
#
# Checked against CachyOS first: this kernel already matches it on HZ=1000,
# MGLRU, THP=madvise, amd-pstate EPP and the NVMe scheduler. What is left is
# below.
#
# It is a `specialisation`, so it adds a second systemd-boot entry sharing
# this userland rather than changing the running system — that is what makes
# ./bench.sh a controlled comparison. To make it the default, move `tuning`
# into `imports`.

{ config, lib, pkgs, ... }:

let
  tuning = {
    # BORE is a kernel patch and nixpkgs has no CachyOS kernel, but this
    # kernel has CONFIG_SCHED_CLASS_EXT=y, so a scheduler can be loaded as
    # BPF instead. scx_lavd is the gaming-oriented one; scx_bpfland is the
    # general interactive choice. Swapping them needs no reboot.
    services.scx = {
      enable = true;
      scheduler = "scx_lavd";
      # lavd defaults to --autopilot, which picks a power mode by load and
      # may enable core compaction. --performance pins it off. Measured: it
      # made no difference to any metric here.
      extraArgs = [ "--performance" ];
    };

    # This machine has no swap at all, so the kernel cannot evict anonymous
    # pages and goes straight from thrashing page cache to OOM. zstd gets
    # roughly 3:1, so ~15 GiB of swap costs ~5 GiB of RAM.
    zramSwap = {
      enable = true;
      algorithm = "zstd";
      memoryPercent = 50;
      priority = 100;
    };

    boot.kernel.sysctl = {
      # Swappiness is a ratio, not an amount. Against zram the anonymous
      # side is a memcpy while the file side re-reads NVMe, so 60 has the
      # preference backwards.
      "vm.swappiness" = 100;
      "vm.page-cluster" = 0;          # no seek to amortise on zram
      "vm.vfs_cache_pressure" = 50;   # the store is a huge dentry tree

      # Percentage-based defaults let ~6 GiB of dirty data pile up and
      # flush in one stalling burst.
      "vm.dirty_bytes" = 268435456;
      "vm.dirty_background_bytes" = 67108864;

      "vm.watermark_scale_factor" = 125;
      "vm.watermark_boost_factor" = 0;

      # Several Proton titles exceed the default and fail illegibly.
      "vm.max_map_count" = 2147483642;

      "kernel.nmi_watchdog" = 0;      # paired with nowatchdog below
    };

    boot.kernelParams = [
      # Compiled in as PREEMPT_DYNAMIC but boots lazy, which lets a busy
      # task hold a core until the next tick.
      "preempt=full"
      # The split-lock mitigation stalls every core; anti-cheat and older
      # engines trip it regularly.
      "split_lock_detect=off"
      "nowatchdog"
    ];

    # ananicy-rules-cachyos is CachyOS's own rule set, packaged in nixpkgs.
    services.ananicy = {
      enable = true;
      package = pkgs.ananicy-cpp;
      rulesProvider = pkgs.ananicy-rules-cachyos;
    };

    environment.etc."bench-profile".text = "cachy\n";
  };
in
{
  environment.etc."bench-profile".text = lib.mkDefault "baseline\n";

  specialisation.cachy.configuration = tuning;
}
