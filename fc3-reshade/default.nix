# ReShade for Far Cry 3, with the free screen-space GI and AO shaders.
#
# Far Cry 3 is a 32-bit game, so this is ReShade32.dll — the 64-bit build in
# the same installer is the one every guide reaches for and it does nothing
# here. It is dropped in as d3d9.dll, not dxgi.dll, because only the game's
# DX9 renderer exposes a readable depth buffer; in DX11 it stays empty and
# every ambient-occlusion or GI shader silently does nothing.
#
# The game directory is not ours to manage declaratively — Steam owns it, and
# "verify integrity of game files" wipes whatever we put there. So this is a
# command that installs on demand and can simply be re-run, rather than a
# Home Manager activation that would fight Steam over the same files.
{
  lib,
  fetchurl,
  fetchFromGitHub,
  stdenvNoCC,
  p7zip,
  writeShellApplication,
  writeText,
}:

let
  version = "6.6.0";

  # The installer is a self-extracting archive; the DLLs sit in a zip appended
  # to it, which p7zip reads directly.
  reshade = stdenvNoCC.mkDerivation {
    pname = "reshade-dll";
    inherit version;

    src = fetchurl {
      url = "https://reshade.me/downloads/ReShade_Setup_${version}_Addon.exe";
      sha256 = "0dhx6v3ms3fyjf08h8pyvwwbdxqm5jp829nlkmkw8y9l6a09bism";
    };

    nativeBuildInputs = [ p7zip ];
    dontUnpack = true;
    dontFixup = true;

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      7z x -y -o"$out" "$src" ReShade32.dll ReShade64.dll >/dev/null
      runHook postInstall
    '';
  };

  # Without this, every single effect fails to compile with
  #
  #   E5002: Static variables cannot have both numeric and resource components
  #
  # which reads like broken shaders but is not: ReShade's D3D9 backend calls
  # D3DCompile out of d3dcompiler_47.dll, and Proton's prefix carries only
  # Wine's built-in stub of it — 370 KB against Microsoft's 3.7 MB. Oddly
  # d3dcompiler_43 *is* native in there, just not the one that gets used.
  #
  # Microsoft does not redistribute the DLL on its own, so winetricks lifts it
  # out of a Firefox installer, which ships it legitimately. Same trick here,
  # with the version winetricks pins.
  d3dcompiler47 = stdenvNoCC.mkDerivation {
    pname = "d3dcompiler_47";
    version = "62.0.3";

    src = fetchurl {
      url = "https://download-installer.cdn.mozilla.net/pub/firefox/releases/62.0.3/win32/ach/Firefox%20Setup%2062.0.3.exe";
      sha256 = "1jharivk78v6iknp6v2ax12nwz2j0zzfvfhrpmz42gvi1bzv9vfn";
    };

    nativeBuildInputs = [ p7zip ];
    dontUnpack = true;
    dontFixup = true;

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      7z e -y -o"$out" "$src" core/d3dcompiler_47.dll >/dev/null
      test -s "$out/d3dcompiler_47.dll"
      runHook postInstall
    '';
  };

  # Which packs to take is not guesswork: ReShade's installer drives itself
  # from EffectPackages.ini in the repository's `list` branch, and these are
  # four of the entries it offers.
  #
  # The headers every other pack includes (ReShade.fxh) live in `slim`, so it
  # is not optional even though its own effect list is tiny.
  stockShaders = fetchFromGitHub {
    owner = "crosire";
    repo = "reshade-shaders";
    rev = "fd0022170615ce0d8162d219bff07232fa6dd84f";
    sha256 = "0f35av37r9r4fm3nl98syldzxpg7lflyilyv25ric8zbrv5d9lks";
  };

  # AmbientLight, Bloom, MagicBloom — the lighting side of this.
  legacyShaders = fetchFromGitHub {
    owner = "crosire";
    repo = "reshade-shaders";
    rev = "bcb5ba54199f4455026dd8ba66dc1b74461d3152";
    sha256 = "055dfmrrcrrm28xap9qx1pf20xh3rslfh8c808h25ikzp3dzbha7";
  };

  # Carries SMAA, which matters here: the depth buffer forces MSAA off, so
  # the game needs some anti-aliasing put back. Also CAS, LumaSharpen and the
  # colour-grading effects that take Far Cry 3's yellow cast out.
  sweetFX = fetchFromGitHub {
    owner = "CeeJayDK";
    repo = "SweetFX";
    rev = "407c11562950195c1b45461fbb59f4bd6bbe7ba4";
    sha256 = "1i8ssph9iilvlcc7r6qh3igzd8jfrm51kn576v8b0lniqamh3rgv";
  };

  # dh_uber_rt — screen-space GI, ambient occlusion and reflections, and free.
  # Marty McFly's RTGI, the one most demonstrations show, is Patreon-only.
  # dh_ambient_remove belongs with it: it takes the game's baked-in ambient
  # light out so the computed bounce is not added on top of the old one.
  dhShaders = fetchFromGitHub {
    owner = "AlucardDH";
    repo = "dh-reshade-shaders";
    rev = "0783b8fde77df48412d79070be7de4bc3743b898";
    sha256 = "09i6r2rrqvjc6wl8q4z3884sg1vaw64fmsk5a5wi3n7j6bbsan8f";
  };

  shaderPacks = [
    stockShaders
    legacyShaders
    sweetFX
    dhShaders
  ];

  # ReShade reads this from next to the DLL. Without the search paths it
  # starts with an empty effect list and looks broken.
  iniFile = writeText "ReShade.ini" ''
    [GENERAL]
    EffectSearchPaths=.\reshade-shaders\Shaders\**
    TextureSearchPaths=.\reshade-shaders\Textures\**
    PresetPath=.\ReShadePreset.ini
    PerformanceMode=0

    [INPUT]
    KeyOverlay=36,0,0,0

    [SCREENSHOT]
    SavePath=.\reshade-screenshots
  '';
in
writeShellApplication {
  name = "fc3-reshade";

  text = ''
    game="''${FC3_DIR:-$HOME/.local/share/Steam/steamapps/common/Far Cry 3}"
    bin="$game/bin"

    if [ ! -f "$bin/farcry3.exe" ]; then
      echo "fc3-reshade: no farcry3.exe under $bin" >&2
      echo "fc3-reshade: set FC3_DIR to the game directory" >&2
      exit 1
    fi

    case "''${1:-install}" in
      install)
        install -Dm644 ${reshade}/ReShade32.dll "$bin/d3d9.dll"

        # Seed the settings once, then never again: ReShade writes the depth
        # buffer choice and every tweak back into this file, and re-running
        # the installer after a Steam verify must not throw that away.
        if [ ! -f "$bin/ReShade.ini" ]; then
          install -Dm644 ${iniFile} "$bin/ReShade.ini"
          echo "fc3-reshade: wrote a fresh ReShade.ini"
        else
          echo "fc3-reshade: kept the existing ReShade.ini"
        fi

        # Next to the executable, so Wine finds it ahead of its own stub in
        # system32 — and so a Proton prefix rebuild cannot take it away.
        install -Dm644 ${d3dcompiler47}/d3dcompiler_47.dll "$bin/d3dcompiler_47.dll"

        rm -rf "$bin/reshade-shaders"
        mkdir -p "$bin/reshade-shaders/Shaders" "$bin/reshade-shaders/Textures"

        # Packs disagree about nesting — SweetFX keeps its effects in a
        # subdirectory, the crosire ones do not. Copying each pack's tree as
        # it comes keeps both working, because EffectSearchPaths recurses.
        for pack in ${lib.concatStringsSep " " shaderPacks}; do
          if [ -d "$pack/Shaders" ]; then
            cp -r --no-preserve=mode,ownership \
              "$pack/Shaders/." "$bin/reshade-shaders/Shaders/"
          fi
          if [ -d "$pack/Textures" ]; then
            cp -r --no-preserve=mode,ownership \
              "$pack/Textures/." "$bin/reshade-shaders/Textures/"
          fi
        done

        echo "fc3-reshade: installed into $bin"
        echo "fc3-reshade: $(find "$bin/reshade-shaders/Shaders" -name '*.fx' | wc -l) effects available"
        echo
        echo "Two things the game itself still needs:"
        echo "  1. GamerProfile.xml: UseD3D11=\"0\" and MSAALevel=\"0\""
        echo "     (DX11 has no readable depth buffer; MSAA depth cannot be read at all)"
        echo "  2. Steam launch options:"
        echo "     WINEDLLOVERRIDES=\"d3d9=n,b;d3dcompiler_47=n\" %command%"
        echo "     Both halves matter — without the second, every effect fails to"
        echo "     compile against Wine's stub compiler."
        echo
        echo "The overlay opens with Home."
        ;;

      uninstall)
        rm -fv "$bin/d3d9.dll" "$bin/ReShade.ini" "$bin/d3dcompiler_47.dll"
        rm -rf "$bin/reshade-shaders"
        echo "fc3-reshade: removed"
        ;;

      *)
        echo "usage: fc3-reshade [install|uninstall]" >&2
        exit 1
        ;;
    esac
  '';

  meta = {
    description = "Install ReShade plus free GI/AO shaders into Far Cry 3";
    homepage = "https://reshade.me/";
    platforms = [ "x86_64-linux" ];
    license = lib.licenses.unfree;
    mainProgram = "fc3-reshade";
  };
}
