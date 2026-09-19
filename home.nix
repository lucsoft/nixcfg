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
# Bottles is pulled from a second, separately pinned nixpkgs. The 63.2 that
# nixos-26.05 ships cannot reach its own servers: Cloudflare now answers the
# User-Agent-less requests it sends with 403, so it reports itself offline,
# never installs a runner, and the first-run wizard dies at its last step.
# 67.4 fixes that upstream — it sends a User-Agent and pings a list of hosts
# instead of one dead one — and exists only on unstable.
#
# Pinned to an exact commit, like system.nix, so it cannot drift. To move it:
#   1. Pick a commit from github.com/NixOS/nixpkgs/commits/nixos-unstable
#   2. nix-prefetch-url --unpack https://github.com/NixOS/nixpkgs/archive/<rev>.tar.gz
#   3. Update rev/sha256 below, then rebuild
#
# Drop this whole pin once the stable channel carries 67.4 or newer.
let
  unstableRev = "e554fab72f81915600f3f449b786fd9af40439a5";

  unstable = import (builtins.fetchTarball {
    # nixos-unstable as of 2026-09-19
    url = "https://github.com/NixOS/nixpkgs/archive/${unstableRev}.tar.gz";
    sha256 = "08qq3a6ry3sjm916cgwgd5421fddpk5jic8j4ssll9c8zmxm9a34";
  }) { };
in

{
  home.username = "lucsoft";
  home.homeDirectory = "/home/lucsoft";

  programs.home-manager.enable = true;

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

    # Nix tooling
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
    ];
  };

  # NOTE: `steam` is deliberately NOT here. It must stay a system-level module
  # (programs.steam.enable) because it needs 32-bit graphics drivers, controller
  # udev rules and firewall ports — none of which Home Manager can provide.

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
