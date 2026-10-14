# TODO

## Module settings (console)

- `Mod_HakList` / `Mod_CustomTlk` aren't editable. Deliberately deferred when
  the rest of the module form landed: adding or removing a hak changes which
  content resolves, so the project needs a re-unpack afterwards to pick it up,
  and the form would have to drive that rather than just writing the field.
  Everything else in the group (start location, calendar, XP scale, tag,
  default bic, start movie) is editable - see `MODULE_FIELD_GROUPS` in
  `bin/nwn-area-editor`.

## Editor capability divergence (accepted)

The console (`bin/nwn-area-editor`) and the standalone web editor
(`skills/nwn-web-editor/scripts/nwn_web_editor.py`) have deliberately
different feature sets, and neither is a superset of the other:

- Console only: area Name/Flags, module.ifo settings, placed-instance editing,
  equipment/Dropable, remove-objects.
- Web editor only: everything `.bic` (level-history integrity check, classes,
  alignment, Deity/Description, carried-item removal, quickbar clear). It's
  also what `nwn-mcp`'s `start_web_editor` spawns, so `.bic` support lives
  there by design.
- Both: area scripts/lighting/music/tags, creature stats/feats/appearance,
  skill ranks.

Porting either way means duplicating logic that's already duplicated
(`apply_char_edits`, the area `apply_*` functions, the GFF field helpers). If
that divergence ever becomes a problem, the fix is extracting the shared code
into one module both import - not copying features across a third time.

## Other NWN file types (mostly `nwn-mcp`'s side)

Editing gaps neither project covers, left where the relevant machinery lives:

- `.2da` and `.ssf` writing - read-only in both projects.
- Editing an *existing* blueprint's scalar fields for
  `.uti`/`.utp`/`.utd`/`.utt`/`.utm`/`.ute` - `nwn-mcp` has `create_*` with
  clone-and-override, but no setter, so changes go through `modify_gff_field`.
- Blueprint *creation* for `.utp`/`.utw`/`.uts`/`.utd` - `place_*` creates
  instances only.
- Area resize / tileset swap after creation - `Width`/`Height`/`Tileset` are
  written only inside `nwn-mcp`'s `create_area`.

## Remove-objects area editor (console)

Deliberately out of scope for the first version - see the "Explicitly out of
scope" section this shipped against for the full reasoning.

- ~~Doors/Triggers/Waypoints/Sounds/Stores/Encounters aren't removable yet~~ -
  added to `OBJECT_LIST_FIELDS` (`Door List`/`TriggerList`/`WaypointList`/
  `SoundList`/`StoreList`/`Encounter List` - field-name spacing verified
  against real `.git` files, not guessed). `apply_remove_objects` needed no
  changes at all since it already dispatched generically over
  `OBJECT_LIST_FIELDS`. The blast-radius concern is real and stays
  unmitigated for the *other* areas a link points at - the app can't verify
  those - but a door/trigger/waypoint row whose `LinkedTo` is set now renders
  with an inline warning (amber row highlight + `-> target` in a new "Linked
  to" column) so at least *this* row's risk is visible before removal, same
  warn-don't-block precedent as the tags-rename feature. `_obj_blueprint()`
  also had to special-case placed stores, which use a bare `ResRef` field
  instead of every other category's `TemplateResRef`.
- Still not covered: a store's own for-sale inventory (its `StoreList`
  sub-field - yes, same name as the top-level placed-stores list, a second
  genuine GFF-JSON collision) and an encounter's `CreatureList`/
  `SpawnPointList` aren't drillable for nested removal the way a
  placeable/creature/item's carried `ItemList` is - `_inventory_rows_html`
  assumes item-shaped entries (`EquippedRes`/`InventoryRes`, `item_name()`),
  which doesn't fit a creature spawn-table entry or a for-sale blueprint
  without a second nested-row renderer. Only the top-level instances are
  removable for these two categories today.
- ~~No filtering/search box within the remove-objects page itself~~ - added
  a client-side live filter (`qnmFilterObjects`/`FILTER_SCRIPT`) that hides
  non-matching rows (grouped with their nested inventory rows) without a
  round trip, so ticked checkboxes survive filtering.
- ~~A loose ground item's own nested inventory isn't exposed for removal~~ -
  `INVENTORY_SUBFIELDS["item"]` now drills into a loose item's own `ItemList`
  the same way placeables' carried items already worked; no other code
  changes were needed since `apply_remove_objects`'s dispatch was already
  generic over category.

## Palettes (console + `nwn-palette`)

- ~~Stock folder/leaf names displayed as `(strref N)`~~ - resolved from the
  project's `tlk/dialog.tlk` (and the `Mod_CustomTlk` file beside it) via a lazy
  one-entry-at-a-time reader (`Tlk` in `bin/nwn-palette`), or `--dialog-tlk`
  on the CLI and console. Without a TLK it still falls back to `(strref N)`,
  and then stock folders are only reachable by index path. Single-language:
  gendered/alternate-language TLK variants aren't consulted.
- Creature leaves filed by `sync`/`add` take `CR` from the `.utc` but guess
  `FACTION` (a sibling leaf's, else `Hostile`) - the faction name lives in
  `repute.fac`, which isn't read.
- No undo beyond the one-time `.json.bak`.

## Reference-aware area rename (item 8)

Landed per `docs/PLAN_item8_reference_aware_rename.md`: a ResRef rename now
also rewrites `module.ifo`'s `Mod_Entry_Area` and `Mod_Area_list[].Area_Name`
(rows appear in the existing preview table; a module.ifo failure warns and
never blocks the rename), and a tag/resref rename lists the `.nss` source
lines that quote the old value. Both editors got the script scan; the
cascade is in both too (the standalone editor does have `module.ifo` access,
contrary to the plan's first draft). Deferred / limits:

- Script scan is detect-only and source-only: no rewriting, no `.ncs`
  inspection, and a quoted match isn't proof of a real reference (comments and
  unrelated identical strings match too). Matching is case-insensitive.
- Only `"<value>"` string literals are found - a tag built by concatenation
  (`"AREA_" + sNum`) is invisible to it.
- Only an area's *own* ResRef/Tag are chased. Other `.git`-embedded references
  to the old *tag* (e.g. a waypoint tagged `<AREA>_VAULT`) are not rewritten.

## Improvement backlog (from a post-palette review)

Status of the ideas surfaced after the palette and reference-aware-rename
work. Items marked *(unchecked)* are leads from skimming, not verified.

### Safety

- ~~No CSRF protection on state-changing POSTs~~ - done in the console and the
  standalone editor: session cookie (`SameSite=Strict`) + per-session HMAC token
  injected into every POST form, verified in `do_POST`. Exempt: `/shutdown`,
  `/projects/new`, `/projects/ingest-root` (the standalone `start.html` posts
  to them from `file://`, where no session exists - they only create projects or
  stop the console). Residual: scripts using `curl` must fetch a token first.
- ~~No write-time conflict check~~ - done: forms carry their render time and
  `json_save` / `gff_save` refuse (409) when the file's mtime is newer. Limits:
  based on filesystem mtime, so a same-millisecond change is missed, and a
  rename (os.replace of an area's files) isn't covered by the check.
- ~~No undo beyond the one-time `.bak`~~ - done for the console and
  `nwn-palette` (`bin/nwn-common`: last 10 snapshots per file in
  `.nwn-manager/history/`, History page, `palette undo`). Not done: the
  standalone editor (`.bak` only - it is installed as a standalone skill and
  can't import repo code), and restoring *renamed/removed* files is by original
  path only. History is only kept for folders containing a `nasher.cfg`.
- **Palette output unverified against the toolset.** Still open - it needs the
  NWN toolset, which can't be run from here. Load an edited palette once on a
  real module, then extend `palette check` with whatever it rejects.
- ~~Tag-embedded references on area rename~~ - detect-only report added (console
  only): placed-object tags containing the old area tag/resref as a whole word.
  Not rewritten automatically (a similar-looking tag isn't proof it tracks the
  area), and not in the standalone editor (its `.git` files are binary GFF).

### Efficiency / maintainability

- **Shared editor module** - partly done: the safety logic lives in
  `bin/nwn-common`, shared by the console and `nwn-palette`. The console and the
  standalone editor still duplicate the GFF helpers and `apply_*` functions, and
  that can't be fixed by importing: the standalone is installed on its own as a
  skill, so it carries its own copies (CSRF, stale check, rename helpers).
- ~~Page-load cost on big projects~~ - measured on the 2,518-area project:
  Areas 2.5 s cold / 0.04 s warm, area map read 3.2 s cold / 0.06 s warm. Cold
  cost is pure JSON parsing (~1 ms per file), paid once per server run and then
  served from the mtime cache. Not worth a persistent cache and its invalidation
  risk; revisit only if cold starts on bigger projects become a complaint.
- ~~Stray repo files~~ - removed the tracked `bin/__pycache__/*.pyc`
  (`__pycache__/` was already gitignored). Left for the owner to decide, as they
  are committed and unreferenced by the code: `orcplate002.uti`,
  `parts_chest.2da`, `ruleset.2da`, `tagged_versions.json` and the three dated
  `*.txt` session logs in the repo root.

### New features (not started)

- **Cross-reference report.** *Done (console `/xref`, "Find" in the nav).*
  Exact, case-insensitive search for a tag/resref/script/variable name across
  every `*.json` GFF file, `.nss` quoted strings and whole-word object tags,
  grouped by file type with the field path. ~0.5 s over the 285 MB
  2,518-area project. Not done: a CLI form, `.ncs`-only scripts, substring
  search, and linking from the rename preview.
- **Generic blueprint scalar editor** for `.uti`/`.utp`/`.utd`/`.utt`/`.utm`/
  `.ute` with a preview step (the gap noted under "Other NWN file types").
- **Palette extras:** drag-and-drop reordering, collapsible folders, and an
  unlisted-blueprint warning in the `repack` gate.
- **Dialog editing.** Dialogs have `check-dlg-integrity` but no editor.
