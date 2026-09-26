# NWN Web Editor — Feature Specifications

One section per feature. Each spec covers: purpose, selection model, UI flow,
fields touched, blank-field semantics, validation, and known limitations.
Verified behavior — every flow below was exercised end-to-end against real
hos1 `.are`/`.utc` files and a real servervault `.bic` at build time.

Shared invariants (apply to every feature):

- All reads go through a per-file mtime cache; all writes `gff_load` fresh,
  mutate, `gff_save`, then invalidate the cache entry.
- `gff_save` = one-time `<file>.bak` sibling backup, JSON -> GFF via
  `nwn_gff -l json -k gff`, atomic `os.replace` into place.
- A field submitted **blank is never written** — bulk forms are sparse
  overlays, not full-record replacement.
- Existing field GFF types are preserved; new fields are created only with an
  explicitly known type.
- Server binds 127.0.0.1 by default; there is no auth — do not expose it.

---

## 1. Area list & selection

**Purpose:** the entry point for every bulk area operation — find and select
the target set.

**Selection model:** two composable filters, then per-row checkboxes:
- `q` — case-insensitive substring over resref, display name, and tag.
- `tileset` — exact match dropdown, populated from the distinct `Tileset`
  values actually present (this is the "category" grouping: all crypt areas,
  all forest areas, etc.).
- Header checkbox = select-all-visible (one inline JS handler; the only JS
  in the app).

**UI flow:** GET `/areas` -> table (resref, name, tag, tileset, current four
event scripts) -> checkboxes -> one of three action buttons POSTs the
selection to `/areas/select`, which renders the matching edit form with the
resrefs embedded as hidden inputs.

**Reads:** `.are` only — `Name` (cexolocstring), `Tag`, `Tileset`,
`OnEnter/OnExit/OnHeartbeat/OnUserDefined`.

**Limitations:** name-prefix conventions (e.g. `plan_*`) are handled via the
substring filter, not a saved-category mechanism; selections don't persist
across page loads.

---

## 2. Bulk area event scripts

**Purpose:** point every selected area's OnEnter / OnExit / OnHeartbeat /
OnUserDefined at a new script in one shot (e.g. install an area-enter hook
module-wide).

**UI flow:** form shows the four events with each event's **current distinct
values** across the selection (so you can see divergence before overwriting).
POST `/areas/scripts/apply`.

**Fields touched:** the four `resref`-typed event fields in each `.are`.

**Blank semantics:** blank = leave that event untouched on every area;
literal `-` = clear the event (set to empty string).

**Validation:** values lowercased and truncated to 16 chars (resref limit).
The app does **not** verify the target script exists compiled in the module —
check `nwn_erf -f mod.mod -t | grep <script>` separately, or the event
silently no-ops in game.

**Result page:** reports changed-vs-selected counts; areas whose values
already matched are skipped (not rewritten, no spurious .bak).

---

## 3. Area lighting & fog

**Purpose:** re-theme atmosphere across whole categories of areas — darken
all crypts, add fog to all swamps, switch areas to static night, etc.

**UI flow:** form prefilled with the **first selected area's** current values
(as reference; multi-area edits apply uniformly). Two fieldsets: colors and
numerics. POST `/areas/lighting/apply`.

**Fields touched (.are):**
- Colors (dword, stored **0xBBGGRR** BGR — entered as `#rrggbb` hex and
  converted; conversion verified: `#112233` -> `0x332211`):
  `SunAmbientColor`, `SunDiffuseColor`, `SunFogColor`, `MoonAmbientColor`,
  `MoonDiffuseColor`, `MoonFogColor`.
- Numerics: `SunFogAmount`/`MoonFogAmount` (byte 0–15), `FogClipDist`
  (float), `DayNightCycle` (byte 0/1), `IsNight` (byte, only matters when
  cycle=0), `LightingScheme` (byte), `ShadowOpacity` (byte 0–100),
  `SunShadows`/`MoonShadows` (byte 0/1), `WindPower` (int 0–2),
  `ChanceRain`/`ChanceSnow`/`ChanceLightning` (int 0–100, %),
  `SkyBox` (byte, skyboxes.2da row).

**Blank semantics:** blank = keep per-area current value (lets you set fog
density on 40 areas without touching their individual colors).

**Validation:** hex parsed strictly (6 hex digits); numerics cast to the
field's GFF type (float vs int). Out-of-range values are not clamped — the
engine tolerates some and ignores others; stay in documented ranges.

**Limitations:** `SkyBox` is a raw skyboxes.2da row number, not a titled
dropdown — skyboxes.2da has no TLK-referenced name column (unlike
ambientmusic/appearance/feat), so it wasn't worth a stock-data lookup for
6 stock rows; check the toolset's picker. Interior-flagged areas may
visibly ignore sun/moon settings (engine behavior, not app).

---

## 4. Area music

**Purpose:** set the day/night/battle ambient tracks across whole categories
of areas without the toolset's Music properties tab.

**UI flow:** form prefilled with the **first selected area's** current values
(as reference; multi-area edits apply uniformly). POST `/areas/music/apply`.

**Fields touched (.are):** `MusicDay`/`MusicNight`/`MusicBattle` (int,
ambientmusic.2da row index — 0 = none), `MusicDelay` (byte, 0 = start
immediately / 1 = delay the day track).

**Name lookup:** `MusicDay`/`MusicNight`/`MusicBattle` render as a `<select>`
of "row - Title" options (e.g. `2 - Rural Day 2`), matching what the
toolset's own Day/Night/Battle pickers show, instead of a bare row number.
Titles come from `bin/wiki_data/music.json`, built by
`_build_stock.py` from `ambientmusic.2da`'s `Description` TLK strref (base
game tracks) with a `DisplayName` literal fallback for expansion-pack
tracks that carry no strref (Daggerford/HotU stingers). Same
`_load_stock_json`/graceful-fallback contract as `class_name`/`feat_name`/
`skill_name`: if `music.json` is missing, the fields fall back to plain
number inputs with the old "look it up yourself" hint — never a crash.

**Project 2da/custom-TLK overlay:** `--twoda-dir DIR` (a project's own
merged `ambientmusic.2da`/`appearance.2da`/`feat.2da`, e.g. extracted from
its HAKs) and `--custom-tlk FILE` (its custom TLK) close the gap above -
`load_named_2da_options()` live-parses `--twoda-dir`'s copy of the table,
resolving any row whose Description/Name strref is `>= 0x01000000`
(`CUSTOM_TLK_OFFSET`) via `--custom-tlk`, keeping the pre-baked stock name
for every row it already knows, and title-casing the Resource/Label cell
as a last resort for a row with no strref at all. Both flags are optional
and pass straight through `nwn-manager console`/`edit-areas`'s existing
"extra args forward to the tool" contract - no `nwn-manager` changes were
needed. `read_tlk()`/`parse_2da()` are small stdlib-only re-implementations
of `bin/wiki_data/_2da_lib.py`'s logic (kept duplicated rather than
imported, matching this project's existing between-editor duplication
convention - see `TODO.md`), so this works even in the frozen
`nwn-pytools` binary with no `nwn_tlk`/`nwn_erf` on PATH.

**Blank semantics:** blank ("(leave unchanged)") = keep per-area current
value on every selected area.

**Limitations:** `--twoda-dir`'s tables must already be the project's
*merged* result (base + HAK overrides stacked, e.g. via `nwn_erf -x` on
each HAK plus manual override resolution) - the app doesn't compute HAK
layering itself, it only parses whatever single `ambientmusic.2da` file
sits in that directory.

---

## 5. Area tags & resrefs

**Purpose:** rename an area's script-visible identity (Tag) and, when truly
needed, its file identity (ResRef).

**UI flow:** per-area editable Tag input (prefilled) + optional "new resref"
input (placeholder = keep). POST `/areas/tags/apply`.

**Behavior:**
- Tag: written to `.are` `Tag` field when changed.
- ResRef: validated `[a-z0-9_]{1,16}`, collision-checked against existing
  `.are`; on success rewrites the `ResRef` field **and** renames all three
  files (`.are/.git/.gic`) via `os.replace`.

**Explicit non-goals (surfaced as an on-page warning):** a resref rename does
NOT chase references — door/trigger `LinkedTo` transitions in other areas
target tags, waypoint tags of the form `<TEAM>_VAULT` embed old tags, and
`module.ifo`'s `Mod_Entry_Area` may point at the old resref. Grep the module
after any rename. Per-area validation errors are reported inline and skip
only the offending rename, not the whole batch.

---

## 6. Player character (.bic) browser & editor

**Purpose:** inspect and fix up player characters directly in a servervault —
restore lost gold/XP, grant or strip a feat, fix a broken appearance.

**Selection model:** `--bic-dir` walked **recursively** (servervaults are
one-subdir-per-CD-key/account); filter by path substring. Path traversal out
of `--bic-dir` is rejected (realpath containment check — verified).

**UI flow:** GET `/bics` list (name, classes, XP, gold) -> `/bic?path=` edit
form -> POST `/bic/apply`.

**Fields touched:** identity (`FirstName`/`LastName` cexolocstring `"0"` key,
`Tag`), abilities (`Str`..`Cha`), stats (`NaturalAC`, `HitPoints`,
`CurrentHitPoints`, `MaxHitPoints`, `fortbonus/refbonus/willbonus`,
`ChallengeRating`), bic extras (`Experience`, `Gold`, `Age`), appearance
(section 7's field set), feats (section 7's add/remove model).

**Blank semantics:** blank numeric = keep. Name/Tag inputs are prefilled with
current values, so an unchanged submit is a no-op (equality-checked before
write).

**Limitations / safety:**
- Never edit a logged-in character — server save clobbers the file. Edit
  with the server down; the `.bak` is the recovery path.
- No `LvlStatList` reconciliation: changing class levels here will trip ELC
  on enforcing servers. XP/gold/feats/appearance edits are safe.
- Unreadable .bic files render as an inline per-row error, not a page crash.

---

## 7. Creature blueprint (.utc) editor

**Purpose:** tune module NPCs/monsters — stats, feats, appearance — without
the toolset.

**UI flow:** GET `/creatures` list (resref, name, tag, classes, appearance
id; substring filter) -> `/creature?res=` -> POST `/creature/apply`.

**Fields touched:** same identity/ability/stat set as .bic (minus
XP/gold/age), plus:
- **Appearance:** `Appearance_Type` renders as a titled `<select>` (via
  `appearance_options()` / `bin/wiki_data/appearance.json`, same
  `music_options()`-style lookup as area music) — "(leave unchanged)" is
  `selected` by default unless the current value is a known appearance
  row, in which case that option is pre-selected instead, so re-submitting
  without touching it is a no-op. A companion `Appearance_Type_raw` text
  input sits next to the dropdown for a HAK appearance past
  appearance.json's stock coverage — when filled, it overrides the
  dropdown's selection entirely (`apply_char_edits` rewrites
  `form["Appearance_Type"]` from it before the generic numeric-field loop
  runs). `PortraitId`, `Gender`, `Race`, `Phenotype`, and — **only when
  present in the file** — the dynamic-model fields `Appearance_Head`,
  `Color_Hair/Skin/Tattoo1/2`, `Tail_New`, `Wings_New` stay plain number
  inputs. Static monster models don't carry them and the form doesn't
  invent them.
- **Feats:** current feat IDs rendered as checkboxes (tick = remove), plus
  **two** add mechanisms: a named multi-select (`addfeat_multi`, via
  `feat_options()` / `feat.json` — ctrl/cmd-click, or type-to-jump, for
  several at once) and the original comma-separated raw-ID box
  (`addfeats`, for HAK feats past feat.json's stock coverage). Both feed
  the same add loop, which dedupes against present feats **and** across
  the two input sources (`have` is updated as entries are appended, not
  just seeded once) — picking a feat in both boxes doesn't double it.
  Adds copy an existing entry's `__struct_id` (default 1) and land as
  `{"__struct_id":1,"Feat":{"type":"word","value":N}}` (verified
  round-trip).

**Limitations:** both lookups gracefully degrade to the old raw-ID inputs
if `appearance.json`/`feat.json` are missing (same `_load_stock_json`
empty-dict fallback as everywhere else) — never a crash. Only stock rows
are named unless `--twoda-dir`/`--custom-tlk` are given (see §4's "Project
2da/custom-TLK overlay" — the same `load_named_2da_options()` backs
`appearance_options()`/`feat_options()` too); without them, a HAK-added
feat/appearance past the stock table's coverage needs its raw ID via the
comma-separated feat box or the `Appearance_Type_raw` override.
Skills, class list,
spell lists, and inventory are view-adjacent but not editable here — use
the `nwn-character-editor` skill's Python recipes for those (positional
SkillList and slot-bitmask Equip_ItemList semantics make them poor fits
for a generic form).

---

## Adding a new feature (spec template)

Before coding, write the section above-style: **Purpose / Selection model /
UI flow / Fields touched (with GFF types) / Blank semantics / Validation /
Limitations.** Then implement as a `render_*` (GET) + `apply_*` (POST) pair,
wire both into `Handler.do_GET/do_POST`, reuse `gff_load/gff_save` +
`getv/setv`, and verify with a curl round-trip against scratch copies before
declaring it done.
