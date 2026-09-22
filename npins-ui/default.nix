# Packaging for npins-ui. Used from home.nix as `callPackage ./npins-ui { }`.

{ lib
, stdenvNoCC
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

  src = ./.;

  # gobject-introspection here (not in buildInputs) is what makes
  # wrapGAppsHook4 collect GI_TYPELIB_PATH for Gtk and Adw.
  nativeBuildInputs = [ wrapGAppsHook4 gobject-introspection ];
  buildInputs = [ gtk4 libadwaita pythonEnv ];

  installPhase = ''
    runHook preInstall

    install -Dm755 npins-ui.py $out/bin/npins-ui
    substituteInPlace $out/bin/npins-ui \
      --replace-fail '#!/usr/bin/env python3' '#!${pythonEnv}/bin/python3'

    install -Dm644 versions.nix $out/share/npins-ui/versions.nix
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
