# Packaging for wpebg. Used from home.nix as `callPackage ./wpebg { }`.

{ lib
, stdenvNoCC
, glib
, callPackage
}:

let
  uuid = "wpebg@lucsoft.de";

  # The player and the effect, in C, reached from extension.js as
  # `gi://WpeBg`. Passthru so home.nix can put it on GI_TYPELIB_PATH.
  girLib = callPackage ./lib { };
in

stdenvNoCC.mkDerivation {
  pname = "gnome-shell-extension-wpebg";
  version = "0.1.0";

  src = ./.;

  # glib for glib-compile-schemas; the compiled schema has to sit next to
  # extension.js, see shaderbg/default.nix.
  nativeBuildInputs = [ glib ];

  installPhase = ''
    runHook preInstall

    dir=$out/share/gnome-shell/extensions/${uuid}

    install -Dm644 metadata.json extension.js prefs.js workshop.js -t $dir

    install -Dm644 schemas/de.lucsoft.wpebg.gschema.xml \
      $dir/schemas/de.lucsoft.wpebg.gschema.xml
    glib-compile-schemas $dir/schemas

    runHook postInstall
  '';

  passthru = {
    extensionUuid = uuid;
    inherit girLib;
  };

  meta = {
    description = "Plays a Wallpaper Engine video wallpaper as the GNOME desktop background";
    platforms = lib.platforms.linux;
  };
}
