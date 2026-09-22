# Entry point for the system configuration (NixOS 26.05+).
#
# nixpkgs is pinned by npins (see npins/sources.json), so rebuilds are
# reproducible and cannot drift when the channel moves underneath you. It
# replaces the need for `nix-channel` on the system side — without flakes.
#
# Apply with:
#
#     sudo nixos-rebuild switch --file ~/nixcfg
#
# To move to a newer nixpkgs:
#
#     npins update --dry-run   # what would move
#     npins update             # rev and hash, fetched and written for you

let
  sources = import ./npins;
in
import "${sources.nixpkgs}/nixos" {
  configuration = {
    imports = [ ./configuration.nix ];
  };
}
