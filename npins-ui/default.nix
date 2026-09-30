# Packaging for npins-ui. Used from home.nix as `callPackage ./npins-ui { }`.

{ lib
, stdenvNoCC
, glib
, python3
, wrapGAppsHook4
, gobject-introspection
, gtk4
, libadwaita
, makeDesktopItem
, adwaita-icon-theme
, hicolor-icon-theme
, npins
, git
, nix
}:

let
  pythonEnv = python3.withPackages (ps: [ ps.pygobject3 ]);

  # The file name has to be the application ID exactly. That is how the
  # shell ties a running window back to its desktop entry — get it wrong and
  # the window shows up nameless, with a fallback icon, no matter how well
  # the icon itself is installed.
  desktopItem = makeDesktopItem {
    name = "de.lucsoft.NpinsUi";
    desktopName = "Pins";
    comment = "Check for nixpkgs and Home Manager updates";
    exec = "npins-ui";
    icon = "de.lucsoft.NpinsUi";
    categories = [ "System" "Settings" ];
    startupWMClass = "de.lucsoft.NpinsUi";   # the XWayland fallback path
  };
in

stdenvNoCC.mkDerivation {
  pname = "npins-ui";
  version = "0.2.0";

  # Not ./. on its own. Running the app from a checkout now imports a package
  # rather than one script, so Python leaves __pycache__ beside it — and a
  # plain path import folds that into the derivation hash, which rebuilds
  # npins-ui and everything downstream of it for nothing. Nix does not read
  # .gitignore, so the filter has to say it here too.
  src = lib.cleanSourceWith {
    name = "npins-ui-source";
    src = ./.;
    filter = path: type:
      !(type == "directory" && baseNameOf path == "__pycache__");
  };

  # gobject-introspection here (not in buildInputs) is what makes
  # wrapGAppsHook4 collect GI_TYPELIB_PATH for Gtk and Adw.
  # glib is here for glib-compile-schemas. Its own hook only relocates a
  # schema directory into share/gsettings-schemas and points the wrapper at
  # it — compiling is the package's job, and nothing else in this build
  # would do it.
  nativeBuildInputs = [ wrapGAppsHook4 gobject-introspection glib ];
  buildInputs = [ gtk4 libadwaita pythonEnv ];

  installPhase = ''
    runHook preInstall

    # The launcher is the only file that becomes a binary; the package it
    # imports goes on PYTHONPATH below, beside the two .nix expressions.
    install -Dm755 npins-ui.py $out/bin/npins-ui
    substituteInPlace $out/bin/npins-ui \
      --replace-fail '#!/usr/bin/env python3' '#!${pythonEnv}/bin/python3'

    mkdir -p $out/share/npins-ui
    cp -r npins_ui $out/share/npins-ui/

    # Byte-compile into the store, for two reasons. $out is read-only, so
    # without this every run reparses the package and caches nothing. And
    # compileall exits non-zero on a syntax error, which is the only thing
    # standing between a typo in app.py or headless.py and the timer: both
    # are imported lazily by __main__, so nothing until then would parse
    # them. It does not import, so it catches syntax and not much else.
    #
    # unchecked-hash because the store normalises every mtime to 1970 — the
    # default timestamp check would then invalidate the cache it just wrote.
    ${pythonEnv}/bin/python3 -m compileall -q \
      --invalidation-mode unchecked-hash $out/share/npins-ui/npins_ui

    install -Dm644 de.lucsoft.NpinsUi.gschema.xml \
      $out/share/glib-2.0/schemas/de.lucsoft.NpinsUi.gschema.xml
    glib-compile-schemas $out/share/glib-2.0/schemas

    install -Dm644 versions.nix $out/share/npins-ui/versions.nix
    install -Dm644 sizes.nix $out/share/npins-ui/sizes.nix
    install -Dm644 de.lucsoft.NpinsUi.svg \
      $out/share/icons/hicolor/scalable/apps/de.lucsoft.NpinsUi.svg
    mkdir -p $out/share
    cp -r ${desktopItem}/share/applications $out/share/

    runHook postInstall
  '';

  preFixup = ''
    gappsWrapperArgs+=(
      # npins, git and nix-instantiate are shelled out to, so they have to be
      # on the app's PATH rather than only in the profile that installed it.
      --prefix PATH : ${lib.makeBinPath [ npins git nix ]}
      --set NPINS_UI_EVAL $out/share/npins-ui/versions.nix

      # Where npins_ui itself lives. The launcher in bin/ only adds its own
      # directory to sys.path, which is what makes running from a checkout
      # work; installed, this is the line that finds the package.
      --prefix PYTHONPATH : $out/share/npins-ui

      # The icon themes have to be named here. Putting them in buildInputs
      # populates XDG_ICON_DIRS but wrapGAppsHook4 no longer folds that into
      # the wrapper, so every symbolic icon would resolve only by luck of
      # whatever the session happens to export. hicolor-icon-theme is also
      # what supplies the index.theme this package's own icon needs.
      --prefix XDG_DATA_DIRS : ${adwaita-icon-theme}/share:${hicolor-icon-theme}/share
    )
  '';

  meta = {
    description = "Adwaita front end for npins";
    mainProgram = "npins-ui";
    platforms = lib.platforms.linux;
  };
}
