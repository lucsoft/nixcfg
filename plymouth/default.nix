# The plymouth theme used at boot. Pulled in from configuration.nix as
# `callPackage ./plymouth { }`.

{ runCommand, imagemagick }:

runCommand "plymouth-theme-nixos"
  {
    nativeBuildInputs = [ imagemagick ];
  }
  ''
    dir=$out/share/plymouth/themes/nixos
    mkdir -p "$dir"

    # The bar is two solid tiles that the script scales to size, so the
    # repository stays free of binary assets. Blue is the lighter of the two
    # colours in the NixOS logo.
    magick -size 512x8 xc:'#ffffff' "$dir/bar-track.png"
    magick -size 512x8 xc:'#7ebae4' "$dir/bar-fill.png"

    cp ${./nixos.script} "$dir/nixos.script"

    # Absolute store paths here: the NixOS module rewrites them when it
    # copies the theme into the initrd, and the running system reads the
    # theme from /etc/plymouth/themes, where relative paths would not resolve.
    cat > "$dir/nixos.plymouth" <<EOF
    [Plymouth Theme]
    Name=NixOS
    Description=NixOS logo, a boot progress bar and the unit being started
    ModuleName=script

    [script]
    ImageDir=$dir
    ScriptFile=$dir/nixos.script
    EOF
  ''
