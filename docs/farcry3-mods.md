# Far Cry 3 mods

The game is downgraded to 1.05 and ReShade is installed. What is still open is
the texture pack and one Steam setting — see
[Where this stands](#where-this-stands).

Far Cry 3 is Steam app `220240`, installed at
`~/.local/share/Steam/steamapps/common/Far Cry 3`.

## Starting point, verified on this machine

Checked 2026-09-25/26, before any change:

| thing | value | how it was checked |
|---|---|---|
| game version | 1.06 | depot `220241` manifest `5896142001500010150` in `appmanifest_220240.acf` — 1.05 is a different manifest |
| executables | **both 32-bit** | PE machine type `014c` in `bin/farcry3.exe` and `bin/farcry3_d3d11.exe` |
| compat tool | Proton Experimental 11.0-100 | `compatdata/220240/version` |
| launch options | none set | no `LaunchOptions` for 220240 in `localconfig.vdf` |
| renderer | D3D11, MSAA 4× | `UseD3D11="1" MSAALevel="4"` in `GamerProfile.xml` |

The 32-bit finding matters later: every DLL an injector puts next to the
executable has to be the 32-bit build, and so does any Vulkan layer.

## Two different mod mechanisms

Far Cry 3 mods arrive in two incompatible shapes, and conflating them is the
main source of confusion:

1. **Mod Installer packages** (`.bin`) — installed by the Far Cry Mod
   Installer, which patches the game's Dunia archives itself and knows which
   packages conflict. Packaged here as `fc-mod-installer`.
2. **Raw archive replacements** (`patch.fat` + `patch.dat` dropped into
   `data_win32/`) — how the Nexus overhauls ship. No tooling, no conflict
   detection; two of them cannot coexist without being merged by hand with
   the Gibbed.Dunia2 tools.

The Mod Installer's own FAQ asks for "clean, unmodified game files", so
mechanism 1 on top of mechanism 2 is not supported. Pick a lane.

## The downgrade comes first, either way

Far Cry 3 modding targets game version **1.05**; Steam ships 1.06 and the
mods do not load against it.[^downgrade]

With Steam **running** (the console is part of the client), open
`steam://open/console` and enter:

    download_depot 220240 220241 7362101836779063707

That command is quoted verbatim from the guide, not reconstructed.[^downgrade]
It writes ~12 GB and leaves the installation untouched.

**It does not land where the guides say.** They all name
`steamapps/content/app_220240/depot_220241`; this client actually wrote to

    ~/.local/share/Steam/ubuntu12_32/steamapps/content/app_220240/depot_220241

Take the path from the console's own "Depot download complete" line rather
than from any guide. Then, with the game closed:

    cp -a "<that path>/." ~/.local/share/Steam/steamapps/common/"Far Cry 3"/

Done here on 2026-09-26, with the replaced files kept in `~/fc3-backup-1.06`
(315 files, 12 GB). Verified afterwards: `bin/FC3.dll` dropped from 40 720 424
to 29 994 856 bytes and `farcry3.exe` from 203 816 to 202 088 — that size
change is the cheapest proof that 1.05 is really in place.

Nothing needs to be told to Steam afterwards: copying files does not touch
`appmanifest_220240.acf`, so Steam still believes 1.06 is installed and will
not re-patch. What *does* undo it is "verify integrity of game files", which
compares checksums and restores 1.06 along with removing every mod.

## What is installed here

`home.nix` carries `fc-mod-installer` — upstream's own Linux build of the Far
Cry Mod Installer, pinned by hash. Run it as:

    fc-mod-installer            # defaults to -game=fc3
    fc-mod-installer -saves     # savegame manager

On first run it seeds a writable copy at
`~/.local/share/fc-mod-installer`, because the tool writes next to itself and
a store path is read-only. Mod packages go in that copy's
`ModifiedFilesFC3/`.

Game detection does not work: the Linux build only probes the Steam Deck's
`/home/deck/...` path, so it opens a "game dir was not found" dialog. Point it
at

    ~/.local/share/Steam/steamapps/common/Far Cry 3/bin/farcry3.exe

`Ctrl+L` gives a path entry in the GTK file dialog; `.local` is hidden
otherwise.

Already placed in `ModifiedFilesFC3/`: **Rakyat mod** v1.28.1, downloaded from
fcmodding.com — no account needed, unlike Nexus.

### Two NixOS-specific fixes, both in `fc-mod-installer/default.nix`

- The binary is a self-contained .NET/Avalonia build asking for
  `/lib64/ld-linux-x86-64.so.2`, so it runs through `steam-run`.
- Avalonia `dlopen()`s **libICE and libSM**, which steam-run's environment
  does not carry. Without them it dies in `AvaloniaX11Platform.Initialize`
  before a window appears — the failure looks like a crash, not a missing
  library. They go on `LD_LIBRARY_PATH`.
- The upstream zip stores no Unix permission bits, so everything unpacks at
  `444` and the launcher is not executable. The derivation restores it.

## What Rakyat is, and is not

93 packages, individually selectable, with conflict detection in the UI. It is
a **gameplay and weapon collection**: weapon behaviour, loot and XP rates,
outfits, skipped intros, `Play as Vaas`, `2nd Island Start`.

The only visual entries are `E3 Ocean`, `Realistic Water`, `Rain`, `Wind`,
`HitEffects` and `Clean Camera`. **There is nothing for lighting and nothing
for textures.** If the goal is how the game looks, Rakyat is the wrong tool,
however convenient its installer is.

## The texture pack that is installed

**Mud's Mod v5.3, "Vanilla Game HD Textures only"** — the variant matters:
the other builds bundle gameplay changes, this one is textures and nothing
else. It replaces `data_win32/patch.fat` and `patch.dat`, the latter growing
from 202 MB to 970 MB. The 1.05 originals are kept in
`~/fc3-backup-textures`.

The German localisation lives in its own `patch_german.*` pair and is not
touched.

### Why its GamerProfile.xml was not used

The archive ships one, and the README calls replacing it "VERY IMPORTANT ...
THIS PREVENTS THE MOD FROM CRASHING". It was deliberately not installed,
because it sets `UseD3D11="1"` and `MSAALevel="4"` — exactly what the depth
buffer cannot work with. Taking it would trade ReShade's ambient occlusion
and GI away.

Comparing it against the existing profile shows most of it is simply the
author's own setup: English, gamepad on, his FOV, his contrast and gamma,
VSync off, HUD hints disabled. The parts that plausibly relate to the mod:

| setting | his | kept here |
|---|---|---|
| `GeometryQuality` | ultrahigh | high |
| `ShadowQuality` | veryhigh | high |
| `WaterQuality` | veryhigh | high |
| `PostFxQuality` | ultrahigh | high |
| `DeferredAmbientQuality` | high | medium |
| `SSAOLevel` | 1 | 6 |
| `Quality` | High | ultrahigh |

Note the shape of it: sub-qualities raised, overall `Quality` and `SSAO`
lowered. A plausible reading is memory pressure — **the game is 32-bit, so it
has roughly 4 GB of address space**, and a 970 MB texture set eats into that.
That is a hypothesis, not something established here, which is why none of
these were applied to a working configuration on spec.

If the game crashes or stutters, they are the dials, in this order: `Quality`
to `High`, then `SSAOLevel` to `1` — the latter is worth doing anyway once
`dh_uber_rt` runs, since two ambient-occlusion passes stacked on each other
look wrong.

## For lighting and textures

These are mechanism 2 — raw archive drops — and all of them are on Nexus,
which requires an account to download.

| mod | what it gives |
|---|---|
| [Far Cry 3 REBORN](https://www.nexusmods.com/farcry3/mods/227) | total overhaul that **bundles an HD texture pack** (4Aces/KMA). Current release is 3.1. Casual / Regular / Hardcore variants differ in how much minimap survives. |
| [Far Cry 3: Redux](https://www.moddb.com/mods/far-cry-3-redux) | balance-focused overhaul listing "improved fire and lighting". Brings no textures. |
| [Mud's Mod Ultra HD v5.3](https://www.nexusmods.com/farcry3/mods/200) | textures only, built for DX11. |
| [Ziggy's Mod](https://www.nexusmods.com/farcry3/mods/63) | the largest overhaul, aimed at a harder game. |

**Redux and Ziggy's cannot be combined** — they conflict over the same
DLL.[^conflict] For "better lighting and better textures with the least
assembly", REBORN is the one to take: it is the only one that already contains
the texture work, which avoids a Gibbed merge.

## If ReShade is added later

Ambient occlusion and any screen-space GI need the depth buffer, and Far Cry 3
is unusual here:

- **The depth buffer is only readable in DX9 mode**; in DX11 it stays
  empty.[^depth] DX11 is also reported broken under Proton for this
  game.[^protondb] So `UseD3D11="0"`, and hook `bin/farcry3.exe`, not
  `farcry3_d3d11.exe`.
- **MSAA has to be off.** ReShade cannot read a multisampled depth buffer, and
  DXVK additionally corrupts this game's waterfalls with MSAA on.[^msaa] Set
  `MSAALevel="0"` and use SMAA inside ReShade.
- The injected DLL is `d3d9.dll` and must be **ReShade32.dll** renamed. Launch
  option: `WINEDLLOVERRIDES="d3d9=n,b" %command%`.

`GamerProfile.xml` lives in the Proton prefix:

    ~/.steam/steam/steamapps/compatdata/220240/pfx/drive_c/users/steamuser/Documents/My Games/Far Cry 3/GamerProfile.xml

This pulls against Mud's Mod, which is built for DX11. Textures via DX11 or
depth-buffer effects via DX9 — not both.

On shaders: Marty McFly's **RTGI** is paid (Patreon). Free screen-space
alternatives are **YASSGI**, **dh_rtgi** from
[AlucardDH's pack](https://github.com/AlucardDH/dh-reshade-shaders),
**RadiantGI**, and the artifact-hardened presets in
[RTShade](https://github.com/DHYCIX/RTShade). Expect mixed results: a 2012
jungle full of volumetric fog gives screen-space GI little to work with, since
light leaving the frame stops existing for it.

### The d3dcompiler trap

First launch produced 66 red entries in the overlay — every single effect
failing with

    E5002: Static variables cannot have both numeric and resource components

which reads like 66 broken shaders and is one missing DLL. ReShade's D3D9
backend calls `D3DCompile` out of `d3dcompiler_47.dll`, and the Proton prefix
carries only Wine's stub: 370 547 bytes against Microsoft's 3 681 592. What
makes it easy to miss is that `d3dcompiler_43.dll` *is* native in the same
`system32`, so nothing looks absent.

`fc3-reshade` now installs the real one next to the executable, lifted out of
a Firefox installer the way winetricks does it. The launch options must name
it too:

    WINEDLLOVERRIDES="d3d9=n,b;d3dcompiler_47=n" %command%

After that: 65 of 66 effects compile. The one holdout is `dh_ahoh.fx`, on
`error X3535: Bitwise operations not supported on target ps_3_0` — the DX9
shader model, not something to fix. Anything reaching for bitwise operations
will fail the same way, which is the standing cost of the DX9 route.

### How it is packaged

No `reshade` attribute exists in the pin, so `fc3-reshade` in `home.nix` does
it: `fetchurl` on `ReShade_Setup_6.6.0_Addon.exe`, `p7zip` to pull
`ReShade32.dll` out of the zip appended to that self-extracting installer, and
four shader packs via `fetchFromGitHub`.

    fc3-reshade             # install, or re-install after a Steam verify
    fc3-reshade uninstall

It is a command, not a Home Manager activation, because Steam owns the game
directory and "verify integrity" clears whatever is put there — a file
activation would fight it on every switch.

Which shader packs to take is not guesswork: ReShade's installer drives itself
from `EffectPackages.ini` on the `list` branch of `crosire/reshade-shaders`,
and these are four of its entries.

| pack | why |
|---|---|
| `crosire/reshade-shaders` @ `slim` | carries `ReShade.fxh`, which every other pack includes. Not optional despite a tiny effect list. |
| `crosire/reshade-shaders` @ `legacy` | `AmbientLight`, `Bloom`, `MagicBloom` — the lighting side. |
| `CeeJayDK/SweetFX` | **SMAA**, plus CAS, LumaSharpen, Tonemap, Vibrance, Curves. |
| `AlucardDH/dh-reshade-shaders` | `dh_uber_rt` (GI, AO, reflections) and `dh_ambient_remove`. |

66 effects in total. SMAA is the one to notice: disabling MSAA for the depth
buffer leaves the game with no anti-aliasing at all, and SMAA is what puts it
back. It lives in SweetFX, not in either crosire branch — which is not
obvious, and is why the package list came from upstream's own INI.

`dh_ambient_remove` belongs with `dh_uber_rt`: it takes the game's baked
ambient light out, so the computed bounce is not laid on top of the old one.
The game's own `SSAOLevel` is left at 6 in `GamerProfile.xml` — if the result
is too dark once `dh_uber_rt` runs, that is the first dial to turn down.

**vkBasalt is not a substitute.** It is in the pin, and `pkgs.vkbasalt` does
ship the 32-bit layer manifest a 32-bit game needs — verified: it carries both
`vkBasalt.json` and `vkBasalt32.json`, and the loader skips the wrong-bitness
one with `wrong bit-type` instead of failing. It would work here. But vkBasalt
has no depth buffer, so it cannot do ambient occlusion or GI at all — only
colour and sharpening.

## Where this stands

The goal settled on is **visuals only, gameplay untouched**. That rules out
every overhaul in the table above, REBORN included: its headline features are
a crafting overhaul, rebalanced enemy damage, changed carry capacities and
all skills unlocked from the start. It is a gameplay mod that happens to ship
textures, not the reverse.

So the split is: textures from a texture-only pack, lighting from ReShade.
Neither touches gameplay.

Done:

- Game downgraded to 1.05, with `~/fc3-backup-1.06` holding what was replaced.
- `GamerProfile.xml` set to `UseD3D11="0"` and `MSAALevel="0"`; the previous
  file is kept beside it as `GamerProfile.xml.before-reshade`.
- ReShade 6.6.0 plus 66 effects installed via `fc3-reshade`.
- `fc-mod-installer` packaged and working, though the visuals-only decision
  means it is not needed for now.

- Mud's Mod v5.3 "Vanilla Game HD Textures only" installed; originals in
  `~/fc3-backup-textures`.

Open:

1. **Steam launch options** — `WINEDLLOVERRIDES="d3d9=n,b" %command%`, set in
   the client. Cannot be written to `localconfig.vdf` from outside while
   Steam is running, because it rewrites that file on exit.
2. **Nothing has actually been run yet.** Every check so far was on file
   sizes and logs, and two questions only launching answers:
   - Do the HD textures load in DX9? They live in the Dunia archives rather
     than in the renderer, so they should, but the pack advertises DX11 and
     its author ships a DX11 profile.
   - Does a 32-bit process hold 970 MB of textures at `ultrahigh` without
     running out of address space? If not, see the table above.

[^downgrade]: [Downgrade to 1.05 to enable mods](https://steamcommunity.com/sharedfiles/filedetails/?id=3360740938), and [Far Cry 3 Downgrade v1.06 to v1.05](https://www.nexusmods.com/farcry3/mods/196).
[^conflict]: [Ziggy's Mod comments](https://www.nexusmods.com/farcry3/mods/63?tab=posts) and [Far Cry 3 Redux discussion](https://steamcommunity.com/app/220240/discussions/0/1642043732655502658/).
[^depth]: [Depth Buffer in Far Cry 3, ReShade forum](https://reshade.me/forum/shader-troubleshooting/544-solved-depth-buffer-in-far-cry-3).
[^protondb]: [ProtonDB, Far Cry 3](https://www.protondb.com/app/220240).
[^msaa]: [dxvk#2863, waterfalls show corruption with MSAA](https://github.com/doitsujin/dxvk/issues/2863).
