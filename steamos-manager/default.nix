# Packaging for Valve's steamos-manager, the system daemon the Steam client
# talks to for the settings its Deck UI cannot reach on its own — TDP limit,
# GPU performance level, manual GPU clock. Called from configuration.nix with
# the npins source.
#
# Upstream's own README is the reason this is worth having off Deck hardware:
# the client probes this D-Bus API at startup and shows exactly the settings
# the running implementation answers for. Nothing in gamescope affects it;
# its --steam integration sets STEAM_GAMESCOPE_* for tearing, VRR, HDR and
# scaling, and has nothing to say about power.

{ lib
, rustPlatform
, src
, version
, pkg-config
, glib
, gsettings-desktop-schemas
, speechd-minimal
, udev
, wrapGAppsNoGuiHook
}:

rustPlatform.buildRustPackage {
  pname = "steamos-manager";
  inherit src version;

  # Every dependency is a crates.io one, so the lock file is enough and there
  # is no vendor hash to re-pin on every `npins update steamos-manager`.
  cargoLock.lockFile = "${src}/Cargo.lock";

  # The suite fakes a Steam Deck under FHS paths it builds in /usr.
  doCheck = false;

  # Three absolute paths are compiled in. Only these three are reachable
  # without Deck-only helpers behind them, so the rest of upstream's /usr
  # references are left to fail the individual D-Bus call that wants them —
  # BIOS updates and factory reset mean nothing on this machine anyway.
  #
  # The device config directory is deliberately *not* among them: the daemon
  # takes --device-config, which skips the DMI scan entirely, and that is how
  # configuration.nix points it at a board this repo describes itself.
  postPatch = ''
    substituteInPlace steamos-manager/src/platform.rs \
      --replace-fail /usr/share/steamos-manager $out/share/steamos-manager
    substituteInPlace steamos-manager/src/daemon/user.rs \
      --replace-fail /usr/share/steamos-manager $out/share/steamos-manager
  '';

  strictDeps = true;

  nativeBuildInputs = [
    glib
    pkg-config
    rustPlatform.bindgenHook
    wrapGAppsNoGuiHook
  ];

  buildInputs = [
    glib
    gsettings-desktop-schemas
    speechd-minimal
    udev
  ];

  # Upstream installs the daemon to /usr/lib rather than a bin directory, and
  # its own unit files name it there. steamosctl is the CLI half and stays on
  # PATH — it is what answers whether the TDP interface came up at all.
  postInstall = ''
    mkdir -p $out/lib
    mv $out/bin/steamos-manager $out/lib/steamos-manager

    install -D -m644 data/platform.toml -t $out/share/steamos-manager
    install -D -m644 data/interfaces/* -t $out/share/dbus-1/interfaces
    install -D -m644 data/system/com.steampowered.SteamOSManager1.conf \
      -t $out/share/dbus-1/system.d
  '';

  postFixup = ''
    wrapGApp $out/lib/steamos-manager
  '';

  meta = {
    description = "D-Bus API the Steam client uses for TDP and GPU clock control";
    homepage = "https://gitlab.steamos.cloud/holo/steamos-manager";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "steamosctl";
  };
}
