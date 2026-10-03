{ config, lib, pkgs, ... }:

let
  sources = import ./npins;

  unstable = import sources.nixpkgs-unstable { };

  npins-ui = pkgs.callPackage ./npins-ui { };

  # blur-my-shell asks for `gi://Blur`
  rounded-blur = pkgs.callPackage ./rounded-blur {
    src = sources.gnome-rounded-blur;
  };

  helium = pkgs.callPackage "${sources.helium}/helium.nix" { };

  # Makes a switch visible to the session that is already running, instead of
  # at the next login.
  #
  # The session watches ~/.nix-profile/share/applications for new apps, but
  # inotify resolves that path once, when the watch is set up, down to the
  # store directory behind it. A switch swaps the profile symlink and leaves
  # that directory untouched, so no event ever arrives and GIO never re-reads
  # the path — measured, not assumed. ~/.local/share/applications is a real
  # directory that changes in place, so a link appearing there does fire.
  # Mirroring the profile's entries into it is what makes a new app show up
  # right away; equal file names mean equal desktop IDs, so nothing is listed
  # twice and window-to-app matching still works.
  #
  # Icons need the other half. They go stale the same way, and mirroring does
  # not help because GTK caches the theme as a whole rather than per file.
  # Renaming the theme and renaming it back is what makes every client drop
  # that cache; the cost is a brief flicker across the desktop.
  xdg-mirror = pkgs.writeShellScript "xdg-mirror" ''
    set -u
    profile="$HOME/.nix-profile/share/applications"
    mirror="$HOME/.local/share/applications"
    mkdir -p "$mirror"

    # A link that goes away and comes back is an app uninstalled and installed
    # again as far as the session is concerned: the Shell drops the object
    # that owns that app's open windows and builds a fresh one, and the dash
    # icon loses its running dot until the app is restarted. So the mirror is
    # never wiped and laid down again — an entry that is already right is left
    # alone, and only the difference is applied.

    # Pointing into the profile is the ownership mark. Nothing else in here
    # does, so this drops entries of uninstalled apps and only those.
    for link in "$mirror"/*.desktop; do
      [ -L "$link" ] || continue
      case "$(readlink "$link")" in "$profile"/*) ;; *) continue ;; esac
      [ -e "$profile/''${link##*/}" ] || rm "$link"
    done

    for entry in "$profile"/*.desktop; do
      [ -e "$entry" ] || continue
      name=''${entry##*/}
      # A name Home Manager writes itself wins. xdg.desktopEntries is there to
      # override the package's copy, not to be shadowed by it.
      [ -e "$mirror/$name" ] || [ -L "$mirror/$name" ] || \
        ln -s "$entry" "$mirror/$name"
    done

    ${pkgs.desktop-file-utils}/bin/update-desktop-database "$mirror"

    # No session bus, no session to tell.
    [ -n "''${DBUS_SESSION_BUS_ADDRESS:-}" ] || exit 0
    key="org.gnome.desktop.interface icon-theme"
    theme=$(${pkgs.glib}/bin/gsettings get $key)
    if [ "$theme" = "'hicolor'" ]; then other="'Adwaita'"; else other="'hicolor'"; fi
    ${pkgs.glib}/bin/gsettings set $key "$other"
    ${pkgs.glib}/bin/gsettings set $key "$theme"
  '';
in

{
  home.username = "lucsoft";
  home.homeDirectory = "/home/lucsoft";

  programs.home-manager = {
    enable = true;
    path = "${sources.home-manager}";
  };

  nixpkgs.config.allowUnfree = true;

  home.packages = with pkgs; [
    # Apps
    vscode
    discord
    signal-desktop
    gnome-secrets
    helium
    resources

    # unstable until bottles v67 is stable
    (unstable.bottles.override { removeWarningPopup = true; })

    (lutris.override {
      extraPkgs = pkgs: with pkgs; [
        gamescope
        mangohud
        gamemode

        vulkan-tools
      ];

      extraLibraries = pkgs: with pkgs; [ gamemode ];
    })

    mangohud   # gamescope --mangoapp looks for mangoapp on PATH

    # Nix tooling
    npins-ui
    npins
    nixd
    nixfmt

    # CLI
    btop
    fastfetch
    claude-code
    mprisence

    # claude-code paste a screenshot
    wl-clipboard
  ];

  programs.gnome-shell = {
    enable = true;
    extensions = [
      { package = pkgs.gnomeExtensions.appindicator; }
      { package = pkgs.gnomeExtensions.just-perfection; }

      { package = pkgs.gnomeExtensions.blur-my-shell; }

      { package = pkgs.gnomeExtensions.dash-to-dock; }

      # A fragment shader as the desktop background, one per day out of
      # shaderbg/sources.nix. Local rather than from e.g.o because the only
      # GLSL wallpaper extension there stops at Shell 49.
      { package = pkgs.callPackage ./shaderbg { }; }

      { package = pkgs.gnomeExtensions.user-stylesheet-font; }
    ];
  };

  # How the Shell is told where Blur-1.0.typelib is. gnome-shell is a systemd
  # user unit, so environment.d reaches it, and its wrapper prepends its own
  # typelib path rather than replacing this one. The extension imports the
  # library when it is enabled, so this only takes effect after a logout.
  systemd.user.sessionVariables.GI_TYPELIB_PATH =
    "${rounded-blur}/lib/girepository-1.0";

  # The stylesheet the extension above reads.
  xdg.configFile."gnome-shell/gnome-shell.css".source = ./gnome-shell.css;

  dconf.settings."org/gnome/desktop/input-sources".sources = [
    (lib.hm.gvariant.mkTuple [ "xkb" "de+mac" ])
  ];


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
      OnStartupSec = "10m";
      OnUnitActiveSec = "6h";
      Persistent = true;
    };
    Install.WantedBy = [ "timers.target" ];
  };


  home.activation.syncXdgMirror =
    lib.hm.dag.entryAfter [ "linkGeneration" ] "run ${xdg-mirror}";

  # discord rpc
  xdg.configFile."mprisence/config.toml".text = ''
    allowed_players = ["soundcloud"]

    [web_player.soundcloud]
    status_display_type = "details"
  '';

  systemd.user.services.mprisence = {
    Unit = {
      Description = "Discord rich presence for MPRIS players";
      PartOf = [ "graphical-session.target" ];
      After = [ "graphical-session.target" ];
      # The daemon reloads the config when it changes, but what changes here
      # is a symlink pointing somewhere else, which its watcher does not see.
      # Naming the store path in the unit makes the unit itself differ on
      # every edit, and Home Manager restarts units that differ.
      X-Restart-Triggers = [ "${config.xdg.configFile."mprisence/config.toml".source}" ];
    };
    Service = {
      ExecStart = "${pkgs.mprisence}/bin/mprisence";
      # Discord is usually not up yet at login, and the daemon exits when it
      # cannot reach it. Restarting is how it waits.
      Restart = "always";
      RestartSec = 10;
    };
    Install.WantedBy = [ "graphical-session.target" ];
  };

  # The native messaging host, pointing Helium at the binary to speak to. It
  # goes in the profile directory, which for Helium is its application ID and
  # not the `chromium` that `mprisence web install` assumes — that command
  # would also bake in the store path of whichever mprisence ran it, so it
  # would go stale at the next update. Declared here it is rewritten on every
  # switch. The second origin is the extension's unlisted build, carried
  # along because upstream ships both IDs.
  home.file.".config/net.imput.helium/NativeMessagingHosts/mprisence.web.bridge.json".text =
    builtins.toJSON {
      name = "mprisence.web.bridge";
      description = "mprisence - sends browser media to MPRIS";
      type = "stdio";
      path = "${pkgs.mprisence}/bin/mprisence";
      allowed_origins = [
        "chrome-extension://pnkkjbdopihogobhhjbgapbpfccinjjo/"
        "chrome-extension://pphdmbejbipjlocngoefnmjoijcbdejf/"
      ];
    };


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
    };
  };

  # Resizing the window needs all three of these together: --xwayland-count 2
  # so gamescope reports the new size to Steam's X display at all, the patched
  # gamescope from configuration.nix, and the variable that arms the patch --
  # otherwise Steam asserts 1920x1080 back over every drag.
  # --force-grab-cursor locks the pointer, which Steam is special-cased out of.
  xdg.desktopEntries.steam-gamingmode = {
    name = "Steam Gaming Mode";
    genericName = "Steam Deck UI";
    comment = "Steam's gamepad UI, in a resizable gamescope window";
    exec = "env GAMESCOPE_IGNORE_STEAM_MODE_CONTROL=1 gamescope -W 1920 -H 1080 --xwayland-count 2 --force-grab-cursor -e --mangoapp -- steam -steamos3 -steamdeck -gamepadui";
    icon = "steam";
    terminal = false;
    categories = [ "Game" ];
    settings.StartupWMClass = "gamescope";
  };

  xdg.mimeApps = {
    enable = true;
    defaultApplications = {
      "text/html" = "helium.desktop";
      "x-scheme-handler/http" = "helium.desktop";
      "x-scheme-handler/https" = "helium.desktop";
      "x-scheme-handler/about" = "helium.desktop";
      "x-scheme-handler/unknown" = "helium.desktop";
      "x-scheme-handler/claude-cli" = "claude-code-url-handler.desktop";
    };
  };

  # default discord logo ugly
  xdg.dataFile."icons/hicolor/scalable/apps/discord.svg".source =
    ./icons/discord.svg;
  xdg.dataFile."icons/hicolor/256x256/apps/discord.svg".source =
    ./icons/discord.svg;

  home.sessionVariables = {
    EDITOR = "nano";
  };

  home.stateVersion = "26.05"; # first installed version
}
