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

### The version it wants, and the downgrade that should not have happened

**The 1.05 downgrade was a requirement of REBORN, and REBORN was then not
installed.** When the goal settled on visuals-only, the overhaul was dropped
but the version change stayed — a leftover from an abandoned decision.

It surfaced as cars wearing leaf textures. That is the signature of an asset
*mismatch* rather than a broken file: the Dunia archives resolve assets by ID,
and a texture pack built against a different base version puts the right
texture behind the wrong ID. Mud's Mod ships no version requirement in its
README, but the archive is dated January 2024, long after 1.06 became the
retail build — so 1.06 is what it was made against.

Restored to 1.06 on 2026-09-26 from `~/fc3-backup-1.06`, with the texture pack
re-applied afterwards; restoring first and re-applying second matters, or the
backup's vanilla `patch.dat` wins.

A second benefit: Steam's `appmanifest` always said 1.06, so files and
bookkeeping now agree again, and there is no pending update to fear.

The lesson worth keeping: **the version the game needs follows from the mod
that is actually installed**, and that has to be re-checked whenever the mod
choice changes. Downgrade because a mod demands it, not by default — 1.06 is
the version everything else expects.

### Its GamerProfile.xml is not optional — the README is right

The archive ships one, and the README calls replacing it "VERY IMPORTANT ...
THIS PREVENTS THE MOD FROM CRASHING". That was initially dismissed, because
its `UseD3D11="1"` and `MSAALevel="4"` are exactly what ReShade's depth buffer
cannot use. Dismissing it was wrong: with his file installed verbatim, DX11
loads a savegame; with ours, it dies every time.

Two readings of that file were wrong along the way and are worth recording so
they are not repeated:

- **"It is mostly his personal settings."** Partly true — English, his FOV,
  his 2560×1440 — but not the whole story, since it demonstrably fixes the
  crash.
- **"The rest is memory tuning."** Flatly wrong. This came from a comparison
  script that matched the wrong attribute: `Quality` appears 17 times in the
  file, and sorting picked a sub-element rather than the one on
  `RenderProfile`. His `RenderProfile` `Quality` is `ultrahigh`, the same as
  ours, and every sub-quality he sets is *higher*, not lower:

  | | his | ours was |
  |---|---|---|
  | `GeometryQuality` | ultrahigh | high |
  | `ShadowQuality` | veryhigh | high |
  | `WaterQuality` | veryhigh | high |
  | `PostFxQuality` | ultrahigh | high |
  | `DeferredAmbientQuality` | high | medium |

The settings he has that we did not, and which are the actual candidates:
`Borderless="1"` (exclusive fullscreen is a known irritant under DXVK),
`GPUMaxBufferedFrames="0"`, `VSync="0"`.

Lesson: when a mod author ships a config and says it is required, test it
verbatim before reasoning about which parts matter. Reasoning first cost
several launches here, and one of the arguments was based on a bad grep.

### What of his profile was actually needed

His file also carries `MSAALevel="4"`, which ReShade cannot work with — a
multisampled depth buffer is unreadable. So the configuration that kept the
game alive looked like the one that ruled out ambient occlusion and GI.

It was resolved by walking his settings back toward ours one at a time,
each step verified by loading the same savegame:

| step | changed | result |
|---|---|---|
| 0 | his file verbatim | loads |
| 1 | resolution to 3440×1440, language to German | loads |
| 2 | `MSAALevel` to `0`, ReShade re-installed as `dxgi.dll` | loads |

So neither the resolution nor MSAA was load-bearing, and neither is ReShade.
What remains of his that we do not otherwise set: **`Borderless="1"`**,
`GPUMaxBufferedFrames="0"`, `VSync="0"`. Exclusive fullscreen is a known
irritant under DXVK, which makes `Borderless` the likely one — though that was
not isolated further, because the configuration works.

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

Ambient occlusion and any screen-space GI need the depth buffer, which is the
whole reason the renderer mattered here.

**The widely repeated claim that Far Cry 3's depth buffer only works in DX9 is
wrong**, at least with ReShade 6 under DXVK. It comes from a 2013 forum
post[^depth] and was taken at face value for most of this work. Tested on
2026-09-26: under DX11 the buffer is populated, `DisplayDepth` shows real
geometry, and the buffer matches the 3440×1440 swap chain instead of the
2560×1440 mismatch DX9 produced. ProtonDB's "DX11 is broken under Proton" for
this game[^protondb] did not reproduce either.

What does hold:

- **MSAA has to be off** in either mode — a multisampled depth buffer cannot
  be read, and DXVK additionally corrupts this game's waterfalls with MSAA
  on.[^msaa] `MSAALevel="0"`, and SMAA inside ReShade instead.
- The injected DLL is **ReShade32.dll** renamed — 32-bit, since both
  executables are — as `dxgi.dll` for DX11 or `d3d9.dll` for DX9.

DX9 is still a working fallback (`fc3-reshade dx9`), but it costs the shader
model 3 ceiling: `dh_ahoh.fx` fails there on `X3535: Bitwise operations not
supported on target ps_3_0`, 65 of 66 effects instead of all of them. And it
pulls against the texture pack, which is built for DX11.

`GamerProfile.xml` lives in the Proton prefix:

    ~/.steam/steam/steamapps/compatdata/220240/pfx/drive_c/users/steamuser/Documents/My Games/Far Cry 3/GamerProfile.xml

On shaders: Marty McFly's **RTGI** is paid (Patreon). Free screen-space
alternatives are **YASSGI**, **dh_rtgi** from
[AlucardDH's pack](https://github.com/AlucardDH/dh-reshade-shaders),
**RadiantGI**, and the artifact-hardened presets in
[RTShade](https://github.com/DHYCIX/RTShade). Expect mixed results: a 2012
jungle full of volumetric fog gives screen-space GI little to work with, since
light leaving the frame stops existing for it.

### The depth buffer reads backwards by default

Finding a depth buffer is not the same as reading it correctly. With the right
buffer selected, `DisplayDepth` still showed **surface normals but a blank
depth map** — and switching between buffers changed nothing, which is the tell
that the buffer is not the problem.

`RESHADE_DEPTH_INPUT_IS_REVERSED` defaults to `1` in `ReShade.fxh`, and Far Cry
3 does not use reversed-Z; it predates the practice. Left at the default,
`depth = 1.0 - depth` pushes every value against the end of the range and the
depth view goes flat white. Normals survive it, because they are built from
differences between neighbouring pixels — so the picture looks like "there is
depth here" while every distance the GI computes is wrong.

    RESHADE_DEPTH_INPUT_IS_REVERSED=0

set under "Edit global preprocessor definitions", and seeded into the
`ReShade.ini` that `fc3-reshade` writes. The live preview in `DisplayDepth`
deliberately *ignores* preprocessor definitions, so getting the preview right
changes nothing for `dh_uber_rt` until the global definition is set too.

`RESHADE_DEPTH_INPUT_IS_LOGARITHMIC` makes no visible difference here, and the
arithmetic says why: with `C = 0.01`, the transform is
`(exp(d·log(1.01)) − 1) / 0.01`, and since `log(1.01) ≈ 0.00995` with
`exp(x) ≈ 1 + x` at that scale, the whole thing reduces to about `d × 0.995`.
Near enough to the identity to see nothing. Leave it off.

### Picking the depth buffer

The Generic Depth add-on lists candidates by resolution and draw calls, and
draw-call count alone is misleading: a 1024×1024 shadow map can carry more
draw calls than the scene buffer, because it redraws much of the world from a
light's point of view. Selecting one renders a landscape from an unfamiliar
angle — recognisable once seen.

Take the entry matching the swap chain. Under DX11 that is
`3440x1440 | D24S8 | 1102 draw calls | 2663919 vertices`, and because it
matches the aspect ratio, `Aspect ratio heuristic` can stay on "Similar aspect
ratio" and will find it again by itself after a restart. Setting that
heuristic to "None" is what surfaces the square shadow maps as candidates in
the first place.

Under DX9 no such buffer exists: the widest candidate was 2560×1440 against a
3440×1440 image, which has to be picked by hand and never matches.

### Motion vectors have to be produced, and ordered

ReShade never receives motion vectors from the game — it sees a finished frame
and a depth buffer, nothing else. A separate effect has to estimate them and
write them into a shared texture.

`dh_uber_rt` picks its source by preprocessor definition:
`USE_MARTY_LAUNCHPAD_MOTION`, `USE_VORT_MOTION`, or — with both left at `0`,
which is the default — a texture called `texMotionVectors`. AlucardDH's pack
already ships the matching producer, `dh_uber_motion.fx`, declaring that exact
name in the same `RG16F` format, so nothing extra needs installing. It just
has to be enabled.

**Order matters**: ReShade runs techniques in list order, so
`DH_UBER_MOTION_020` has to sit above `dh_uber_rt`, or the vectors read are
the ones not yet written this frame. Check it with the shader's own
Debug → `Display` → `Motion` view: panning the camera should tint the frame
evenly; a black field means the wiring is not live.

Without them, temporal accumulation cannot reproject, so every camera movement
restarts the estimate — which is most of the noise that denoiser settings get
blamed for.

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

### DX11 was tried, and it crashes

The DX9 choice rested on a 2013 forum post. It was tested properly on
2026-09-26, and the post turns out to be wrong about the part it is quoted
for — but DX11 is unusable here anyway.

What DX11 does deliver, from the ReShade log:

- The device comes up: `D3D11CreateDevice` succeeds, `Using feature level
  b000` — feature level 11_0 under DXVK. ProtonDB's "DirectX 11 is broken
  under Proton" does not hold for startup.
- **66 of 66 effects compile, zero failures.** `dh_ahoh.fx`, which fails on
  DX9 with `X3535: Bitwise operations not supported on target ps_3_0`, goes
  through. Shader model 5 removes that ceiling entirely.

And then the game dies while loading a savegame. Ruled out, in order:

| suspected | test | result |
|---|---|---|
| ReShade | renamed `dxgi.dll` away, launched clean | crashes anyway |
| 2 GB address space | set `IMAGE_FILE_LARGE_ADDRESS_AWARE` on both executables — neither ships it, so they are capped at 2 GB while a 970 MB texture pack is loaded | crashes anyway |

No Wine crash dump and no game log is written, so there is nothing to read
without `PROTON_LOG=1`. The untried lever is `Quality="ultrahigh"`, which the
texture pack's author ships as `High` — the reading that his profile is memory
tuning is still open.

DX9 is where this stays, because DX9 runs. The cost is the shader model 3
ceiling and one dead effect out of 66.

The LAA patch was left in place; it is harmless and may help DX9 too. It lives
in the executable, so a Steam file verification reverts it — along with the
mods.

### Overrides belong in the prefix, not in the launch options

`WINEDLLOVERRIDES` in Steam's launch options has to be rewritten every time
the renderer changes, and it is easy to leave pointing at the wrong DLL. The
same thing goes into the prefix registry once, scoped per executable, and then
never needs touching:

    [Software\\Wine\\AppDefaults\\farcry3.exe\\DllOverrides]
    "d3d9"="native,builtin"
    "d3dcompiler_47"="native"

    [Software\\Wine\\AppDefaults\\farcry3_d3d11.exe\\DllOverrides]
    "dxgi"="native,builtin"
    "d3dcompiler_47"="native"

Whichever executable runs picks up the override that belongs to it, so
switching renderer is only `fc3-reshade dx9` or `dx11` — the file on disk
decides, and the registry is right either way.

Two things to know when editing `user.reg` by hand:

- Wine holds the registry in memory and writes it out when the **last**
  process in the prefix exits. Editing under a live prefix loses the edit
  silently, and Uplay lingers after the game closes — wait for that too.
- **An environment variable beats the registry.** Leaving
  `WINEDLLOVERRIDES` in the launch options overrides these entries, so it has
  to be cleared or the registry rules are dead weight.

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
