# The machine. Applied with `sudo nixos-rebuild switch --file ~/nixcfg`.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./power.nix         # suspend workarounds, all transitional
    ./performance.nix   # CachyOS-style tuning, as an opt-in boot entry
  ];

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxPackages_latest;

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

  # nixpkgs ships an en-US Firefox; German needs both the pack and a locale.
  programs.firefox = {
    enable = true;
    languagePacks = [ "de" ];
    preferences = {
      "intl.locale.requested" = "de,en-US";
    };
  };

  nixpkgs.config.allowUnfree = true;

  # Compatibility marker, not a version to bump.
  system.stateVersion = "26.05";
}
