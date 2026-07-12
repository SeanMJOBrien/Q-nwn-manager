---
name: nwn-area-editor
description: Use this skill for selective or bulk edits to existing NWN:EE areas — changing area event scripts (OnEnter/OnExit/OnHeartbeat/OnUserDefined) across one or many areas, renaming area tags or resrefs, or adjusting lighting, fog, day/night, and weather settings. Trigger on "change the script on these areas", "set fog", "lighting", "rename this area's tag", "all areas in tileset X", or similar bulk-area requests. For building new areas or placing objects, use nwn-area-builder instead; for a browser UI, use nwn-web-editor.
---

# NWN Area Editor (bulk/selective edits)

Recipes for editing many `.are` files at once with Python + `nwn_gff`
(see `nwn-gff-formats` for the load/save pattern). For an interactive
checkbox-driven UI over the same operations, launch `nwn-web-editor`.

## Selecting areas

An area = three files sharing a resref: `.are` (static: everything this skill
edits), `.git` (instances), `.gic` (comments). Selection strategies:

- **By category**: group on the `Tileset` field (all crypts, all forests…),
  or on resref/tag prefix conventions (`plan_*`, `spid*`).
- **By list**: explicit resref list from the user.
- Always print the matched set and get confirmation before a bulk write.

```python
import glob
areas = {p[:-4]: load(p) for p in glob.glob("*.are")}
crypts = [r for r, d in areas.items()
          if d["Tileset"]["value"] == "tdc01"]        # by tileset
```

## Event scripts (in .are, NOT .git)

Fields: `OnEnter`, `OnExit`, `OnHeartbeat`, `OnUserDefined` — all `resref`
type (max 16 chars, no `.nss`/`.ncs` extension, empty string = no script).

```python
for res in selected:
    d = load(res + ".are")
    d["OnEnter"]["value"] = "my_area_enter"
    save(res + ".are", d)
```

The script itself must exist compiled (`.ncs`) in the module or a hak, or the
event silently does nothing — verify with `nwn_erf -f mod.mod -t | grep`.

## Tag and resref

- `Tag` (`cexostring`, in `.are`): what `GetArea`-by-tag / scripts see.
  Freely editable, but grep the module's `.nss`/`.git` for the old tag first —
  transitions (`LinkedTo`) and scripts reference tags by string.
- `ResRef` (`resref` field, in `.are`): must equal the filename stem.
  Renaming = rename all three files **and** the `ResRef` field **and** fix
  every door/trigger `LinkedTo`-target plus `Mod_Entry_Area` in `module.ifo`
  if it pointed there. Prefer changing Tag over ResRef when either would do.

## Lighting, fog, day/night (all in .are)

| Field | Type | Meaning |
|-------|------|---------|
| `SunAmbientColor` / `SunDiffuseColor` | dword | daytime ambient/diffuse, **0xBBGGRR** |
| `MoonAmbientColor` / `MoonDiffuseColor` | dword | nighttime equivalents |
| `SunFogColor` / `MoonFogColor` | dword | fog color day/night |
| `SunFogAmount` / `MoonFogAmount` | byte | 0–15 fog density |
| `FogClipDist` | float | draw distance where fog fully occludes |
| `DayNightCycle` | byte | 1 = cycles; 0 = static (then `IsNight` picks which) |
| `IsNight` | byte | 0/1, only meaningful when static |
| `LightingScheme` | byte | row in environment presets 2da |
| `SunShadows` / `MoonShadows` | byte | 0/1 |
| `ShadowOpacity` | byte | 0–100 |
| `WindPower` | int | 0 none / 1 weak / 2 strong |
| `ChanceRain` / `ChanceSnow` / `ChanceLightning` | int | 0–100 weather odds |

Color conversion (BGR!):

```python
def hex_to_dword(s):                     # "#rrggbb" -> NWN dword
    r, g, b = (int(s.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)
```

Interior areas ignore Sun*/Moon* cycling unless flagged exterior (`Flags`
bit 0x02 underground, etc.) — if a lighting change "does nothing" in-game,
check `Flags` and `DayNightCycle` first.

## After editing

Rebuild/repack so the module actually contains the new `.are` (for hos1:
`bash build_module.sh`, which diffs, recompiles, and overlays onto the base
module). In-game, area lighting reloads on area re-entry; a running server
needs the area reloaded or a restart.
