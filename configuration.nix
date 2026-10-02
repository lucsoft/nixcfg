# The machine. Applied with `sudo nixos-rebuild switch --file ~/nixcfg`.

{ config, lib, pkgs, ... }:

let
  sources = import ./npins;

  # The daemon behind the Deck UI's power settings; see the block next to
  # programs.steam below for what it does and does not reach here.
  steamos-manager = pkgs.callPackage ./steamos-manager {
    src = sources.steamos-manager;
    version = lib.removePrefix "v" sources.steamos-manager.version;
  };

  # Passed to both halves of the daemon with --device-config, which is what
  # keeps a board upstream has never heard of out of its DMI table.
  steamos-manager-device = ./steamos-manager/device.toml;
in

{
  imports = [
    ./hardware-configuration.nix
    ./power.nix         # suspend workarounds, all transitional
  ];

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.kernelPackages = pkgs.linuxPackages_latest;

  # Boot splash instead of the log: the logo, a progress bar, and the name of
  # the unit systemd has just brought up. The theme lives in this repository
  # because every stock graphical theme runs on plymouth's two-step plugin,
  # which drops the unit names systemd sends it — see plymouth/nixos.script.
  boot.plymouth = {
    enable = true;
    themePackages = [ (pkgs.callPackage ./plymouth { }) ];
    theme = "nixos";
    logo = "${pkgs.nixos-icons}/share/icons/hicolor/256x256/apps/nix-snowflake.png";
  };

  # A splash is only a splash if nothing prints over it. `quiet` does double
  # duty here: the kernel holds its console output down to warnings, and
  # systemd drops its own status lines to failures only — while still handing
  # plymouth every unit name, which is a separate path. The udev settings do
  # the same for stage 1 and stage 2. Nothing is lost, it all stays in the
  # journal.
  boot.consoleLogLevel = 3;
  boot.kernelParams = [
    "quiet"
    "udev.log_level=3"
    "rd.udev.log_level=3"
    "vt.global_cursor_default=0"   # no blinking cursor over the splash

    # amdgpu keeps overdrive behind a feature bit, and without it the driver
    # never creates pp_od_clk_voltage — the only file a manual GPU clock can
    # be written to, and so the one thing the Deck UI's "Manual GPU Clock
    # Control" needs from steamos-manager below.
    #
    # This is the driver's own default, 0xfff7bfff, with PP_OVERDRIVE_MASK
    # (0x4000) set, rather than the 0xffffffff that gets passed around. Same
    # effect for overdrive, without also turning on every other feature bit
    # the driver left off. Re-check it against
    # /sys/module/amdgpu/parameters/ppfeaturemask after a kernel bump.
    "amdgpu.ppfeaturemask=0xfff7ffff"
  ];

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
  # The keyboard is a Mac one, so the layout has to be Apple's German: @ on
  # Alt+L, | on Alt+7, {} on Alt+8/9, ~ on Alt+N. Dead keys as in plain `de`.
  services.xserver.xkb.layout = "de";
  services.xserver.xkb.variant = "mac";
  console.keyMap = "mac-de-latin1";

  # GNOME Web. Helium is the browser here — see xdg.mimeApps in home.nix.
  environment.gnome.excludePackages = [ pkgs.epiphany ];

  fonts.packages = [ pkgs.twitter-color-emoji ];

  # Twemoji instead of Noto's emoji. This has to be the option and not a
  # <prefer> in localConf below: the option rewrites
  # 52-nixos-default-fonts.conf, while <prefer> only inserts a family that is
  # not in the list yet — Noto is already first by then, so a later rule
  # cannot displace it.
  #
  # noto-fonts-color-emoji stays installed. It rides along with
  # fonts.enableDefaultPackages and covers what Twemoji is missing.
  fonts.fontconfig.defaultFonts.emoji = [ "Twitter Color Emoji" ];

  # Web UI font stacks name the platform faces first and reach a font that
  # exists only at the end. GitHub asks for
  #
  #     -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, …
  #
  # Nothing here provides the first four — only the CJK Notos are installed,
  # and those are a different family name — so it fell through to Helvetica,
  # which 30-metric-aliases.conf maps to TeX Gyre Heros: a print face with no
  # screen hinting. That was the wrong-looking text.
  #
  # Point the two missing UI families at Adwaita Sans, which GNOME already
  # uses for the Shell and every GTK app, so web UIs match the desktop.
  # Helvetica is deliberately left alone — its alias is metric-compatible and
  # documents should keep it.
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

  # User packages live in home.nix (Home Manager), not here.
  users.users."lucsoft" = {
    isNormalUser = true;
    description = "lucsoft";
    # input/uinput are Sunshine's. It reads force feedback back off the virtual
    # gamepads it creates, and upstream asks for `input` outright. /dev/uinput
    # already carries a uaccess ACL, but that comes from Steam's udev rules —
    # the group is what keeps Sunshine working independently of Steam.
    extraGroups = [ "networkmanager" "wheel" "input" "uinput" ];
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

  # What puts "TDP Limit" and "Manual GPU Clock Control" in the Deck UI's
  # performance menu. None of it is gamescope's doing — its --steam
  # integration only advertises tearing, VRR, HDR and the scaling filters.
  # The client probes com.steampowered.SteamOSManager1 at startup instead, and
  # shows exactly the settings whatever implements it answers for.
  #
  # Two halves of one binary, as upstream ships it. The session one owns the
  # name Steam talks to; the root one does the sysfs writes, because the
  # amdgpu_hwmon method reports needs_root. Running only the session half
  # leaves the sliders visible and inert.
  #
  # Known rough edge: the daemon finds its card by scanning /sys/class/hwmon
  # for the first entry named "amdgpu", and this machine has two — the Navi 32
  # (hwmon4, the one with power1_cap) and the Raphael iGPU (hwmon5, which has
  # none). Directory order decides it, and nothing pins that order. If the TDP
  # setting disappears or errors after a kernel or BIOS change, that is the
  # first thing to check: `steamosctl get-tdp-limit`.
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

  # The session half exits 1 outright if the root half is not on the system
  # bus yet, so the restart window is upstream's rather than systemd's default
  # of five in ten seconds — which this would burn through in a login race and
  # then stay down for good.
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

  # The bus policy that lets a non-root client send to the service at all.
  # Without it the session half cannot reach the root half and every write
  # comes back as an access denial.
  services.dbus.packages = [ steamos-manager ];

  # steamosctl is the same package's CLI. It is the honest way to tell whether
  # an interface came up, rather than hunting for a slider in the UI.
  environment.systemPackages = [ steamos-manager ];

  # The host half of Moonlight. Moonlight is the client and is not installed
  # here; Sunshine is what streams this desktop out to one.
  #
  # capSysAdmin is not optional on this machine. The session is GNOME on
  # Wayland, where the only capture path left is kmsgrab, and reading another
  # process' framebuffer through drmModeGetFB2 needs CAP_SYS_ADMIN. Without it
  # Sunshine still starts, pairs, and streams a black screen.
  #
  # The wrapper avoids the AT_SECURE trap that keeps capSysNice off for
  # gamescope above: sunshine finds its libraries through a baked-in RUNPATH,
  # so losing LD_LIBRARY_PATH costs it nothing.
  #
  # `settings` stays empty on purpose. The module only passes sunshine a config
  # file once some setting other than the port is set, and a config file on the
  # command line locks the web UI read-only — which is where pairing, the
  # credentials and the app list all live.
  services.sunshine = {
    enable = true;
    openFirewall = true;   # TCP 47984/47989/47990/48010, UDP 47998-48000/48002/48010
    capSysAdmin = true;
  };

  # Claude Code writes ~/.claude/settings.json itself — /config keeps the theme
  # and its like in there — so Home Manager cannot own that file. A store
  # symlink is read-only, and an atomic write over one replaces the link and
  # breaks the next switch. Managed settings are the single layer the program
  # never writes back to. Everything here also outranks the other sources and
  # /config cannot undo it, so this is for decisions, not for preferences.
  environment.etc."claude-code/managed-settings.json".text = builtins.toJSON {
    disableArtifact = true;   # no publishing pages to claude.ai
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
