# Top-level package versions for one nixpkgs.
#
# This is pure evaluation and it costs about two seconds. Laziness is why:
# asking for a package's pname and version never forces its derivation, so
# nothing here touches the build graph and nothing is ever downloaded. That
# is the whole reason the app can answer "what changes for me" without a
# rebuild.
#
# The trade-off is that it sees top-level packages only. A library bump that
# rebuilds Firefox without changing its version is invisible here — the app
# covers that separately, by matching commit subjects against the store
# closure.
#
# Note what is *not* decided here: whether something is an app or a system
# package. Where a package is declared says nothing about that — Firefox
# arrives through a NixOS module and would look like a system package, while
# btop sits in home.packages and would look like an app. The app sorts that
# out afterwards, by which packages ship a desktop launcher.

{ nixpkgs, homeManager, repo }:

let
  pkgs = import nixpkgs { config.allowUnfree = true; };

  sys = (import "${nixpkgs}/nixos" {
    configuration = { imports = [ "${repo}/configuration.nix" ]; };
  }).config;

  hm = (import "${homeManager}/modules" {
    inherit pkgs;
    configuration = "${repo}/home.nix";
    check = false;
  }).config;

  # hardware.firmware is a single merged derivation in some nixpkgs revisions
  # and a list in others.
  asList = x: if builtins.isList x then x else [ x ];

  ident = p: {
    name = p.pname or p.name or "?";
    version = p.version or "";
  };
  idents = ps: map ident (builtins.filter (p: p ? outPath) (asList ps));
in

{
  # Everything the two configs name outright, in one bag. The split into
  # apps and system happens outside, on better evidence.
  declared = idents (hm.home.packages ++ sys.environment.systemPackages);

  # Graphics and kernel are worth their own category, and both are real
  # options rather than dependencies — hardware.graphics.package is mesa, so
  # a mesa bump shows up here as an honest version comparison.
  drivers = idents ([ sys.boot.kernelPackages.kernel
                      sys.hardware.graphics.package
                      sys.hardware.graphics.package32 ]
    ++ asList sys.hardware.graphics.extraPackages
    ++ asList sys.hardware.graphics.extraPackages32
    ++ asList sys.hardware.firmware);
}
