# The native half of shaderbg: a ClutterEffect in C, reached from the
# extension as `gi://ShaderBg`. Called from ../default.nix, which carries it
# through as passthru.girLib.
#
# It is native for one reason that JavaScript cannot be talked into: the
# frame budget needs the GPU time of a single shader pass, and the only way
# to that number is a GL timer query. Cogl has no binding for one — mutter 50
# carries COGL_FEATURE_ID_TIMESTAMP_QUERY in its headers and no function to
# go with it — and GJS has no GL binding at all.

{ lib
, stdenv
, meson
, ninja
, pkg-config
, gobject-introspection
, mutter
, atk
, cairo
, glib
, graphene
, gsettings-desktop-schemas
, harfbuzz
, lcms2
, libGL
, libxkbcommon
, pango
, wayland
, libx11
, libxfixes
, libxi
}:

stdenv.mkDerivation {
  pname = "shaderbg-gir";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [
    meson
    ninja
    pkg-config
    gobject-introspection
  ];

  # mutter, and then what libmutter-18.pc lists under Requires:, directly or
  # through mutter-clutter-18. pkg-config walks that chain to produce the
  # cflags, so a missing one fails configure even though most of it is never
  # used by name here. pango and harfbuzz are not in that chain but in
  # Clutter-18.gir's, which g-ir-scanner reads to resolve ClutterEffect.
  buildInputs = [
    mutter
    atk
    cairo
    glib
    graphene
    gsettings-desktop-schemas
    harfbuzz
    lcms2
    libGL
    libxkbcommon
    pango
    wayland
    libx11
    libxfixes
    libxi
  ];

  # mutter keeps clutter and cogl in a private lib/mutter-18, which the .pc
  # files do not put on the link path. Inside gnome-shell both are already
  # loaded, but with the rpath the typelib is also loadable on its own, which
  # is what makes `gjs -c "imports.gi.ShaderBg"` a usable check.
  env.NIX_LDFLAGS = "-rpath ${mutter}/lib/mutter-18";

  meta = {
    description = "ShaderBg.Effect, the ClutterEffect that draws the shader";
    platforms = lib.platforms.linux;
  };
}
