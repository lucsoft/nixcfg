# Far Cry 3 mods

The tooling is installed and works; no mod is applied yet, because the game
still has to be downgraded first. See [Where this stands](#where-this-stands).

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
It writes ~11 GB to
`~/.local/share/Steam/steamapps/content/app_220240/depot_220241`, leaving the
installation untouched. Copy that over
`~/.local/share/Steam/steamapps/common/Far Cry 3`, replacing — with the game
closed.

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

### Packaging ReShade, if it comes to that

No `reshade` attribute exists in the pin. Two routes, both checked:

- `programs.steam.extraCompatPackages = [ pkgs.steamtinkerlaunch ]` —
  SteamTinkerLaunch (12.12 in the pin) has a ReShade installer, handles the
  32/64-bit DLL split, and pulls its shader-repository list from PCGamingWiki.
  Imperative, but immediate.
- Our own derivation, in the shape of `fc-mod-installer`: `fetchurl` on
  `https://reshade.me/downloads/ReShade_Setup_6.6.0_Addon.exe` (reachable and
  hash-pinnable), `p7zip` to extract `ReShade32.dll`, shader repos via
  `fetchFromGitHub`.

**vkBasalt is not a substitute.** It is in the pin, and `pkgs.vkbasalt` does
ship the 32-bit layer manifest a 32-bit game needs — verified: it carries both
`vkBasalt.json` and `vkBasalt32.json`, and the loader skips the wrong-bitness
one with `wrong bit-type` instead of failing. It would work here. But vkBasalt
has no depth buffer, so it cannot do ambient occlusion or GI at all — only
colour and sharpening.

## Where this stands

Done: the Mod Installer is packaged, runs, and has Rakyat staged.

Not done, and both need a person:

1. **The downgrade** — `download_depot` is a GUI action in the Steam client.
2. **A lighting/texture mod** — REBORN and the rest are Nexus downloads, and
   Nexus requires an account. fcmodding.com does not, which is why Rakyat
   could be fetched automatically and REBORN could not.

[^downgrade]: [Downgrade to 1.05 to enable mods](https://steamcommunity.com/sharedfiles/filedetails/?id=3360740938), and [Far Cry 3 Downgrade v1.06 to v1.05](https://www.nexusmods.com/farcry3/mods/196).
[^conflict]: [Ziggy's Mod comments](https://www.nexusmods.com/farcry3/mods/63?tab=posts) and [Far Cry 3 Redux discussion](https://steamcommunity.com/app/220240/discussions/0/1642043732655502658/).
[^depth]: [Depth Buffer in Far Cry 3, ReShade forum](https://reshade.me/forum/shader-troubleshooting/544-solved-depth-buffer-in-far-cry-3).
[^protondb]: [ProtonDB, Far Cry 3](https://www.protondb.com/app/220240).
[^msaa]: [dxvk#2863, waterfalls show corruption with MSAA](https://github.com/doitsujin/dxvk/issues/2863).
