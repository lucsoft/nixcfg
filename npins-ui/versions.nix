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

  firmware = asList sys.hardware.firmware;

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

  # The two things a rebuild cannot put into use on its own get a bag each,
  # because "what changed" and "what you have to do about it" are different
  # questions. A mesa bump is settled by logging out; a kernel bump is
  # settled by nothing short of a reboot.
  kernel = idents ([ sys.boot.kernelPackages.kernel ] ++ firmware);

  graphics = idents ([ sys.hardware.graphics.package
                       sys.hardware.graphics.package32 ]
    ++ asList sys.hardware.graphics.extraPackages
    ++ asList sys.hardware.graphics.extraPackages32
    ++ asList sys.fonts.packages);

  # What a reboot would put into use, as store paths. A system generation
  # keeps the same four under the same names, so comparing these against
  # /run/booted-system answers "reboot?" outright — where a version diff
  # cannot: a kernel can be rebuilt without its version moving, and the
  # firmware derivation carries no version at all.
  #
  # These are the only outPaths forced anywhere in this file, and they are
  # nearly free: the system evaluation they need has already happened above.
  boot = {
    kernel = sys.boot.kernelPackages.kernel.outPath;
    initrd = sys.system.build.initialRamdisk.outPath;
    kernel-modules = sys.system.modulesTree.outPath;
    # One merged derivation is also what /run/*/firmware points at. Were a
    # revision to hand back a real list, the merge happens during activation
    # and cannot be reproduced from here — so say nothing rather than guess.
    firmware = if builtins.length firmware == 1
               then (builtins.head firmware).outPath
               else "";
  };
}
