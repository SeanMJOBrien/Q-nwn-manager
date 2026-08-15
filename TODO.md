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

- Doors/Triggers/Waypoints/Sounds/Stores/Encounters aren't removable yet -
  only Placeable/Creature/loose-item lists are. Higher blast radius (broken
  transitions/script hooks) if done carelessly.
- ~~No filtering/search box within the remove-objects page itself~~ - added
  a client-side live filter (`qnmFilterObjects`/`FILTER_SCRIPT`) that hides
  non-matching rows (grouped with their nested inventory rows) without a
  round trip, so ticked checkboxes survive filtering.
- ~~A loose ground item's own nested inventory isn't exposed for removal~~ -
  `INVENTORY_SUBFIELDS["item"]` now drills into a loose item's own `ItemList`
  the same way placeables' carried items already worked; no other code
  changes were needed since `apply_remove_objects`'s dispatch was already
  generic over category.
