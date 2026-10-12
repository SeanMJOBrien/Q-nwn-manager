# Plan — reference-aware area rename (item 8)

> **Status: implemented** (both phases). Correction found while building:
> `nwn_web_editor.py` *does* have `module.ifo` access (its `/module` page), so
> the Phase 1 cascade was added there too, not just to the console. See
> `TODO.md` "Reference-aware area rename" for what landed and its limits.

Implementation plan for closing the "does NOT chase references" gap in the
area tags/resref editor (`skills/nwn-web-editor/references/feature-specs.md`
§5, `bin/nwn-area-editor`'s `apply_tags`). Not yet built — this is the design
to review before writing code.

## Corrected scope

The existing on-page warning (§5) reads:

> a resref rename does NOT chase references — door/trigger `LinkedTo`
> transitions in other areas target tags, waypoint tags of the form
> `<TEAM>_VAULT` embed old tags, and `module.ifo`'s `Mod_Entry_Area` may
> point at the old resref.

Checked this against `nwn-mcp`'s reference implementation
(`src/tools/area-tools.ts`, `object-mgmt-tools.ts`, `paint-tools.ts`,
`verify-tools.ts`) before planning further, since it changes what's actually
worth building:

- **`LinkedTo`/`LinkedToFlags`** on doors, triggers, and even placeables
  (`object-mgmt-tools.ts` comment: "adventure transition lights") always
  target a **waypoint or door tag**, resolved module-wide at runtime by tag
  lookup. They never store an area resref or an area's own tag. Renaming an
  area's Tag or ResRef does **not** invalidate any `LinkedTo` field anywhere
  — the warning is wrong on this point.
- **`module.ifo`** is the one place that genuinely references an area by
  resref:
  - `Mod_Entry_Area` (resref) — the module's start area.
  - `Mod_Area_list[].Area_Name` (resref, one struct per area) — the
    module's own area roster. `nwn-mcp`'s `verify-tools.ts` already treats a
    mismatch here as a real error ("Mod_Area_list matches the actual .are
    resources"), and its `paint-tools.ts` already keeps this list in sync on
    area deletion — same field, same risk, precedent already exists.
- Nothing else in `.are`/`.git`/`.ifo` GFF data references an area by
  resref or tag. The only remaining risk is **NWScript source** doing
  `GetObjectByTag("<old tag>")`-style string lookups against the area's own
  tag — real, but not GFF data, and not something that can be rewritten
  automatically (see Phase 2).

So the feature splits into one safe auto-fix and one detect-only report,
not one big "chase everything" pass.

## Phase 1 — module.ifo cascade (console only, auto-fix)

**Where:** `bin/nwn-area-editor` only. `skills/nwn-web-editor/scripts/
nwn_web_editor.py` has no module.ifo plumbing at all (`TODO.md` already
scopes module.ifo editing as console-only) and operates on raw `.are`/`.utc`
GFF binaries per-request rather than a JSON-native project tree — adding
module.ifo awareness there would be new architecture, not a fix to this
feature. Out of scope for this item.

**Change:** in `apply_tags`, after a resref rename is validated (existing
`[a-z0-9_]{1,16}` + collision checks, unchanged), also load
`module_ifo_path(root)` (already exists, used by the Module settings
feature) and:

- If `Mod_Entry_Area` == old resref → queue rewrite to new resref.
- For each entry in `Mod_Area_list` whose `Area_Name` == old resref → queue
  rewrite to new resref.

Best-effort: if `module.ifo.json` isn't present (partial checkout,
`--dir`-only usage), skip silently — no new failure mode for existing
non-project usage.

**Reuses item 5's infrastructure directly:** the tags preview already emits
a `(res, "ResRef (renames .are/.git/.gic.json)", res, new_ref)` diff row
under `dry_run=True`. This phase just appends
`(res, "module.ifo: Mod_Entry_Area", old, new)` and
`(res, "module.ifo: Mod_Area_list[i]", old, new)` rows to the same `diffs`
list when applicable, so the cascade shows up in the existing preview table
before anything is written — no new UI, no new route.

**Write ordering:** module.ifo write happens in the same `apply_tags` pass,
after the per-area `.are.json`/file-rename writes succeed, so a failure
partway through doesn't leave module.ifo referencing a resref that no
longer exists on disk.

## Phase 2 — script-reference scan (both editors, detect-only)

Tag rename has no GFF field to fix, but a script can still reference the
old tag by string. This can't be auto-fixed safely (a quoted-string match
in `.nss` source has no guaranteed correspondence to a real reference —
could be a comment, an unrelated identical tag reused for something else,
or inside a disabled code path — and there's no recompile step in this
tool), so this phase is strictly **report, don't touch**.

**Change:** after a tag *or* resref rename (shown on both the preview page
*and* the final result page — it's read-only, safe to compute either time),
grep every `.nss` file under the project root for the old value as a quoted
string literal (`"<old_tag>"` / `"<old_resref>"`), and list `file:line`
matches. Replaces today's blanket "grep the module yourself" disclaimer
with the tool actually doing that grep.

**Explicitly not attempted:**
- No rewriting of script source, compiled or not.
- No `.ncs` (compiled) disassembly/scan in the first cut — source-only. A
  source-less project just gets zero scan results, not a crash.
- No claim of completeness — this is a best-effort net, not a guarantee.

## Open questions to resolve before/while implementing

1. **Confirm `.nss` sources live in the same flat `--dir` root as the
   GFF-JSON files** in this project's nasher convention. Believed true from
   prior context in this repo, but not yet verified against a real
   `unpacked/`-style checkout — check before relying on it structurally.
2. **Do we want a size/count cap on the script-scan report** (e.g. a
   generic short tag like `"go"` could match hundreds of unrelated lines)?
   Leaning toward: always run it, but cap displayed matches with a "+N more"
   note rather than skipping the scan for short tags.
3. **Should Phase 1 block the rename on write failure**, or rename the area
   files regardless and just report that module.ifo couldn't be updated?
   Leaning toward: never block the area rename itself (it already succeeded
   by the time module.ifo is touched) — report a warning if the module.ifo
   write fails, matching the existing warn-don't-block posture used for
   `LinkedTo`/tag risk elsewhere in this feature.

## Files touched (estimate)

- `bin/nwn-area-editor` — `apply_tags` (Phase 1 diff rows + module.ifo
  writes), new small `scan_script_references()` helper (Phase 2, shared by
  both editors conceptually but duplicated per the project's existing
  between-editor convention).
- `skills/nwn-web-editor/scripts/nwn_web_editor.py` — `apply_tags` (Phase 2
  only; no module.ifo access to add for Phase 1).
- `skills/nwn-web-editor/references/feature-specs.md` §5 — replace the
  imprecise `LinkedTo` warning with the verified scope above, document both
  phases.
- `TODO.md` — close out this item the way items 1/2/6 were closed (strike
  through with a short "how it landed" note), and add Phase 2's stated
  limitations (source-only, no auto-fix, no completeness guarantee) as the
  new deferred-scope entry.

## Verification plan

- Real fixture: an `.ifo.json` with `Mod_Entry_Area` and `Mod_Area_list`
  both pointing at the area under test, renamed via the preview → confirm
  flow; assert both fields land on the new resref and the diff table showed
  both rows before confirming.
- A rename where module.ifo doesn't reference the area at all → no extra
  diff rows, no module.ifo write, unchanged from today's behavior.
- A rename with no `module.ifo.json` present → unchanged from today's
  behavior, no crash.
- A tag rename with a planted `GetObjectByTag("oldtag")` in a sample `.nss`
  → shows up in the scan report; a rename with no scripts present → empty
  report, no crash.
