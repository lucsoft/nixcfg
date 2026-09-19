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
    bottles

    # Nix tooling
    nixd        # language server
    nixfmt      # formatter

    # CLI
    btop
    fastfetch
    claude-code
  ];

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
