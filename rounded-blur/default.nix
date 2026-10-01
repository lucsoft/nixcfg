# Packaging for kancko/gnome-rounded-blur, the `gi://Blur` library that
# blur-my-shell looks for. Called from home.nix with the npins source.

{ lib
, stdenv
, src
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
, lcms2
, libGL
, libxkbcommon
, wayland
, libx11
, libxfixes
, libxi
}:

stdenv.mkDerivation {
  pname = "gnome-rounded-blur";
  version = "1.0.1";

  inherit src;

  nativeBuildInputs = [
    meson
    ninja
    pkg-config
    gobject-introspection
  ];

  # meson.build names libmutter-18 literally, which is the ABI mutter 50 ships.
  # A mutter bump moves that number, and this fails to configure rather than
  # building something the Shell would refuse to load.
  #
  # The rest is what libmutter-18.pc lists under Requires:, directly or through
  # mutter-clutter-18. pkg-config walks that chain to produce the cflags, so a
  # missing one fails configure even though none of it is used by name here.
  buildInputs = [
    mutter
    atk
    cairo
    glib
    graphene
    gsettings-desktop-schemas
    lcms2
    libGL
    libxkbcommon
    wayland
    libx11
    libxfixes
    libxi
  ];

  # mutter keeps clutter and cogl in a private lib/mutter-18, which the .pc
  # files do not put on the link path. Inside gnome-shell both are already
  # loaded, but with the rpath the typelib is also loadable on its own, which
  # is what makes `gjs -c "imports.gi.Blur"` a usable check.
  env.NIX_LDFLAGS = "-rpath ${mutter}/lib/mutter-18";

  meta = {
    description = "Blur.BlurEffect with corner radius, for blur-my-shell";
    homepage = "https://github.com/kancko/gnome-rounded-blur";
    license = lib.licenses.gpl3Plus;
    platforms = lib.platforms.linux;
  };
}
