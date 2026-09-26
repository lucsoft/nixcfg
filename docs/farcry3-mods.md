# Far Cry 3 mods

**Status: researched and prepared, not executed.** Two steps need a human —
see [What is blocked](#what-is-blocked). Everything below that is either
verified on this machine or sourced; the distinction is marked per section.

Far Cry 3 is Steam app `220240`, installed at
`~/.local/share/Steam/steamapps/common/Far Cry 3`.

## Starting point, verified on this machine

Checked 2026-09-25, before any change:

| thing | value | how it was checked |
|---|---|---|
| game version | 1.06 | depot `220241` manifest `5896142001500010150` in `appmanifest_220240.acf` — the 1.05 manifest is a different one |
| executables | **both 32-bit** | PE machine type `014c` in `bin/farcry3.exe` and `bin/farcry3_d3d11.exe` |
| compat tool | Proton Experimental 11.0-100 | `compatdata/220240/version` |
| launch options | none set | `localconfig.vdf` has no `LaunchOptions` for 220240 |
| renderer | D3D11, MSAA 4× | `UseD3D11="1" MSAALevel="4"` in `GamerProfile.xml` |

The 32-bit finding is the one that trips people up: every DLL a mod or an
injector puts next to the executable has to be the 32-bit build, and so does
any Vulkan layer.

Mods live in `data_win32/`, which is a set of Dunia archive pairs
(`patch.fat` + `patch.dat` and friends). Overhauls ship a replacement
`patch.fat`/`patch.dat`.

## What is blocked

Neither of these can be done from an agent session:

1. **The downgrade to 1.05.** It needs `download_depot` typed into the Steam
   client console — a GUI action, and an ~11 GB download.
2. **The mod downloads.** Nexus Mods requires an account, and both Nexus and
   ModDB answer automated requests with HTTP 403.

## Why a downgrade comes first

Far Cry 3 modding targets game version **1.05**. Steam ships 1.06, and the
overhauls do not load against it.[^downgrade] So the order is: downgrade,
*then* install a mod.

In the Steam client, open the console (Steam is already running, so the
`steam://open/console` URL reaches it) and run:

    download_depot 220240 220241 7362101836779063707

> The manifest ID `7362101836779063707` comes from community guides and could
> not be checked against SteamDB or the Steam Community pages — both
> rate-limited or refused the request at the time of writing. If it is wrong,
> Steam answers with an error and nothing is downloaded or overwritten, so it
> is safe to simply try.

That writes roughly 11 GB to
`~/.local/share/Steam/steamapps/content/app_220240/depot_220241`. There is
room: the root filesystem had 467 GB free. Copy its contents over
`~/.local/share/Steam/steamapps/common/Far Cry 3`, replacing.

Then stop Steam from patching back to 1.06: game properties → Updates → *Only
update this game when I launch it*. A "verify integrity of game files" run
undoes the downgrade and every mod with it.

## Picking one overhaul

**Far Cry 3: Redux and Ziggy's Mod cannot be combined** — they conflict over
the same DLL.[^conflict] So it is one or the other, not both.

| mod | what it is |
|---|---|
| [Far Cry 3 REBORN](https://www.nexusmods.com/farcry3/mods/227) | total overhaul that **bundles an HD texture pack** (4Aces/KMA). Ships in Casual / Regular / Hardcore variants, differing in how much minimap survives. |
| [Far Cry 3: Redux](https://www.moddb.com/mods/far-cry-3-redux) | overhaul aimed at balance rather than difficulty; lists "improved fire and lighting" as a feature. No textures — those would have to be merged in separately. |
| [Ziggy's Mod](https://www.nexusmods.com/farcry3/mods/63) | the largest overhaul, but pointed at a harder, more punishing game. |

For "better lighting and better textures with the least assembly", **REBORN**
is the one to take: it is the only one of the three that already contains the
texture work, which sidesteps the merging problem below entirely.

## Installing an overhaul

Overhauls are installed by dropping their files into `data_win32/`, replacing
what is there.[^install] Back up the pair that gets replaced first — it is
only ~200 MB, not the whole 12 GB directory:

    cd ~/.local/share/Steam/steamapps/common/"Far Cry 3"/data_win32
    cp -v patch.fat patch.dat ~/fc3-vanilla-backup/

One machine-specific wrinkle: this install also carries
`patch_german.fat`/`patch_german.dat`. German localisation is a separate
archive, so a mod's text changes may not surface while the game runs in
German, even though its world and texture changes will.

## Merging a separate texture pack

Only needed if the overhaul does not bring its own textures — i.e. if Redux or
Ziggy's is chosen over REBORN. Two packs are in circulation:
[Mud's Mod Ultra HD v5.3](https://www.nexusmods.com/farcry3/mods/200) and
[HD Texture Pack (upscaled)](https://www.nexusmods.com/farcry3/mods/291), the
latter quadrupling each texture's edge length.

Both ship as their own `patch.*` pair, so they and the overhaul want the same
file. Combining them means unpacking both with the **Gibbed.Dunia2** tools
(`Gibbed.Dunia2.Unpack.exe`) and repacking the union.[^conflict] Those are
Windows .NET binaries — on this machine they would have to run under Wine,
most simply inside the game's existing Proton prefix.

This is the step worth avoiding. Choosing REBORN removes it.

## If ReShade is added later

Relevant because ambient occlusion and any screen-space GI need the depth
buffer, and Far Cry 3 has an unusual constraint:

- **The depth buffer is only readable in DX9 mode.** In DX11 it stays
  empty.[^depth] DX11 is also reported broken under Proton for this
  game.[^protondb] So: `UseD3D11="0"` in `GamerProfile.xml`, and hook
  `bin/farcry3.exe`, not `farcry3_d3d11.exe`.
- **MSAA has to be off.** ReShade cannot read a multisampled depth buffer, and
  DXVK additionally corrupts Far Cry 3's waterfalls with MSAA on.[^msaa] Set
  `MSAALevel="0"` and use SMAA inside ReShade instead.
- The injected DLL is `d3d9.dll`, and it must be **ReShade32.dll** renamed —
  see the 32-bit finding above. Launch option:
  `WINEDLLOVERRIDES="d3d9=n,b" %command%`.

`GamerProfile.xml` lives inside the Proton prefix, at

    ~/.steam/steam/steamapps/compatdata/220240/pfx/drive_c/users/steamuser/Documents/My Games/Far Cry 3/GamerProfile.xml

Note this pulls in the opposite direction from Mud's Mod, which is built for
DX11. Textures via DX11 or depth-buffer effects via DX9 — not both.

On shaders: Marty McFly's **RTGI**, the one most demos show, is paid
(Patreon). Free screen-space alternatives are **YASSGI**, **dh_rtgi** from
[AlucardDH's pack](https://github.com/AlucardDH/dh-reshade-shaders),
**RadiantGI**, and the artifact-hardened presets in
[RTShade](https://github.com/DHYCIX/RTShade). Expect mixed results: a 2012
jungle full of volumetric fog gives screen-space GI little to work with, since
light leaving the frame stops existing for it.

### The packaging side

Nothing here is in nixpkgs: there is no `reshade` attribute in the pin. There
are two routes, both checked:

- `programs.steam.extraCompatPackages = [ pkgs.steamtinkerlaunch ]` —
  SteamTinkerLaunch (12.12 in the pin) has a full ReShade installer, handles
  the 32/64-bit DLL split itself, and pulls its shader-repository list from
  PCGamingWiki. Imperative and GUI-driven, but immediate.
- A derivation of our own: `fetchurl` on
  `https://reshade.me/downloads/ReShade_Setup_6.6.0_Addon.exe` (reachable,
  hash-pinnable), `p7zip` to extract `ReShade32.dll`, shader repos via
  `fetchFromGitHub`, and a Home Manager activation to place them. Reproducible
  and repo-managed, and it survives a Steam file verification because the
  activation puts everything back.

**vkBasalt is not a substitute.** It is in the pin, and `pkgs.vkbasalt` does
carry the 32-bit layer manifest that a 32-bit game needs — verified: the
package ships both `vkBasalt.json` and `vkBasalt32.json`, and the Vulkan
loader skips the wrong-bitness one with `wrong bit-type` rather than failing.
It would work on Far Cry 3. But vkBasalt has no depth buffer, so it cannot do
ambient occlusion or GI at all — only colour and sharpening.

[^downgrade]: [Far Cry 3 Downgrade v1.06 to v1.05](https://www.nexusmods.com/farcry3/mods/196), and the Steam guide [Downgrade to 1.05 to enable mods](https://steamcommunity.com/sharedfiles/filedetails/?id=3360740938).
[^conflict]: [Ziggy's Mod comments](https://www.nexusmods.com/farcry3/mods/63?tab=posts) and [Far Cry 3 Redux discussion](https://steamcommunity.com/app/220240/discussions/0/1642043732655502658/).
[^install]: [HD Texture Pack install notes](https://www.nexusmods.com/farcry3/mods/291).
[^depth]: [Depth Buffer in Far Cry 3, ReShade forum](https://reshade.me/forum/shader-troubleshooting/544-solved-depth-buffer-in-far-cry-3).
[^protondb]: [ProtonDB, Far Cry 3](https://www.protondb.com/app/220240).
[^msaa]: [dxvk#2863, waterfalls show corruption with MSAA](https://github.com/doitsujin/dxvk/issues/2863).
