# Personal user-level Nix config (Home Manager, standalone).
#
# Apply with:   home-manager switch      (no sudo)
#
# What goes where:
#   /etc/nixos/configuration.nix -> the machine: kernel, drivers, GNOME,
#                                   pipewire, networking, Steam, user accounts
#   this file                    -> me: my programs, dotfiles, settings
#
# Options: https://home-manager-options.extranix.com/

{ config, pkgs, ... }:

let
  sources = import ./npins;

  # Bottles comes from a second, separately pinned nixpkgs. The 63.2 that
  # nixos-26.05 ships cannot reach its own servers: Cloudflare now answers the
  # User-Agent-less requests it sends with 403, so it reports itself offline,
  # never installs a runner, and the first-run wizard dies at its last step.
  # 67.4 fixes that upstream — it sends a User-Agent and pings a list of hosts
  # instead of one dead one — and exists only on unstable.
  #
  # Drop this, its pin (`npins remove nixpkgs-unstable`) and the override
  # below once the stable channel carries 67.4 or newer.
  unstable = import sources.nixpkgs-unstable { };

  npins-ui = pkgs.callPackage ./npins-ui { };
in

{
  home.username = "lucsoft";
  home.homeDirectory = "/home/lucsoft";

  # Home Manager itself is pinned too, so `home-manager switch` cannot drift
  # either. This bakes the path into the installed CLI, which otherwise looks
  # up <home-manager> in NIX_PATH and finds the nix-channel copy. The channel
  # is what evaluates the *first* switch after this lands; every one after
  # that uses the pin, so `nix-channel --remove home-manager` is safe then.
  programs.home-manager = {
    enable = true;
    path = "${sources.home-manager}";
  };

  # vscode and discord are unfree.
  nixpkgs.config.allowUnfree = true;

  # ---------------------------------------------------------------------------
  # Packages
  # ---------------------------------------------------------------------------
  home.packages = with pkgs; [
    # Apps
    vscode
    discord
    signal-desktop
    gnome-secrets   # KeePass-format password manager (libadwaita)
    resources       # system monitor (GNOME Circle)

    # From the unstable pin above, not this channel's broken 63.2.
    # removeWarningPopup drops the "unsupported environment" dialog nixpkgs
    # adds; Bottles upstream only supports its own Flatpak build.
    (unstable.bottles.override { removeWarningPopup = true; })

    # Lutris runs inside an FHS sandbox, because the Wine builds and runtimes
    # it downloads are ordinary dynamically-linked binaries. Everything it
    # composes into a launch command has to exist inside that sandbox too:
    # extraPkgs adds binaries, extraLibraries adds .so's for both bitnesses.
    #
    # Each one is found by a bare PATH lookup, and the matching toggle in
    # System options is *hidden* when the lookup fails — a missing binary is
    # not an error, the checkbox simply is not there.
    (lutris.override {
      extraPkgs = pkgs: with pkgs; [
        gamescope     # "Enable Gamescope"
        mangohud      # "Show FPS"; also supplies mangoapp for --mangoapp
        gamemode      # gamemoderun, for "Enable Feral GameMode"

        # Without vulkaninfo, Lutris names GPUs via lspci, which is installed
        # nowhere here. That dropdown is what picks the card gamescope renders
        # on, and this machine has the iGPU sitting next to the dGPU.
        vulkan-tools
      ];

      # gamemoderun LD_PRELOADs libgamemodeauto.so.0, so the library has to be
      # on the sandbox's lib paths, not just the binary on PATH.
      extraLibraries = pkgs: with pkgs; [ gamemode ];
    })

    # Nix tooling
    npins-ui    # Adwaita front end for npins
    npins       # updates the pins in npins/sources.json
    nixd        # language server
    nixfmt      # formatter

    # CLI
    btop
    fastfetch
    claude-code

    # wl-copy/wl-paste. A Wayland session ships no clipboard CLI at all, so
    # terminal programs cannot read the clipboard — this is what lets
    # claude-code paste a screenshot instead of silently ignoring Ctrl+V.
    wl-clipboard
  ];

  # GNOME Shell extensions. This module installs the packages *and* writes
  # enabled-extensions, taking each UUID from the package's extensionUuid —
  # a Shell loads nothing that is not in that list, and the UUIDs are not
  # worth typing by hand.
  programs.gnome-shell = {
    enable = true;
    extensions = [
      # Wine registers its tray icons over XEmbed. GNOME dropped XEmbed tray
      # support in 3.26, so with nothing to dock into, Wine parks them in a
      # standalone floating window — the boxes next to every Bottles prefix.
      # This brings XEmbed back (trayIconsManager.js, IndicatorStatusTrayIcon)
      # alongside its nominal job, AppIndicator and KStatusNotifierItem.
      #
      # extensions.gnome.org still serves v64, which stops at Shell 50.
      # Upstream added 51 in July 2026 and tagged it v65; nixpkgs packages
      # from e.g.o, so it arrives here once that publish goes through.
      { package = pkgs.gnomeExtensions.appindicator; }

      # Hide and tweak Shell UI elements.
      { package = pkgs.gnomeExtensions.just-perfection; }

      # Blur behind the panel, the overview and the dash.
      { package = pkgs.gnomeExtensions.blur-my-shell; }

      # Turn the overview dash into a permanent dock.
      { package = pkgs.gnomeExtensions.dash-to-dock; }
    ];
  };

  # NOTE: `steam` is deliberately NOT here. It must stay a system-level module
  # (programs.steam.enable) because it needs 32-bit graphics drivers, controller
  # udev rules and firewall ports — none of which Home Manager can provide.

  # Background update check. `npins-ui --check` probes a throwaway copy of the
  # lock file, so it writes nothing and needs no privileges. It exits 10 when
  # a pin can move, and only that exit code becomes a notification — a real
  # failure (no network, forge down) stays in the journal instead of nagging.
  systemd.user.services.npins-check = {
    Unit.Description = "Check whether the npins pins can move";
    Service = {
      Type = "oneshot";
      ExecStart = toString (pkgs.writeShellScript "npins-check" ''
        out=$(${npins-ui}/bin/npins-ui --check ${config.home.homeDirectory}/nixcfg)
        [ $? -eq 10 ] || exit 0
        ${pkgs.libnotify}/bin/notify-send \
          --app-name=Pins --icon=de.lucsoft.NpinsUi \
          "Updates available" "$out"
      '');
    };
  };

  systemd.user.timers.npins-check = {
    Unit.Description = "Check whether the npins pins can move";
    Timer = {
      OnStartupSec = "10m";      # not during login, the session is busy
      OnUnitActiveSec = "6h";
      Persistent = true;         # catch up after the machine was asleep
    };
    Install.WantedBy = [ "timers.target" ];
  };

  # ---------------------------------------------------------------------------
  # Dotfiles
  # ---------------------------------------------------------------------------
  programs.git = {
    enable = true;
    settings = {
      user.name = "lucsoft";
      user.email = "mail@lucsoft.de";
      init.defaultBranch = "main";
      pull.rebase = true;
      push.autoSetupRemote = true;   # `git push` on a new branch just works
    };
  };

  programs.bash = {
    enable = true;
    shellAliases = {
      hm = "home-manager switch";
      hme = "$EDITOR ~/nixcfg/home.nix";
      nixcfg = "cd ~/nixcfg";
    };
  };

  # Signal is an Electron app, so its chat UI is web content and no GTK theme
  # can reach it. The window frame is fixable though: on Wayland mutter draws
  # no server-side decorations, so Electron falls back to drawing its own
  # GTK3-styled titlebar, which matches nothing else on the desktop.
  # --gtk-version=4 makes it load GTK4 and pick up Adwaita colors and metrics.
  #
  # This shadows signal.desktop from the package: entries in
  # ~/.local/share/applications take precedence over the profile's copy.
  #
  # Alternative: --ozone-platform=x11 gets a real mutter-drawn Adwaita titlebar
  # via XWayland, at the cost of screen sharing in calls only seeing XWayland
  # windows.
  xdg.desktopEntries.signal = {
    name = "Signal";
    comment = "Private messaging from your desktop";
    exec = "signal-desktop --gtk-version=4 %U";
    icon = "signal-desktop";
    terminal = false;
    categories = [ "Network" "InstantMessaging" "Chat" ];
    mimeType = [ "x-scheme-handler/sgnl" "x-scheme-handler/signalcaptcha" ];
    settings.StartupWMClass = "signal";
  };

  home.sessionVariables = {
    EDITOR = "nano";
  };

  # Compatibility marker — not a version to bump.
  home.stateVersion = "26.05";
}
