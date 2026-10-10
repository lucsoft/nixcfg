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
  # nothing can predict for a mode that comes out of an EDID we generated here,
  # so both halves read the ids back out of mutter at run time.
  #
  #   only <connector> <resolution> <scale>   that connector, by itself
  #   rest <connector>                        every other one, as mutter prefers
  #
  # `rest` is the undo, and it asks mutter rather than being told, so no monitor
  # this machine happens to own is named anywhere below. Sunshine's unit forces
  # PATH empty, hence the absolute paths.
  monitors = pkgs.writeShellScript "monitors" ''
    set -eu
    gmc=${pkgs.gnome-monitor-config}/bin/gnome-monitor-config
    awk=${pkgs.gawk}/bin/awk

    case "$1" in
    only)
      # the connector may be seconds old, and mutter learns of it over udev
      for _ in {1..50}; do
        mode=$("$gmc" list | "$awk" -v c="$2" -v r="$3" '
          /^Monitor \[/ { here = ($3 == c) }
          here && $1 ~ "^" r "@" && match($0, /\[id: [^]]*\]/) {
            print substr($0, RSTART + 6, RLENGTH - 8)
            exit
          }
        ')
        [ -z "$mode" ] || break
        ${pkgs.coreutils}/bin/sleep 0.1
      done
      [ -n "$mode" ] || { echo "monitors: no $3 mode on $2" >&2; exit 1; }
      exec "$gmc" set -L -M "$2" -m "$mode" -s "$4" -p
      ;;

    rest)
      # one tab-separated row per monitor: connector, preferred mode, the width
      # that mode covers once its preferred scale is applied, and that scale
      args=() x=0 primary=-p
      while IFS=$'\t' read -r connector mode width scale; do
        args+=(-L -x "$x" -M "$connector" -m "$mode" -s "$scale" $primary)
        x=$(( x + width ))
        primary=
      done < <("$gmc" list | "$awk" -v skip="$2" '
        /^Monitor \[/ { connector = $3; taken = (connector == skip) }
        !taken && /PREFERRED/ && match($0, /\[id: [^]]*\]/) {
          mode = substr($0, RSTART + 6, RLENGTH - 8)
          scale = match($0, /scale = [0-9.]+/) ? substr($0, RSTART + 8, RLENGTH - 8) : 1
          split($1, size, /[x@]/)
          printf "%s\t%s\t%d\t%s\n", connector, mode, int(size[1] / scale + 0.5), scale
          taken = 1
        }
      ')

      [ ''${#args[@]} -gt 0 ] || { echo "monitors: nothing left but $2" >&2; exit 1; }
      exec "$gmc" set "''${args[@]}"
      ;;
    esac
  '';

  # The same forcing the kernel command line can do, done at run time instead.
  # A connector forced at boot is there for every session the machine ever
  # starts, the greeter's included — and the greeter will put the login prompt
  # on a screen that does not exist, which locks the machine. debugfs does the
  # forcing on demand, so the ghost is only up while a stream wants it.
  ghost-monitor = pkgs.writeShellScript "ghost-monitor" ''
    set -eu
    edid=${config.hardware.display.edid.packages}/lib/firmware/edid/MBP14_60.bin

    # the dri minor is whatever it is, and the connector directory has been
    # spelled both ways across kernels
    dir=
    for candidate in /sys/kernel/debug/dri/*/HDMI-A-1 /sys/kernel/debug/dri/*/card*-HDMI-A-1; do
      if [ -e "$candidate/force" ]; then dir=$candidate; break; fi
    done
    [ -n "$dir" ] || { echo "ghost-monitor: no debugfs entry for HDMI-A-1" >&2; exit 1; }

    case "$1" in
    up)
      ${pkgs.coreutils}/bin/cat "$edid" > "$dir/edid_override"
      echo on > "$dir/force"
      ;;
    down)
      # `reset` is compared against exactly five bytes and `force` reads into a
      # char[12] that must hold a terminator, so neither write may carry the
      # newline echo would add — `unspecified` is eleven characters exactly
      printf reset > "$dir/edid_override"
      printf unspecified > "$dir/force"
      ;;
    esac

    echo 1 > "$dir/trigger_hotplug"
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

  # The mode list of a monitor that is not there, so Moonlight can stream the
  # MacBook Pro 14"'s own 3024x1964: the panel on DP-2 offers nothing near it,
  # and mutter only ever hands out what a panel reports. Nothing here reaches
  # a connector by itself — `ghost-monitor` hands this file to debugfs when a
  # stream starts. Reduced blanking because there is no sink to negotiate with
  # and 386 MHz of pixel clock is a far easier sell than plain CVT's 508;
  # `cvt -r 3024 1964 60` prints this line. 120 Hz would want 794 MHz, which
  # is past HDMI TMDS and needs an EDID advertising FRL, so this one is 60 Hz.
  # edid-generator refuses a modeline whose aspect it cannot name, and 3024:1964
  # is none of the four it knows, so say 16:10 — the field only feeds the
  # standard-timing descriptors, not the detailed timing that matters. dpi is
  # the 14" panel's real 254, which is what makes mutter offer scale 2 at all.
  hardware.display.edid.modelines."MBP14_60" =
    "385.75  3024 3072 3104 3184  1964 1967 1977 2020 "
    + "+hsync -vsync ratio=16:10 dpi=254";

  systemd.services.ghost-monitor = {
    description = "A monitor that is not there, for as long as a stream wants it";
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${ghost-monitor} up";
      ExecStop = "${ghost-monitor} down";
    };
  };

  # Sunshine's prep-cmd runs as whoever is logged in, and debugfs is root's
  security.polkit.extraConfig = ''
    polkit.addRule(function (action, subject) {
      if (action.id == "org.freedesktop.systemd1.manage-units"
          && action.lookup("unit") == "ghost-monitor.service"
          && subject.isInGroup("wheel"))
        return polkit.Result.YES;
    });
  '';

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
          # Sunshine runs the undos in reverse, so the ghost is raised before
          # the session moves onto it and dropped after it has moved back off.
          # The two halves name the same connector differently: debugfs knows
          # the kernel's HDMI-A-1, while mutter drops the connector type's
          # suffix and calls it HDMI-1, which is the name its D-Bus API takes.
          prep-cmd = [
            {
              do = "${config.systemd.package}/bin/systemctl start ghost-monitor.service";
              undo = "${config.systemd.package}/bin/systemctl stop ghost-monitor.service";
            }
            {
              do = "${monitors} only HDMI-1 3024x1964 2";
              undo = "${monitors} rest HDMI-1";
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
