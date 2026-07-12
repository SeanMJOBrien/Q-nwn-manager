---
name: nwn-character-editor
description: Use this skill when viewing or editing NWN:EE player character files (.bic, in a servervault/localvault) or creature blueprints (.utc) — inspecting or changing ability scores, hit points, saves, feats, skills, classes, XP, gold, or appearance (model, head, colors, portrait). Trigger on ".bic", "servervault", "player character file", "give this character a feat", "change creature stats/appearance", or similar. For a browser UI over the same edits, use nwn-web-editor.
---

# NWN Character & Creature Editor (.bic / .utc)

`.bic` (player character) is a superset of `.utc` (creature blueprint) — same
GFF container, same core fields, plus persistence extras. Use the Python
load/save pattern from `nwn-gff-formats`. Field names below are verified
against real converted samples.

**Golden rule for .bic:** never edit a character that might be logged in —
the server rewrites the file on save/logout and will clobber your edit (or
worse). Edit offline copies or with the server down, and keep the `.bak`.

## Core stats (both .utc and .bic)

| Field | Type | Notes |
|-------|------|-------|
| `Str` `Dex` `Con` `Int` `Wis` `Cha` | byte | raw ability scores |
| `HitPoints` | short | base (rolled) HP |
| `MaxHitPoints` | short | base + con bonus; keep >= HitPoints |
| `CurrentHitPoints` | short | may be < max (wounded) |
| `NaturalAC` | byte | natural armor bonus |
| `fortbonus` `refbonus` `willbonus` | short | flat save adjustments |
| `ChallengeRating` | float | CR (affects XP awards) |
| `CRAdjust` | int | .utc only, builder CR fudge |
| `FirstName` `LastName` | cexolocstring | `{"0": "text"}` value dict |
| `Tag` | cexostring | script handle |
| `FactionID` | word | row in the module's .fac |
| `Conversation` | resref | dialog file |
| `Script*` (Attacked, Heartbeat, Spawn, …) | resref | 13 event scripts |

## Feats, skills, classes

```json
"FeatList":  {"type":"list","value":[{"__struct_id":1,"Feat":{"type":"word","value":2}}]}
"SkillList": {"type":"list","value":[{"__struct_id":0,"Rank":{"type":"byte","value":4}}]}
"ClassList": {"type":"list","value":[{"__struct_id":2,
    "Class":{"type":"int","value":4},"ClassLevel":{"type":"short","value":7}}]}
```

- **Feats**: unordered set of feat.2da row IDs. Add = append struct (copy an
  existing entry's `__struct_id`, conventionally 1); remove = filter. Avoid
  duplicates. Class-granted feats reappear on level-up if removed.
- **Skills**: positional — index in the list IS the skills.2da row; edit
  `Rank` in place, never insert/delete/reorder entries.
- **Classes**: max 3 entries. Casters also carry `KnownList0-9` /
  `MemorizedList0-9` (spells.2da IDs) and `Domain1/Domain2` on clerics.
  Changing `ClassLevel` on a .bic without matching `LvlStatList` entries
  (one struct per level: feats/skills/HP gained that level) makes the
  character fail ELC validation on servers that enforce it — for .bic level
  changes, prefer in-game console/scripts unless you rebuild `LvlStatList`.

## Appearance

| Field | Type | Notes |
|-------|------|-------|
| `Appearance_Type` | word | appearance.2da row (model) |
| `PortraitId` (.utc) / `Portrait` (.bic) | word / resref | portraits.2da row vs direct `po_*` resref |
| `Gender` | byte | 0 M / 1 F |
| `Race` | byte | racialtypes.2da row |
| `Phenotype` | int | 0 normal / 2 large |
| `Appearance_Head` | byte | head model # (dynamic models only) |
| `BodyPart_*` (Torso, Pelvis, LBicep…) | byte | part model #s (dynamic only) |
| `ArmorPart_RFoot` | byte | ditto |
| `Color_Hair` `Color_Skin` `Color_Tattoo1` `Color_Tattoo2` | byte | palette indices |
| `Tail_New` `Wings_New` | dword | tail/wing model |
| `SoundSetFile` | word | soundset.2da row |

Dynamic-model fields (`Appearance_Head`, `BodyPart_*`, `Color_*`) only exist
when `Appearance_Type` is a player-race dynamic model; static monster models
ignore them. Only render/edit fields already present in the file.

## .bic-only extras

| Field | Type | Notes |
|-------|------|-------|
| `Experience` | dword | total XP — server recalcs level eligibility from this |
| `Gold` | dword | carried gold |
| `Age` | int | cosmetic |
| `LvlStatList` | list | per-level snapshot (see Classes above) |
| `QBList` | list | quickbar slots |
| `Equip_ItemList` / `ItemList` | list | equipped / backpack items, each a full inline .uti struct |
| `IsDM` | byte | leave alone |

Position (`XPosition`…) and `AreaId` in a .bic are where the character last
saved; safe to ignore.

## Inventory notes (both)

`Equip_ItemList` entries carry `__struct_id` = equip-slot **bitmask** (1 =
head, 2 = chest, 4 = boots, … 16384 = cloak) — the struct id is meaningful
here, don't renumber it. `ItemList` entries have `Repos_PosX/PosY` grid
fields. Each entry is a complete item (like an inlined .uti), so edits to an
equipped item's properties happen here, not in any external file.

## Verification

Round-trip the file back through `nwn_gff` and diff JSON before/after to
confirm only intended fields changed. For .bic: copy into a test vault and
log the character in on a local server; for .utc: rebuild the module and
spawn one.
