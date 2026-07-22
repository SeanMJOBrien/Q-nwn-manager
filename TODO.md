# TODO

## Remove-objects area editor (console)

Deliberately out of scope for the first version - see the "Explicitly out of
scope" section this shipped against for the full reasoning.

- Doors/Triggers/Waypoints/Sounds/Stores/Encounters aren't removable yet -
  only Placeable/Creature/loose-item lists are. Higher blast radius (broken
  transitions/script hooks) if done carelessly.
- No filtering/search box within the remove-objects page itself - a large
  area (one sample had 86 placeables) renders as one long flat list.
- A loose ground item's own nested inventory (bag-of-holding-style items
  that themselves carry an ItemList) isn't exposed for removal - only
  creature/placeable containers get the inventory drill-down.
