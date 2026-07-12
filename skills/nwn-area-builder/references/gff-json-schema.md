# GFF JSON Schema (nwn_gff / nwn-lib compatible)

This describes the JSON shape that `nwn_gff -k json` (niv/neverwinter.nim,
"compatible with niv/nwn-lib") produces for GFF files like `.are`, `.git`,
`.gic`, `.utc`, etc.

Confirmed against real converted samples from two independent projects/tool
builds (different binary, same lineage — `md5sum` differs): a flat unpacked
repo (`.are`/`.git` at the repo root, converted on demand) and a nasher
project (`src/<type>/*.json` sources, already unpacked). Where the two builds
disagreed (see the STRREF note below), both shapes are documented — pick
whichever the target file actually shows.

**Always confirm against a real converted sample from the user's own file
before relying on this document** — field sets differ by file type,
module-specific custom fields (often prefixed `x` by the toolset, e.g.
`XPosition`) may exist that aren't listed here, and even this reference's own
authors got the STRREF placement wrong on the first pass by assuming instead
of checking.

## Top-level shape

A GFF file is one root struct. Note it does **not** carry `__struct_id` —
that only appears on nested struct-type fields and list entries (see below):

```json
{
  "__data_type": "ARE ",
  "FieldName": { "type": "<gff-type>", "value": <value> },
  ...
}
```

`__data_type` is the 4-character file type tag (padded with a trailing space
if needed, e.g. `"ARE "`, `"GIT "`, `"GIC "`). Do not strip the padding when
writing back.

## Field value types

| `type` string   | GFF type      | JSON `value` shape                          |
|-----------------|---------------|----------------------------------------------|
| `byte`          | BYTE          | integer 0–255                                |
| `char`          | CHAR          | integer                                       |
| `word`          | WORD          | integer 0–65535                              |
| `short`         | SHORT         | integer                                       |
| `dword`         | DWORD         | integer                                       |
| `int`           | INT           | integer                                       |
| `dword64`       | DWORD64       | integer (as string if it exceeds JS safe int) |
| `int64`         | INT64         | integer                                       |
| `float`         | FLOAT         | float                                         |
| `double`        | DOUBLE        | float                                         |
| `cexostring`    | CExoString    | string                                        |
| `resref`        | ResRef        | string, **max 16 chars**, lowercase by convention |
| `cexolocstring` | CExoLocString | object — see below                            |
| `void`          | VOID          | base64-encoded binary blob (rare in areas)    |
| `struct`        | Struct        | nested object; `__struct_id` also on the field itself, see below |
| `list`          | List          | array of struct objects                       |

### CExoLocString shape

Localized strings (used for names, descriptions) look like:

```json
{
  "type": "cexolocstring",
  "value": {
    "0": "English text here"
  }
}
```

`value` maps string-typed integer language IDs directly to text (`"0"` =
English) — there is **no** `entries`/`str_ref` wrapper inside `value` in
either build checked. `value` can legitimately be `{}` (no inline text at
all) when the string comes purely from a TLK reference.

A TLK reference (STRREF, an integer) is real but its **placement is not
stable across nwn_gff builds** — confirmed different between two builds:

```json
// Build A: "id" as a sibling of type/value
{ "type": "cexolocstring", "value": { "0": "text" }, "id": 62554 }

// Build B: "id" nested inside value, alongside language keys
{ "type": "cexolocstring", "value": { "id": 68893 } }
```

Check both locations for an `id` key before concluding a name/description is
genuinely blank — don't assume one shape without checking the actual sample.

### Struct and List nesting

A `struct`-type **field** carries `__struct_id` as a sibling of `type`/
`value`, duplicated again inside `value`:

```json
"AreaProperties": {
  "__struct_id": 100,
  "type": "struct",
  "value": { "__struct_id": 100, "SomeField": { "type": "byte", "value": 1 } }
}
```

**List entries**, by contrast, are bare structs with no `type`/`value`
wrapper at all — just `__struct_id` plus fields directly:

```json
"List": {
  "type": "list",
  "value": [
    {
      "__struct_id": 0,
      "SomeField": { "type": "byte", "value": 1 }
    }
  ]
}
```

Every object inside a `list`'s `value` array must have `__struct_id`. Missing
it is one of the most common causes of a corrupted round-trip.

## Common ARE fields (area properties)

- `Tag` (cexostring) — area tag, referenced by scripts
- `Name` (cexolocstring) — display name
- `ResRef` (resref) — must match filename
- `Width`, `Height` (dword) — tile grid dimensions
- `Tile_List` (list) — one struct per tile, includes `Tile_ID`, `Tile_Height`,
  `Tile_Orientation`
- `WeatherType`, `DayNightCycle`, `IsNight` — environment flags
- `SunAmbientColor`, `SunDiffuseColor`, `MoonAmbientColor` etc. — lighting

## Common GIT fields (area instance / placed objects)

Field name spacing is genuinely inconsistent in real output — confirmed
identical across both projects checked, so don't "clean it up":

- Spaced: `Creature List`, `Door List`, `Encounter List`, `Placeable List`
- Not spaced: `SoundList`, `StoreList`, `TriggerList`, `WaypointList`
- `List` (no qualifier) — loose items placed directly in the area, not
  inside a container (each entry shaped like a `.uti` item struct: `Tag`,
  `TemplateResRef`, `XPosition`/`YPosition`/`ZPosition`, etc.)
- `AreaProperties` — a `struct` field (see shape above), not a list

All of the `*List` fields are `list`s of bare structs (see List nesting
above).

- Each placed object struct typically has `TemplateResRef` (resref, points at
  the `.utc`/`.utp`/etc. blueprint), `Tag`, `XPosition`/`YPosition`/`ZPosition`
  (float), `XOrientation`/`YOrientation` (float)
- Triggers additionally have `Geometry` (list of vertex structs) and
  `LinkedTo`/`LinkedToFlags` for door/area transitions
- Store (`.utm`) entries in `StoreList` nest their own `StoreList` of
  item-struct lists (`$.StoreList[i].StoreList[j].ItemList[k]`) — the
  repeated name is real, not a typo, when cross-referencing validator output

## Common GIC fields (area comments)

- `Comments` (cexostring) — free-text notes, not read by the game engine,
  purely for the toolset UI. Safe to ignore unless the user asks about
  design notes.

## When in doubt

If a field isn't documented here, don't guess its type — read it from the
actual converted JSON. Preserve unknown/custom fields exactly as found rather
than dropping them; the toolset or other haks may depend on them.
