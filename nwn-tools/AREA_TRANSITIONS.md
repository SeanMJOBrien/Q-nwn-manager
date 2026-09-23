# NWN area-transition GFF reference

How to connect areas (with a door, or without one) by editing the loose
`.are`/`.git`/`.utt`/`.utw` GFF resources directly with `nwn_gff`. Findings
below were derived by inspecting real working transitions in hos1 (a project
that stores areas as loose GFF files in its repo root — no `.mod`/`nwn_erf`
unpacking needed there; if a project instead bundles everything into a
`.mod`, use `nwn_erf` to list/extract the relevant `.are`/`.git`/`.utw`/
`.utt`/`.ifo` resources first, edit as JSON, then repack).

Edit workflow (same round-trip pattern as `.dlg` editing):
```
nwn_gff -i <area>.git -o <area>.json -k json -p   # inspect/edit
nwn_gff -i <area>.json -o <area>.git -k gff       # write back
```
Verify round-trip stability the same way as for `.dlg`: convert back to JSON
and confirm the structure is semantically unchanged (field ordering/
indentation differences are harmless).

## 1. Door-to-door transition (built-in engine handling, no script)

Each door is a struct in its area's `.git` under `Door List`. To link two
doors in different areas:

- On door A (in area A's `.git`): set `LinkedToFlags = 1` and
  `LinkedTo = <Tag of door B>`.
- On door B (in area B's `.git`): set `LinkedToFlags = 1` and
  `LinkedTo = <Tag of door A>` (reciprocal).
- Leave `LinkedToModule` empty — lookups resolve by `Tag` within the running
  module (cross-module links via `LinkedToModule` were not found anywhere in
  hos1's data and don't appear to be needed for same-module connections).
- Leave `OnClick`/`OnOpen`/etc. empty — the engine performs the transition
  automatically when the door is opened.

Tag naming convention seen in practice: `<srcAreaAbbrev>_2_<dstAreaAbbrev>`
on each side, e.g. door `AGNE_2_PNGE` (in `abovegroundnesec.git`) <->
`PNGE_2_AGNE` (in the Pantry area), and a simpler pair `ABNE_D` <-> `BGNE_U`.
Reference file: `abovegroundnesec.git`.

## 2. Door-less / trigger-based transition (built-in engine handling, no script)

Use the `genericareatrans.utt` blueprint (`TemplateResRef = genericareatrans`,
default `Tag = GenericAreaTransition`). Place an *instance* of it in the
source area's `.git` under `TriggerList`:

- `Type = 1` (Transition).
- `LinkedToFlags = 2`, `LinkedTo = <Tag of destination waypoint>`.
- `OnClick` cleared to empty — the blueprint's default `OnClick =
  mar_trans_trig` (see §3) is the *legacy scripted* system, not used by
  built-in transitions.
- Give the instance its own `Geometry`: a list of structs (`__struct_id: 3`)
  each `{PointX, PointY, PointZ}`, defining the trigger's footprint polygon
  as offsets from the trigger's own `XPosition`/`YPosition`/`ZPosition`. The
  reference example uses 5 points forming a small polygon (~0–2 units across).

The destination waypoint is a normal `.git` `WaypointList` entry (struct
`__struct_id: 5`) with a matching `Tag`, e.g.:
```
{Tag: "WP_CatOSkulls_W", TemplateResRef: "", XPosition, YPosition, ZPosition,
 XOrientation, YOrientation, LinkedTo: "", ...}
```
It can live in a *different* area's `.git` than the trigger — `GetObjectByTag`
resolves it module-wide when the player walks into the trigger.

Reference: trigger `HobgoblinTribe` in `area001.git` (`LinkedTo =
WP_CatOSkulls_W`, `LinkedToFlags = 2`) links to waypoint `WP_CatOSkulls_W` in
`area.git`'s `WaypointList`.

## 3. Legacy scripted system (`mar_trans_trig` / `MTRANS_*`) — not recommended for new content

`genericareatrans.utt`'s default `OnClick = mar_trans_trig` implements an
older, more complex grid-based transition system (`mar_trans_trig.nss`):
area tags are expected to encode `X_Y_Z` grid coordinates, and destination
waypoints are named `MTRANS_<DIR><N>` (`DIR` = N/S/E/W/U/D, `N` = 1-32) and
located by `GetNearestObjectByTag` with a fallback search that widens `N`.
Only use this if extending an existing area that already follows this grid/
naming convention — for new transitions, prefer §1/§2 (no script needed).

## New areas: `module.ifo`

Adding a brand-new area (not just a transition between existing ones)
requires appending its resref to `module.ifo`'s `Mod_Area_list` (a list of
structs `__struct_id: 6`, each just `{Area_Name: "<arearesref>"}`). The
module's PC start location is separate: `Mod_Entry_Area` (resref) +
`Mod_Entry_X/Y/Z` + `Mod_Entry_Dir_X/Y`.

## Open items / not yet observed in this project's data

- `TransitionDestin` (the "Travel to X" tooltip, cexolocstring) — not set on
  any door or trigger transition found so far. Unclear if it's required for
  the tooltip to appear, or purely cosmetic/optional.
- `LinkedToFlags` values other than `1` (door) and `2` (waypoint) were not
  observed — there may be additional values (e.g. for linking to a trigger)
  per the toolset, but confirm against a real example before relying on them.
