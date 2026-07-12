---
name: nwn-area-builder
description: Use this skill whenever working on a Neverwinter Nights 1:EE (NWN:EE) module or area — creating, editing, or reviewing .are/.git/.gic files, nasher projects, GFF JSON source, or NWScript (.nss) tied to an area. Trigger on mentions of "area", "toolset", "GFF", ".are"/".git"/".gic" files, nasher, nwn_gff/nwn-gff, placed objects, waypoints, triggers, tile layout, or module building for NWN1:EE — even if the user just says "add a new area" or "edit this trigger" without naming the file format. Also use to verify that GFF JSON Claude produced or edited will round-trip correctly back into valid GFF/toolset-loadable files before handing it to the user.
---

# NWN1:EE Area Builder

Helps Claude read, write, and verify Neverwinter Nights 1: Enhanced Edition area
data safely, using the niv/neverwinter.nim `nwn_gff` tool inside a `nasher` project.

## Why this skill exists

`.are`, `.git`, and `.gic` files are binary GFF (Generic File Format). Claude
cannot reliably hand-write or hand-edit binary GFF. The safe path is always:

**GFF (binary) → JSON (text, editable) → GFF (binary) → validate → nasher pack/compile**

Never attempt to construct or patch GFF bytes directly. Never guess at a field
name or type — always read it out of an actual converted JSON sample first
(see "Ground truth first" below).

## Ground truth first

Before editing any area data, get real JSON to work from:

```bash
nwn_gff -k -i path/to/file.are -o file.are.json    # GFF -> JSON
nwn_gff -j -i file.are.json -o path/to/file.are     # JSON -> GFF (round trip back)
```

If the user's project already has unpacked JSON sources (typical nasher layout:
`src/<target>/*.json`), read those directly instead of re-converting — they're
already ground truth and match what nasher will compile.

If nasher isn't installed or these commands aren't available in the current
environment, say so plainly rather than fabricating output — do not simulate
what a conversion "would" produce.

Read `references/gff-json-schema.md` before editing JSON to confirm field
names/types match what's actually in the user's file — the reference is a
guide, not a substitute for looking at the real struct.

## Standard workflow (nasher project)

1. **Unpack** (if working from a packed .mod, otherwise skip — nasher projects
   usually keep JSON sources under `src/`):
   `nasher unpack <target>`
2. **Locate** the area's three files by ResRef, e.g. for area `frontier01`:
   - `src/<target>/areas/frontier01.are.json`
   - `src/<target>/areas/frontier01.git.json`
   - `src/<target>/areas/frontier01.gic.json`
3. **Edit** the JSON directly with str_replace/create_file. Preserve key order
   and untouched fields exactly — only change what was asked.
4. **Compile any related scripts** referenced by new triggers/creatures:
   `nasher compile <target>` (uses nwnsc/nwn_script_comp under the hood; read
   compiler errors carefully, they reference the .nss line number).
5. **Convert + pack**: `nasher convert <target>` then `nasher pack <target>`.
6. **Verify** using `scripts/validate_gff_json.py` (see below) BEFORE telling
   the user the file is ready.

## Verifying output (do this every time)

Run the bundled checker on any `.are.json` / `.git.json` / `.gic.json` you
edited or created:

```bash
python3 scripts/validate_gff_json.py path/to/file.are.json
```

This catches the most common causes of toolset import failures:
- Missing required top-level fields for the file type
- ResRef strings over 16 characters (silently truncated/corrupted by the game)
- Struct list entries missing `__struct_id`
- Orphaned references (e.g. a trigger's `LinkedTo` pointing at a tag not
  present anywhere in the module's waypoints/areas — this is a heuristic
  warning, not a hard NWN rule, so surface it as a caution, not an error)
- Malformed CExoLocString structures (missing `type: "cexolocstring"` shape)

If the script reports errors, fix them and re-run before considering the task
done. If it only reports warnings, tell the user what they are and let them
decide.

For a behavior-preserving edit (e.g. moving a trigger's script without
changing its geometry), diff the JSON before/after on every field NOT
intentionally touched — this is the GFF equivalent of a characterization
test: catch accidental changes to unrelated fields.

## Reference files

- `references/gff-json-schema.md` — field type reference for the JSON shape
  nwn_gff produces (types, struct/list nesting, CExoLocString, common ARE/GIT
  field names) — read this before writing raw JSON by hand
- `references/nasher-commands.md` — nasher CLI cheat sheet (unpack, compile,
  convert, pack, install) and nasher.cfg layout notes

## Common pitfalls to flag proactively

- Editing a `.mod`'s temp-unpacked files directly instead of the nasher `src/`
  sources — changes will be lost on next `nasher pack`.
- ResRefs longer than 16 characters or containing spaces/uppercase
  inconsistently (NWN ResRefs are case-insensitive on disk but some tools are
  picky about casing consistency).
- Adding a GIT entry (creature/placeable/trigger) without a corresponding
  unique `TemplateResRef` or leaving `__struct_id` off a new list entry.
- Forgetting to compile new/changed `.nss` scripts before packing — the area
  will load but the script logic silently won't run (or nwnsc will fail loud,
  which is preferable — always compile before packing, never after).
