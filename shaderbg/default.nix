# Packaging for shaderbg. Used from home.nix as `callPackage ./shaderbg { }`.

{ lib
, stdenvNoCC
, glib
, callPackage
}:

let
  uuid = "shaderbg@lucsoft.de";
  sources = import ./sources.nix;

  # The ClutterEffect, in C, reached from extension.js as `gi://ShaderBg`.
  # Carried through as passthru so home.nix needs one callPackage and not two;
  # it has to put girLib on GI_TYPELIB_PATH for the Shell to find it.
  girLib = callPackage ./lib { };
in

stdenvNoCC.mkDerivation {
  pname = "gnome-shell-extension-shaderbg";
  version = "0.1.0";

  src = ./.;

  # glib is here for glib-compile-schemas. A Shell extension reads its schema
  # out of its own directory, not out of the session's schema path, so the
  # compiled file has to land next to extension.js rather than in
  # share/glib-2.0 where glib's own hook would relocate it.
  nativeBuildInputs = [ glib ];

  # sources.nix is the configuration and JSON is what the extension reads.
  # Converting here rather than at runtime means a malformed list fails the
  # build instead of leaving the rotation quietly short.
  sourcesJson = builtins.toJSON sources;
  passAsFile = [ "sourcesJson" ];

  installPhase = ''
    runHook preInstall

    dir=$out/share/gnome-shell/extensions/${uuid}

    install -Dm644 metadata.json $dir/metadata.json
    install -Dm644 extension.js  $dir/extension.js
    install -Dm644 prefs.js      $dir/prefs.js
    install -Dm644 "$sourcesJsonPath" $dir/sources.json

    install -Dm644 schemas/de.lucsoft.shaderbg.gschema.xml \
      $dir/schemas/de.lucsoft.shaderbg.gschema.xml
    glib-compile-schemas $dir/schemas

    install -dm755 $dir/shaders
    install -Dm644 shaders/*.frag -t $dir/shaders

    # A shader named in sources.nix but missing from shaders/ would only show
    # up on the one day it came round, which could be six weeks out.
    for want in ${lib.escapeShellArgs (map (s: s.file) sources)}; do
      if [ ! -f "$dir/shaders/$want" ]; then
        echo "shaderbg: sources.nix names shaders/$want, which does not exist" >&2
        exit 1
      fi
    done

    runHook postInstall
  '';

  # programs.gnome-shell takes the UUID from here to write enabled-extensions.
  passthru = {
    extensionUuid = uuid;
    inherit girLib;
  };

  meta = {
    description = "Draws a Shadertoy fragment shader as the GNOME desktop background";
    platforms = lib.platforms.linux;
  };
}
