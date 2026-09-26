# The two derivations a rebuild would realise, so nix can be asked what
# installing them would cost before any of it is fetched.
#
# Deliberately not part of versions.nix. That file promises to force no
# outPath and to cost about two seconds, and instantiating a whole system is
# neither: it writes the build graph out, which takes about fourteen seconds
# for the pair. Keeping them apart keeps that promise intact — and keeps the
# cheap answer cheap, which is the order the app asks its questions in.
#
# Same trade-off as versions.nix otherwise: nixpkgs and home-manager come in
# as arguments so the new pins can be evaluated without touching the repo,
# while the config files are read where they lie and so reach any *other*
# pin through their own `import ./npins` — nixpkgs-unstable, today. A move
# there is therefore not counted. It feeds one sandboxed program.

{ nixpkgs, homeManager, repo }:

let
  pkgs = import nixpkgs { config.allowUnfree = true; };
in

{
  # What `nixos-rebuild --file` builds, reached the same way it reaches it.
  system = (import "${nixpkgs}/nixos" {
    configuration = { imports = [ "${repo}/configuration.nix" ]; };
  }).system;

  # What `home-manager switch` builds. check = false because the assertions
  # are for a real switch; here the derivation is all that is wanted.
  home = (import "${homeManager}/modules" {
    inherit pkgs;
    configuration = "${repo}/home.nix";
    check = false;
  }).activationPackage;
}
