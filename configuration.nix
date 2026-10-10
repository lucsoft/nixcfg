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

  # mutter names a mode by its own refresh number — 3440x1440@144.001 — which
  # nothing can predict for one the kernel builds off the command line, so look
  # the id up by resolution and take the first, the fastest. Sunshine's unit
  # forces PATH empty, hence the absolute paths.
  set-monitor = pkgs.writeShellScript "set-monitor" ''
    set -eu
    connector=$1 resolution=$2 scale=$3
    gmc=${pkgs.gnome-monitor-config}/bin/gnome-monitor-config

    mode=$("$gmc" list | ${pkgs.gawk}/bin/awk -v c="$connector" -v r="$resolution" '
      /^Monitor \[/ { here = ($3 == c) }
      here && $1 ~ "^" r "@" && match($0, /\[id: [^]]*\]/) {
        print substr($0, RSTART + 6, RLENGTH - 8)
        exit
      }
    ')

    [ -n "$mode" ] || { echo "no $resolution mode on $connector" >&2; exit 1; }
    exec "$gmc" set -L -M "$connector" -m "$mode" -s "$scale" -p
  '';
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
    # A monitor that is not there, so Moonlight can stream the MacBook Pro
    # 14"'s own 3024x1964: `e` forces the empty connector on, and with no EDID
    # to read the probe takes this mode as the connector's. The panel on DP-2
    # offers nothing near it, and mutter only hands out what a panel reports.
    "video=HDMI-A-1:3024x1964@60e"
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

  # Keys only — there is no password worth brute-forcing a public port with.
  services.openssh = {
    enable = true;
    openFirewall = true;
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "no";
    };
  };

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
    openssh.authorizedKeys.keys = [
      # ~/.ssh/id_ed25519.pub on this machine
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDQjtXFsbUxTkLB2H7sE+F6J2ZYbOmQORkk0Za0Gf7Uk mail@lucsoft.de"
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJWMrv1BL5cTjJsT1fukAYEuq4DQMcN5/i++OKUIMGID lucsoft@laptop"
    ];
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

  services.sunshine = {
    enable = true;
    openFirewall = true;
    capSysAdmin = true;

    # Naming the apps here takes them away from the web UI, which only ever
    # held Sunshine's own defaults — the first and last entries are those.
    applications = {
      env.PATH = "/run/current-system/sw/bin:$(HOME)/.local/bin";
      apps = [
        {
          name = "Desktop";
          image-path = "desktop.png";
        }
        {
          # 3024x1964 is the 14" panel and scale 2 the 1512x982 macOS draws it
          # at, so the stream lands pixel for pixel. Only HDMI-A-1 is named, so
          # the real monitor goes dark until `undo` brings it back — and stays
          # dark if Sunshine dies mid-stream, where ssh is the way back.
          name = "MacBook Desktop";
          image-path = "desktop.png";
          prep-cmd = [
            {
              do = "${set-monitor} HDMI-A-1 3024x1964 2";
              undo = "${set-monitor} DP-2 3440x1440 1";
            }
          ];
        }
        {
          name = "Steam Big Picture";
          image-path = "steam.png";
          detached = [ "setsid steam steam://open/bigpicture" ];
          prep-cmd = [
            {
              do = "";
              undo = "setsid steam steam://close/bigpicture";
            }
          ];
        }
      ];
    };
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

  # Andromeda is packaged in lucsoft/andromeda-nix, whose CI pushes here.
  # Without it the runtime is a 20 minute Rust build.
  nix.settings = {
    substituters = [ "https://andromeda-nix.cachix.org" ];
    trusted-public-keys = [
      "andromeda-nix.cachix.org-1:DEWHc3Ls1TK60gCMDnztXLcd5vE45As8QMP8Ro/cbaE="
    ];
  };

  system.stateVersion = "26.05"; # first installed version
}
