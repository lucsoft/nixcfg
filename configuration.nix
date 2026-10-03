# The machine. Applied with `sudo nixos-rebuild switch --file ~/nixcfg`.

{ config, lib, pkgs, ... }:

let
  sources = import ./npins;

  steamos-manager = pkgs.callPackage ./steamos-manager {
    src = sources.steamos-manager;
    version = lib.removePrefix "v" sources.steamos-manager.version;
  };

  # --device-config, because upstream's DMI table is handhelds only
  steamos-manager-device = ./steamos-manager/device.toml;

  # Jovian's packaging of Decky, built from source against the nixpkgs pinned
  # here. Only this one file is used; none of Jovian's modules are imported.
  # The Decky version is a literal inside it, so `npins update jovian` is also
  # what updates the loader.
  decky-loader = pkgs.callPackage "${sources.jovian}/pkgs/decky-loader" { };

  decky-state = "/var/lib/decky-loader";
in

{
  imports = [
    ./hardware-configuration.nix
    ./power.nix
  ];

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxPackages_latest;

  boot.plymouth = {
    enable = true;
    themePackages = [ (pkgs.callPackage ./plymouth { }) ];
    theme = "nixos";
    logo = "${pkgs.nixos-icons}/share/icons/hicolor/256x256/apps/nix-snowflake.png";
  };

  boot.consoleLogLevel = 3;
  boot.kernelParams = [
    "quiet"
    "udev.log_level=3"
    "rd.udev.log_level=3"
    "vt.global_cursor_default=0"   # no blinking cursor over the splash
    # amdgpu's default mask plus PP_OVERDRIVE_MASK — pp_od_clk_voltage, and so
    # the manual GPU clock, does not exist without it
    "amdgpu.ppfeaturemask=0xfff7ffff"
  ];

  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 100;
  };

  # sys calls i stole somewhere for gaming performance stuff

  boot.kernel.sysctl = {
    "vm.swappiness" = 100;
    "vm.page-cluster" = 0;
    "vm.vfs_cache_pressure" = 50;

    "vm.dirty_bytes" = 268435456;
    "vm.dirty_background_bytes" = 67108864;

    "vm.watermark_scale_factor" = 125;
    "vm.watermark_boost_factor" = 0;

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
  services.xserver.xkb.variant = "mac";
  console.keyMap = "mac-de-latin1";

  # GNOME Web. Helium is the browser here — see xdg.mimeApps in home.nix.
  environment.gnome.excludePackages = [ pkgs.epiphany ];

  fonts.packages = [ pkgs.twitter-color-emoji ];

  # Twemoji better
  fonts.fontconfig.defaultFonts.emoji = [ "Twitter Color Emoji" ];

  # Some websites where ugly
  fonts.fontconfig.localConf = ''
    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
    <fontconfig>
      <alias binding="same">
        <family>Segoe UI</family>
        <prefer><family>Adwaita Sans</family></prefer>
      </alias>
      <alias binding="same">
        <family>Noto Sans</family>
        <prefer><family>Adwaita Sans</family></prefer>
      </alias>
    </fontconfig>
  '';

  services.printing.enable = true;

  services.pulseaudio.enable = false;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  users.users."lucsoft" = {
    isNormalUser = true;
    description = "lucsoft";
    # input/uinput for Sunshine
    extraGroups = [ "networkmanager" "wheel" "input" "uinput" ];
  };

  programs.steam = {
    enable = true;
    remotePlay.openFirewall = true;
    localNetworkGameTransfers.openFirewall = true;
    extest.enable = true;   # Steam Input on Wayland
  };

  programs.gamemode.enable = true;
  programs.gamescope.enable = true;

  # Patched so Steam cannot take the resolution back; see the patch header
  # and the Gaming Mode entry in home.nix, which sets the variable.
  programs.gamescope.package = pkgs.gamescope.overrideAttrs (o: {
    patches = (o.patches or [ ]) ++ [ ./gamescope/ignore-steam-mode-control.patch ];
  });

  systemd.services.steamos-manager = {
    description = "SteamOS Manager, privileged half";
    wantedBy = [ "multi-user.target" ];
    environment.RUST_LOG = "info";
    serviceConfig = {
      Type = "notify-reload";
      ExecStart = "${steamos-manager}/lib/steamos-manager -r --device-config ${steamos-manager-device}";
      Restart = "on-failure";
      RestartSec = 1;
    };
  };

  # exits 1 while the root half is not on the bus yet, so widen the window
  systemd.user.services.steamos-manager = {
    description = "SteamOS Manager, session half";
    wantedBy = [ "graphical-session.target" ];
    partOf = [ "graphical-session.target" ];
    environment.RUST_LOG = "info";
    startLimitIntervalSec = 120;
    startLimitBurst = 5;
    serviceConfig = {
      Type = "notify-reload";
      ExecStart = "${steamos-manager}/lib/steamos-manager --device-config ${steamos-manager-device}";
      Restart = "on-failure";
      RestartSec = 1;
    };
  };

  services.dbus.packages = [ steamos-manager ];
  environment.systemPackages = [ steamos-manager ];

  # Decky, the plugin manager for the Deck UI. It reaches Steam the same way a
  # devtools window would: Steam exposes its CEF on localhost, Decky attaches
  # and injects its own frontend, which is why nothing about the Gaming Mode
  # entry in home.nix has to change for it.
  #
  # That CEF port only opens when ~/.steam/steam/.cef-enable-remote-debugging
  # exists. The file is already there, and it is Steam's own switch (Settings ->
  # "Enable developer mode"), so it stays imperative — Steam does not stop
  # listening when the file goes away again, so a declarative one would be a
  # port this config could open but never close.
  #
  # The loader runs as root and setuids down per plugin; running it unprivileged
  # is unsupported upstream. Plugins therefore land as `decky`, not as lucsoft,
  # which keeps store-installed plugin backends out of the real home directory.
  users.users.decky = {
    group = "decky";
    home = decky-state;
    isSystemUser = true;
  };
  users.groups.decky = { };

  systemd.services.decky-loader = {
    description = "Steam Deck Plugin Loader";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" ];
    environment = {
      UNPRIVILEGED_USER = "decky";
      UNPRIVILEGED_PATH = decky-state;
      PLUGIN_PATH = "${decky-state}/plugins";
    };
    preStart = ''
      mkdir -p "${decky-state}"
      chown -R decky: "${decky-state}"
    '';
    serviceConfig = {
      ExecStart = "${decky-loader}/bin/decky-loader";
      # plugin backends are children it must not take down with itself
      KillMode = "process";
      TimeoutStopSec = 45;
    };
  };

  services.sunshine = {
    enable = true;
    openFirewall = true;
    capSysAdmin = true;
  };

  environment.etc."claude-code/managed-settings.json".text = builtins.toJSON {
    disableArtifact = true;

    attribution = {
      commit = "";
      sessionUrl = false;
    };
  };

  nixpkgs.config.allowUnfree = true;

  nix.nixPath = [ "nixpkgs=${sources.nixpkgs}" ];

  system.stateVersion = "26.05"; # first installed version
}
