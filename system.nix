# Entry point for the system configuration (NixOS 26.05+).
#
# This pins nixpkgs to an exact commit, so rebuilds are reproducible and
# cannot drift when the channel moves underneath you. It replaces the need
# for `nix-channel` on the system side — without using flakes.
#
# Apply with:
#
#     sudo nixos-rebuild switch --file ~/nixcfg
#
# To move to a newer nixpkgs later:
#   1. Pick a commit from github.com/NixOS/nixpkgs/commits/nixos-26.05
#   2. nix-prefetch-url --unpack https://github.com/NixOS/nixpkgs/archive/<rev>.tar.gz
#   3. Update rev/sha256/versionSuffix below, then rebuild

let
  rev = "cf9d2fb3e50fa1cd5114c47505ea9177f7ff5f49";

  nixpkgs = builtins.fetchTarball {
    # nixos-26.05 as of 2026-09-19
    url = "https://github.com/NixOS/nixpkgs/archive/${rev}.tar.gz";
    sha256 = "16fa6vir35h0pajdrs1ws7d3ly28ifks2g9y67y3j7zw1hqyqm3h";
  };
in
import "${nixpkgs}/nixos" {
  configuration = {
    imports = [ ./configuration.nix ];

    # A GitHub tarball has no .git-revision / .version-suffix, so without this
    # the system would label itself "26.05pre-git" in the boot menu and in
    # `nixos-version`. Restore the real identity.
    system.nixos.revision = rev;
    system.nixos.versionSuffix = ".10057.cf9d2fb3e50f";
  };
}
