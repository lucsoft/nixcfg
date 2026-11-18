# The native half of wpebg: a GStreamer player and the ClutterEffect that
# draws its frames, reached from the extension as `gi://WpeBg`. Called from
# ../default.nix, which carries it through as passthru.girLib.
#
# Native because a frame is several megabytes, and that is not something to
# copy through GJS thirty times a second inside the compositor.

{ lib
, stdenv
, meson
, ninja
, pkg-config
, gobject-introspection
, mutter
, gst_all_1
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

let
  # The Shell's wrapper already has core, base and good on its plugin path.
  # bad brings the VA decoders and the parsers in front of them, libav the
  # software fallback. All five are listed so the library does not depend on
  # what the wrapper happens to carry; scanning one twice costs nothing.
  plugins = with gst_all_1; [
    gstreamer
    gst-plugins-base
    gst-plugins-good
    gst-plugins-bad
    gst-libav
  ];
in

stdenv.mkDerivation {
  pname = "wpebg-gir";
  version = "0.1.0";

  src = ./.;

  nativeBuildInputs = [
    meson
    ninja
    pkg-config
    gobject-introspection
  ];

  # mutter and what its .pc files pull in, as in shaderbg/lib.
  buildInputs = [
    mutter
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
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

  mesonFlags = [
    (lib.mesonOption "plugin_path"
      (lib.makeSearchPathOutput "lib" "lib/gstreamer-1.0" plugins))
  ];

  env.NIX_LDFLAGS = "-rpath ${mutter}/lib/mutter-18";

  meta = {
    description = "WpeBg.Player and WpeBg.Effect, the video wallpaper's native half";
    platforms = lib.platforms.linux;
  };
}
