# Far Cry Mod Installer — upstream's own Linux build, for modding Far Cry 3.
#
# Two things stop this from being an ordinary package:
#
#   * The binary is a self-contained .NET/Avalonia build that asks for
#     /lib64/ld-linux-x86-64.so.2, so it runs through steam-run's FHS env
#     rather than being patched. Nothing here is built from source.
#   * It writes next to itself — settings, and the ModifiedFilesFC3 folder
#     that mod packages are dropped into. A store path is read-only, so the
#     wrapper seeds a writable copy on first run and launches that.
#
# Avalonia dlopen()s libICE and libSM, and steam-run's environment carries
# neither; without them it dies in AvaloniaX11Platform.Initialize before a
# window ever appears. Hence extraLibs on LD_LIBRARY_PATH.
{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
  writeShellApplication,
  steam-run,
  symlinkJoin,
  libice,
  libsm,
}:

let
  version = "20250412-1300";

  payload = stdenvNoCC.mkDerivation {
    pname = "fc-mod-installer-payload";
    inherit version;

    src = fetchurl {
      url = "https://downloads.fcmodding.com/files/FCModInstallerLinux.zip";
      sha256 = "10cc2llmfrkyp6gj43svg1d4wp180569yvlbz9ajh0wa16zhsdq0";
    };

    nativeBuildInputs = [ unzip ];
    sourceRoot = "FCModInstaller";

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -r . "$out"/

      # The zip carries no Unix permission bits, so everything lands at 444
      # and the launcher cannot be executed. Restore the bit on the binaries.
      chmod +x "$out"/bin/DuniaModInstaller "$out"/FC*ModInstaller "$out"/FCSavegameManager

      runHook postInstall
    '';

    # Prebuilt foreign binaries: stripping or patching them only breaks things.
    dontFixup = true;
  };

  extraLibs = symlinkJoin {
    name = "fc-mod-installer-libs";
    paths = [ libice libsm ];
  };
in
writeShellApplication {
  name = "fc-mod-installer";
  runtimeInputs = [ steam-run ];

  text = ''
    dir="''${XDG_DATA_HOME:-$HOME/.local/share}/fc-mod-installer"

    if [ ! -e "$dir" ]; then
      mkdir -p "$dir"
      # Keep the modes — dropping them costs the executable bit — and only add
      # the write permission the store path lacks.
      cp -r --no-preserve=ownership ${payload}/. "$dir"/
      chmod -R u+w "$dir"
      echo "fc-mod-installer: seeded $dir"
      echo "fc-mod-installer: put mod packages (.bin) in $dir/ModifiedFilesFC3"
    fi

    cd "$dir/bin"

    # -game=fc3 skips the game picker; any other argument is passed straight on
    # (-game=fc5, -saves, ...).
    exec steam-run env LD_LIBRARY_PATH=${extraLibs}/lib \
      ./DuniaModInstaller "''${@:--game=fc3}"
  '';

  meta = {
    description = "Mod installer for the Far Cry Dunia-engine games";
    homepage = "https://fcmodding.com/";
    platforms = [ "x86_64-linux" ];
    # Upstream ships binaries only, with no licence grant attached.
    license = lib.licenses.unfree;
    mainProgram = "fc-mod-installer";
  };
}
