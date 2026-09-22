# The machine. Applied with `sudo nixos-rebuild switch --file ~/nixcfg`.

{ config, pkgs, ... }:

let
  sources = import ./npins;
in

{
  imports = [
    ./hardware-configuration.nix
    ./power.nix         # suspend workarounds, all transitional
  ];

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxPackages_latest;

  # This machine shipped with no swap at all, so the kernel could not evict
  # anonymous pages and went straight from thrashing page cache to OOM. zstd
  # gets roughly 3:1, so ~15 GiB of swap costs ~5 GiB of RAM and never touches
  # the SSD.
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 100;
  };

  boot.kernel.sysctl = {
    # Swappiness is a ratio, not an amount. Against zram the anonymous side is
    # a memcpy while the file side re-reads NVMe, so 60 has it backwards.
    "vm.swappiness" = 100;
    "vm.page-cluster" = 0;          # no seek to amortise on zram
    "vm.vfs_cache_pressure" = 50;   # the store is a huge dentry tree

    # Percentage-based defaults let ~6 GiB of dirty data pile up and flush in
    # one stalling burst.
    "vm.dirty_bytes" = 268435456;
    "vm.dirty_background_bytes" = 67108864;

    "vm.watermark_scale_factor" = 125;
    "vm.watermark_boost_factor" = 0;

    # Several Proton titles exceed the default and fail illegibly.
    "vm.max_map_count" = 2147483642;
  };

  networking.hostName = "nixos";
  networking.networkmanager.enable = true;

  time.timeZone = "Europe/Berlin";

  i18n.defaultLocale = "de_DE.UTF-8";
  i18n.extraLocaleSettings = {
    LC_ADDRESS = "de_DE.UTF-8";
    LC_IDENTIFICATION = "de_DE.UTF-8";
    LC_MEASUREMENT = "de_DE.UTF-8";
    LC_MONETARY = "de_DE.UTF-8";
    LC_NAME = "de_DE.UTF-8";
    LC_NUMERIC = "de_DE.UTF-8";
    LC_PAPER = "de_DE.UTF-8";
    LC_TELEPHONE = "de_DE.UTF-8";
    LC_TIME = "de_DE.UTF-8";
  };

  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;
  services.xserver.xkb.layout = "de";
  console.keyMap = "de";

  services.printing.enable = true;

  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  # User packages live in home.nix (Home Manager), not here.
  users.users."lucsoft" = {
    isNormalUser = true;
    description = "lucsoft";
    extraGroups = [ "networkmanager" "wheel" ];
  };

  # Steam must be a system module, not a package: it needs 32-bit graphics
  # drivers, controller udev rules and the FHS runtime. Home Manager has no
  # programs.steam and cannot provide any of it.
  programs.steam = {
    enable = true;
    remotePlay.openFirewall = true;
    localNetworkGameTransfers.openFirewall = true;
    extest.enable = true;   # Steam Input on Wayland
  };

  programs.gamemode.enable = true;

  # gamescope must be a system module, not a package: capSysNice needs
  # security.wrappers. Lutris and Steam both find it by a bare PATH lookup.
  #
  # capSysNice stays off (the default). It only buys --rt, and file
  # capabilities put the binary in AT_SECURE mode, where glibc strips
  # LD_PRELOAD and LD_LIBRARY_PATH from the environment — which is how
  # MangoHud and gamemode reach the game in the first place.
  #
  # No global args: Lutris emits its own --prefer-vk-device from the GPU
  # dropdown, and passing it twice leaves which one wins undefined.
  programs.gamescope.enable = true;

  # nixpkgs ships an en-US Firefox; German needs both the pack and a locale.
  programs.firefox = {
    enable = true;
    languagePacks = [ "de" ];
    preferences = {
      "intl.locale.requested" = "de,en-US";
    };
  };

  nixpkgs.config.allowUnfree = true;

  # Point <nixpkgs> at the pinned tree. NixOS defaults it to root's channel
  # profile, which nothing in this repo maintains — it holds whatever the
  # installer fetched and `nix-channel --update` last left there. That path is
  # what standalone Home Manager builds against, so without this line
  # `home-manager switch` builds against a different nixpkgs than the system.
  nix.nixPath = [ "nixpkgs=${sources.nixpkgs}" ];

  # Compatibility marker, not a version to bump.
  system.stateVersion = "26.05";
}
