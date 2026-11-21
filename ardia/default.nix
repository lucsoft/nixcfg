{ appimageTools, fetchurl, makeWrapper, stdenv, autoPatchelfHook, cacert
, python313 }:

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

  # The control CLI ships inside the AppImage; the app would otherwise
  # install its own copy into ~/.local. Its launcher runs the Python next to
  # it, but patchelf breaks that standalone Python ("undefined symbol"), so
  # nixpkgs' 3.13 stands in, carrying the bundled packages. Python has no
  # idea where NixOS keeps CA certificates, hence SSL_CERT_FILE.
  cliTarball = "${contents}/lib/ardia/cli/ardia-cli-${version}-linux-x64.tar.gz";

  cliPackages = stdenv.mkDerivation {
    pname = "ardia-cli-packages";
    inherit version;
    src = cliTarball;
    nativeBuildInputs = [ autoPatchelfHook ];
    passthru.pythonModule = python313;
    installPhase = ''
      mkdir -p $out/${python313.sitePackages}
      cp -r python/lib/python3.13/site-packages/{ardia_cli,websockets} \
        $out/${python313.sitePackages}
    '';
  };

  cli = stdenv.mkDerivation {
    pname = "ardia-cli";
    inherit version;
    src = cliTarball;
    nativeBuildInputs = [ autoPatchelfHook makeWrapper ];
    buildInputs = [ stdenv.cc.cc.lib ];
    installPhase = ''
      install -Dm755 bin/ardia $out/lib/ardia-cli/bin/ardia
      makeWrapper ${python313.buildEnv.override { extraLibs = [ cliPackages ]; }}/bin/python3 \
        $out/lib/ardia-cli/python/bin/python3
      makeWrapper $out/lib/ardia-cli/bin/ardia $out/bin/ardia \
        --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    '';
  };
in
appimageTools.wrapType2 {
  inherit pname version src;

  # XWayland until ardia-browser/ardia#3340 is fixed: on native Wayland a
  # tab dragged in the sidebar moves the whole window instead.
  #
  # The browser and the CLI both want to be `ardia`. A bare word first
  # (`ardia config …`) or a CLI flag goes to the CLI; URLs, browser flags
  # and no arguments go to the browser.
  extraInstallCommands = ''
    source ${makeWrapper}/nix-support/setup-hook
    mv $out/bin/ardia $out/bin/ardia-browser
    wrapProgram $out/bin/ardia-browser --add-flags --ozone-platform=x11

    cat > $out/bin/ardia <<'EOF'
    #!${stdenv.shell}
    case "''${1-}" in
      -h|--help|--version|--skill|--port*|--ws*|--data-dir*|--timeout*|--json)
        exec ${cli}/bin/ardia "$@" ;;
      *[.:/]*) ;;
      [a-z]*) exec ${cli}/bin/ardia "$@" ;;
    esac
    exec @out@/bin/ardia-browser "$@"
    EOF
    substituteInPlace $out/bin/ardia --replace-fail @out@ $out
    chmod +x $out/bin/ardia

    install -Dm444 ${contents}/ardia.desktop $out/share/applications/ardia.desktop
    substituteInPlace $out/share/applications/ardia.desktop \
      --replace-fail 'Exec=AppRun' 'Exec=ardia-browser'
    install -Dm444 ${contents}/ardia.png \
      $out/share/icons/hicolor/256x256/apps/ardia.png
  '';
}
