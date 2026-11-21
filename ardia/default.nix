{ appimageTools, fetchurl }:

# Ardia ships Linux only as nightlies, with no Flatpak and nothing in
# nixpkgs; the AppImage is the one format that carries its own libraries.
# Its launcher runs Chromium's sandbox through user namespaces, which NixOS
# allows, so it needs no setuid helper. A nightly is never "latest" on
# GitHub, so the version below moves by hand.
let
  pname = "ardia";
  version = "0.2.47-nightly.9";

  src = fetchurl {
    url = "https://github.com/ardia-browser/ardia/releases/download/v${version}/Ardia-${version}-linux-x64.AppImage";
    hash = "sha256-Iav2Aq2RNQV6dtZq2ox0RxYt4WtPcKbMHwzbKPR9miw=";
  };

  contents = appimageTools.extract { inherit pname version src; };
in
appimageTools.wrapType2 {
  inherit pname version src;

  extraInstallCommands = ''
    install -Dm444 ${contents}/ardia.desktop $out/share/applications/ardia.desktop
    substituteInPlace $out/share/applications/ardia.desktop \
      --replace-fail 'Exec=AppRun' 'Exec=ardia'
    install -Dm444 ${contents}/ardia.png \
      $out/share/icons/hicolor/256x256/apps/ardia.png
  '';
}
