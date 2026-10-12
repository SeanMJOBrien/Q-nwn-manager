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

Ideas surfaced after the palette and reference-aware-rename work. Items marked
*(unchecked)* are leads from skimming, not verified problems.

### Safety

- **No CSRF protection on state-changing POSTs.** The editors bind 127.0.0.1,
  but the docs describe a reverse-proxy deployment (`--url-prefix`, Apache with
  basic auth). A per-session token (`secrets.token_hex`, compared with
  `hmac.compare_digest`) on every apply/preview form would close it. Highest
  priority if the console is ever reachable by anyone else.
- **No write-time conflict check.** Every editor reads, edits and writes a whole
  file; two tabs, or the console plus a `nasher` unpack, silently overwrite each
  other. Cheap fix: record the file's mtime when a form is rendered and refuse
  the apply if it changed.
- **No undo beyond the one-time `.bak`.** The second edit to a file has nothing
  to go back to. Options: timestamped backups under a per-project history dir,
  or a "restore from .bak" action. Matters more now that palette edits are
  structural.
- **Palette output unverified against the toolset.** Edited palettes have never
  been loaded into the toolset. Do that once on a real module, and extend
  `palette check` with whatever the toolset turns out to reject.
- **Tag-embedded references on area rename.** Waypoint/object tags that embed
  the old area tag (e.g. `<TEAM>_VAULT`) are still not rewritten; only module.ifo
  and the script scan landed (see "Reference-aware area rename").

### Efficiency / maintainability

- **Shared editor module.** The console and the standalone web editor duplicate
  the GFF helpers and the `apply_*` functions (see "Editor capability
  divergence"); the rename cascade and script scan were written twice. Extract
  the shared logic into one module both import, the way `bin/nwn-palette`
  already is.
- **Page-load cost on big projects** *(unchecked)*. Areas/Creatures reparse many
  JSON files on first load (an 8,000-file project exists locally). The mtime
  cache works, but measure before optimising.
- **Stray repo-root files** *(unchecked)*. `bin/__pycache__/*.pyc` and loose
  `.2da`/`.uti`/`.json` files in the repo root look accidental.

### New features

- **Cross-reference report.** "Where is this blueprint / tag / resref used?"
  across areas, dialogs, scripts and palettes. The rename script scan is a
  starting point; `nwn-mcp` has `find_orphans` / `find_variable_usage` for
  comparison.
- **Generic blueprint scalar editor** for `.uti`/`.utp`/`.utd`/`.utt`/`.utm`/
  `.ute` with a preview step (the gap noted under "Other NWN file types").
- **Palette extras:** drag-and-drop reordering, collapsible folders, and an
  unlisted-blueprint warning in the `repack` gate.
- **Dialog editing.** Dialogs have `check-dlg-integrity` but no editor.
