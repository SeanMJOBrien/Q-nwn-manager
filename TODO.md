# TODO

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
