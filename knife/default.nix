{ lib, stdenv, fetchurl, autoPatchelfHook, makeWrapper, copyDesktopItems
, makeDesktopItem, libxkbcommon, libxcb, libx11, libxcursor, libxi
, libglvnd, wayland, libpulseaudio, alsa-lib, xdg-utils }:

# The Knife ships as a prebuilt tarball that installs itself into
# ~/.local. Its binaries find their helpers next to /proc/self/exe, so they
# stay together in one directory. Graphics, input and audio libraries are
# dlopened, hence runtimeDependencies rather than NEEDED entries. The URL
# always serves the newest preview, so the hash breaks on every release;
# the version is whatever channels.json in the same folder says.
stdenv.mkDerivation rec {
  pname = "the-knife";
  version = "0.2.1";

  src = fetchurl {
    url = "https://file.paperclover.net/shr/the-knife/the-knife-x86_64-linux.tar.xz";
    hash = "sha256-j5WWLc6CqiDJTDqat+bl7U4UEU53CVHGy4efLAWPWxw=";
  };

  nativeBuildInputs = [ autoPatchelfHook makeWrapper copyDesktopItems ];
  buildInputs = [ stdenv.cc.cc.lib libxkbcommon libxcb ];

  runtimeDependencies = [
    libxkbcommon libxcb libx11 libxcursor libxi libglvnd wayland
    libpulseaudio alsa-lib
  ];

  dontStrip = true;

  installPhase = ''
    runHook preInstall
    # The bundled xkbcommon/xcb copies give way to nixpkgs'.
    rm -r lib install.sh net.paperclover.knife.preview.desktop
    mkdir -p $out/lib/knife-preview
    cp -r . $out/lib/knife-preview
    install -Dm644 knife.png \
      $out/share/icons/hicolor/64x64/apps/net.paperclover.knife.preview.png
    makeWrapper $out/lib/knife-preview/knife-preview $out/bin/knife-preview \
      --prefix PATH : ${lib.makeBinPath [ xdg-utils ]}
    runHook postInstall
  '';

  desktopItems = [
    (makeDesktopItem {
      name = "net.paperclover.knife.preview";
      desktopName = "The Knife";
      exec = "knife-preview";
      icon = "net.paperclover.knife.preview";
      startupWMClass = "net.paperclover.knife.preview";
      categories = [ "Development" ];
    })
  ];

  meta = {
    description = "The Knife, a desktop app for coding agents";
    homepage = "https://paperclover.net";
    license = lib.licenses.unfree;
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
    platforms = [ "x86_64-linux" ];
    mainProgram = "knife-preview";
  };
}
