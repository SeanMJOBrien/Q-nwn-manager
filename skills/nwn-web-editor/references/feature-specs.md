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
  `SunShadows`/`MoonShadows` (byte 0/1), `WindPower` (int 0–2).

**Blank semantics:** blank = keep per-area current value (lets you set fog
density on 40 areas without touching their individual colors).

**Validation:** hex parsed strictly (6 hex digits); numerics cast to the
field's GFF type (float vs int). Out-of-range values are not clamped — the
engine tolerates some and ignores others; stay in documented ranges.

**Limitations:** weather odds (`ChanceRain/Snow/Lightning`) and `SkyBox`
aren't exposed yet — trivial to add to `LIGHT_NUM_FIELDS`. Interior-flagged
areas may visibly ignore sun/moon settings (engine behavior, not app).

---

## 4. Area tags & resrefs

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

## 5. Player character (.bic) browser & editor

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
(section 6's field set), feats (section 6's add/remove model).

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

## 6. Creature blueprint (.utc) editor

**Purpose:** tune module NPCs/monsters — stats, feats, appearance — without
the toolset.

**UI flow:** GET `/creatures` list (resref, name, tag, classes, appearance
id; substring filter) -> `/creature?res=` -> POST `/creature/apply`.

**Fields touched:** same identity/ability/stat set as .bic (minus
XP/gold/age), plus:
- **Appearance:** `Appearance_Type` (appearance.2da row), `PortraitId`,
  `Gender`, `Race`, `Phenotype`, and — **only when present in the file** —
  the dynamic-model fields `Appearance_Head`, `Color_Hair/Skin/Tattoo1/2`,
  `Tail_New`, `Wings_New`. Static monster models don't carry them and the
  form doesn't invent them.
- **Feats:** current feat IDs rendered as checkboxes (tick = remove) plus a
  comma-separated add box. Adds copy an existing entry's `__struct_id`
  (default 1), dedupe against present feats, and land as
  `{"__struct_id":1,"Feat":{"type":"word","value":N}}` (verified round-trip).

**Limitations:** feat/appearance IDs are raw 2da row numbers — the app has no
2da name lookup (would need a `--twoda-dir`; see feat.2da / appearance.2da
for the mapping). Skills, class list, spell lists, and inventory are
view-adjacent but not editable here — use the `nwn-character-editor` skill's
Python recipes for those (positional SkillList and slot-bitmask
Equip_ItemList semantics make them poor fits for a generic form).

---

## Adding a new feature (spec template)

Before coding, write the section above-style: **Purpose / Selection model /
UI flow / Fields touched (with GFF types) / Blank semantics / Validation /
Limitations.** Then implement as a `render_*` (GET) + `apply_*` (POST) pair,
wire both into `Handler.do_GET/do_POST`, reuse `gff_load/gff_save` +
`getv/setv`, and verify with a curl round-trip against scratch copies before
declaring it done.
