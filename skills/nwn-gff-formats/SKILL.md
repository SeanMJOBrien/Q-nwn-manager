---
name: nwn-gff-formats
description: Use this skill when working with any Neverwinter Nights 1:EE binary file format — creature/item/placeable/door/trigger/waypoint/sound/store/encounter blueprints (.utc/.uti/.utp/.utd/.utt/.utw/.uts/.utm/.ute), player characters (.bic), dialogs (.dlg), module info (.ifo), journals (.jrl), factions (.fac), palettes (.itp), soundsets (.ssf), ERF containers (.mod/.erf/.hak), 2DA tables, or TLK talk tables. Trigger on any mention of these extensions, "GFF", "blueprint", "servervault", or converting/inspecting/bulk-editing NWN game data with Python. For .are/.git/.gic area files specifically, prefer the nwn-area-builder and nwn-area-editor skills.
---

# NWN1:EE File Format Catalog

One-stop reference for every NWN:EE file format and the safe Python editing
pattern. Companion skills: `nwn-area-builder` (area GFF JSON schema in depth),
`nwn-area-editor` (bulk area edits), `nwn-character-editor` (.bic/.utc fields),
`nwn-web-editor` (browser UI for selective bulk edits).

## Tools

`~/git/nwn-tools/linux/neverwinter/` has the CLI converters (add to PATH or
call by absolute path; sibling `../nwn-tools/` from any project repo):

| Tool | Purpose |
|------|---------|
| `nwn_gff` | GFF binary <-> JSON (all formats below marked GFF) |
| `nwn_erf` | pack/extract/list `.mod`/`.erf`/`.hak`/`.sav` |
| `nwn_tlk` | `.tlk` <-> CSV/JSON |
| `nwn_twoda` | `.2da` <-> CSV/JSON/minified |
| `nwn_ssf` | soundset <-> CSV/JSON |
| `nwn_key_*` / `nwn_resman_*` | read game key/bif archives |

## Format catalog

Everything below except ERF/2DA/TLK is **GFF** — same container, different
`__data_type` tag and field set. Never hand-edit the binary; always round-trip
through JSON (`nwn_gff -i x.utc -o x.json -k json -p`, edit, convert back).

| Ext | Type tag | Contents | Notable fields |
|-----|----------|----------|----------------|
| .are | `ARE ` | area static: tiles, lighting, fog, event scripts | `Tag`, `OnEnter/OnExit/OnHeartbeat/OnUserDefined`, `Sun*/Moon*Color`, `FogClipDist`, `Tileset`, `Tile_List` |
| .git | `GIT ` | area instances | `Creature List`, `Door List`, `Placeable List` (spaced!), `TriggerList`, `WaypointList`, `SoundList`, `StoreList`, `List` (loose items), `AreaProperties` struct |
| .gic | `GIC ` | toolset comments only | safe to ignore in-game |
| .utc | `UTC ` | creature blueprint | `Str..Cha`, `FeatList`, `SkillList`, `ClassList`, `Appearance_Type`, `Script*`, `FactionID`, `Equip_ItemList`, `ItemList` |
| .bic | `BIC ` | player character (servervault/localvault) | UTC fields **plus** `Experience`, `Gold`, `Age`, `LvlStatList`, `QBList`, body-part/`Color_*` fields |
| .uti | `UTI ` | item blueprint | `BaseItem`, `PropertiesList`, `StackSize`, `Charges`, `Cost`/`AddCost` |
| .utp | `UTP ` | placeable | `Appearance` (row in placeables.2da), `HasInventory`, `ItemList`, `OnUsed`, `Useable`, `Static`, `Plot` |
| .utd | `UTD ` | door | `GenericType`, `Locked`, `KeyName`, `LinkedTo`, `OnOpen` etc |
| .utt | `UTT ` | trigger blueprint | `Type`, `ScriptOnEnter/Exit`, `LinkedTo`, `Cursor` |
| .utw | `UTW ` | waypoint | `Tag`, `LocalizedName`, `HasMapNote`, `MapNote` |
| .uts | `UTS ` | sound | `Sounds` list, `Volume`, `Looping`, `Positional` |
| .utm | `UTM ` | store | `StoreList` (nested item lists), `MarkUp`, `MarkDown`, `OnOpenStore` |
| .ute | `UTE ` | encounter | `CreatureList` (blueprint+CR), `Difficulty`, `MaxCreatures`, `SpawnOption` |
| .dlg | `DLG ` | conversation tree | `EntryList` (NPC), `ReplyList` (PC), `StartingList`; nodes link by **index** into these lists via `RepliesList`/`EntriesList` with `Active` (condition script) and `Index` |
| .ifo | `IFO ` | module info | `Mod_OnLoad` + all module event scripts, `Mod_Entry_Area`, `Mod_HakList`, `Mod_CacheNSSList` |
| .jrl | `JRL ` | journal | `Categories` list -> `EntryList` per quest |
| .fac | `FAC ` | factions | `FactionList`, `RepList` (pairwise reputation) |
| .itp | `ITP ` | toolset palette | `MAIN` list tree — only matters for toolset display |
| .ssf | — | soundset (own binary; use `nwn_ssf`) | 16-char resrefs + strrefs per slot |
| .mod/.erf/.hak/.sav | — | ERF container (use `nwn_erf`) | `.mod` = module, `.hak` = content overlay, `.sav` = savegame (nested!) |
| .2da | — | plain text table | engine rulebook: appearance.2da, feat.2da, classes.2da, portraits.2da … |
| .tlk | — | talk table (use `nwn_tlk`) | strref -> localized text; custom content uses strref >= 0x01000000 |

## GFF JSON shape (essentials)

Full schema: `~/.claude/skills/nwn-area-builder/references/gff-json-schema.md`.
The load-bearing rules:

- Root: `{"__data_type": "UTC ", "Field": {"type": "...", "value": ...}, ...}`
  (4-char tag, keep trailing space).
- Every entry inside a `list`'s value array is a bare struct that **must**
  carry `__struct_id` (copy from a sibling entry when appending).
- `cexolocstring` value is a dict of language-id keys: `{"0": "text"}`; a TLK
  strref appears as an `id` key whose placement varies by tool build — check
  both `field["id"]` and `field["value"]["id"]`.
- Color fields (lighting etc.) are dwords in **0xBBGGRR** (BGR) byte order.
- `resref` values: max 16 chars, lowercase.
- Preserve unknown fields exactly (toolset-injected `x`-prefixed appearance
  fields, module-custom locals) — never prune what you don't recognize.

## Python editing pattern

```python
import json, subprocess

GFF = "~/git/nwn-tools/linux/neverwinter/nwn_gff"  # expanduser it

def load(path):
    out = subprocess.run([GFF, "-i", path, "-k", "json"],
                         check=True, capture_output=True)
    return json.loads(out.stdout)

def save(path, data):
    subprocess.run([GFF, "-l", "json", "-o", path, "-k", "gff"],
                   check=True, input=json.dumps(data).encode())

d = load("goblin.utc")
d["Str"]["value"] = 18                      # existing field: touch value only
d["FeatList"]["value"].append(              # list append: include __struct_id
    {"__struct_id": 1, "Feat": {"type": "word", "value": 411}})
save("goblin.utc", d)
```

Verify after any nontrivial edit: reconvert to JSON and diff, or run
`~/.claude/skills/nwn-area-builder/scripts/validate_gff_json.py` on the JSON.

## ERF / 2DA / TLK quick reference

```bash
nwn_erf -f mod.mod -t                    # list contents
nwn_erf -x -f mod.mod                    # extract to cwd (use empty temp dir!)
nwn_erf -c -f out.mod dir/               # pack (MOD type inferred from name)
nwn_twoda -i feat.2da -k csv             # 2da -> csv (also: json, 2da -m)
nwn_tlk -i dialog.tlk -k json | head     # tlk dump
```

ERF gotchas: extraction is flat (no subdirs); packing recurses by default
(`-r`), so pack from a clean flat dir or old builds get embedded. A `.sav`
contains a nested module — extract twice.

## When in doubt

Convert a real sample file the user already has and read the actual field
names/types out of it. Field sets vary by toolset version and by
static-vs-dynamic appearance; this catalog is a map, not the territory.
