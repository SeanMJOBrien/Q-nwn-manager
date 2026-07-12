#!/usr/bin/env python3
"""
validate_gff_json.py

Sanity-checks a GFF-as-JSON file (the format produced by niv/neverwinter.nim's
nwn_gff -k, and compatible with nwn-lib-d's json_legacy output) BEFORE it gets
converted back to binary GFF and packed into a module.

This is a heuristic pre-flight check, not a full GFF spec validator. It exists
to catch the mistakes that most commonly corrupt a round-trip or cause silent
toolset import failures:

  - missing __data_type at root
  - ResRefs over 16 characters
  - list entries missing __struct_id
  - malformed cexolocstring shape
  - duplicate Tag values across placed objects in a .git file (common cause
    of scripts firing on the wrong object)

Ground truth for this shape was cross-checked against real nwn_gff output
from two separate projects (hos1's flat unpacked repo and the-frozen-north's
nasher `src/<type>/*.json` layout) — see gff-json-schema.md for details.

Usage:
    python3 validate_gff_json.py path/to/file.are.json [more files...]

Exit code is 0 if no errors (warnings are still printed but don't fail the
run), non-zero if any errors were found.
"""

import sys
import json
from pathlib import Path

MAX_RESREF_LEN = 16

REQUIRED_ROOT_FIELDS_BY_TYPE = {
    "ARE ": ["Tag", "ResRef", "Width", "Height"],
    "GIT ": [],  # GIT's required fields are mostly the *List fields, checked separately
    "GIC ": [],
}

# Field names are inconsistent about spacing in real nwn_gff output — some
# have a space, some don't. Confirmed against actual .git.json samples;
# don't "clean up" these names to a consistent style.
GIT_LIST_FIELDS = [
    "Creature List",
    "Door List",
    "Encounter List",
    "List",  # loose items placed directly in the area (not in a container)
    "Placeable List",
    "SoundList",
    "StoreList",
    "TriggerList",
    "WaypointList",
]


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def walk_structs(node, path, errors, warnings, tag_locations):
    """Recursively walk the GFF JSON tree, checking struct/list/resref/locstring shape."""
    if isinstance(node, dict):
        # Is this a field-value wrapper? {"type": ..., "value": ...}. Don't
        # require an exact 2-key match: a "struct"-type field carries a
        # sibling __struct_id, and a TLK-referenced cexolocstring carries a
        # sibling "id" (the STRREF) alongside type/value.
        if "type" in node and "value" in node:
            ftype = node["type"]
            fval = node["value"]

            if ftype == "resref":
                if not isinstance(fval, str):
                    errors.append(f"{path}: resref value is not a string: {fval!r}")
                elif len(fval) > MAX_RESREF_LEN:
                    errors.append(
                        f"{path}: resref '{fval}' is {len(fval)} chars, "
                        f"max is {MAX_RESREF_LEN} — will be silently truncated by the game"
                    )
                elif fval != fval.lower():
                    warnings.append(
                        f"{path}: resref '{fval}' has uppercase characters — "
                        f"NWN resrefs are conventionally lowercase"
                    )

            elif ftype == "cexolocstring":
                # Real shape: "value" is a flat dict mapping string-typed
                # language IDs directly to text, e.g. {"0": "text"} — there
                # is no nested "entries"/"str_ref" wrapper. A TLK reference
                # (STRREF) is an integer "id" — but *where* it appears is not
                # stable across nwn_gff builds: some put it as a sibling of
                # "type"/"value" on the field wrapper, others nest it inside
                # "value" alongside the language-id keys. Accept either.
                # An empty/id-only value is valid when the string comes
                # entirely from the TLK.
                if not isinstance(fval, dict):
                    errors.append(
                        f"{path}: cexolocstring value is not an object: {fval!r}"
                    )
                else:
                    has_tlk_id = "id" in node or "id" in fval
                    lang_entries = {k: v for k, v in fval.items() if k != "id"}
                    if not lang_entries and not has_tlk_id:
                        warnings.append(
                            f"{path}: cexolocstring has no inline text and no "
                            f"TLK 'id' reference — likely an unset name/description"
                        )
                    elif not all(isinstance(k, str) and k.isdigit() for k in lang_entries):
                        warnings.append(
                            f"{path}: cexolocstring value has non-language-id "
                            f"keys: {list(lang_entries.keys())!r}"
                        )

            elif ftype == "struct":
                if not isinstance(fval, dict) or "__struct_id" not in fval:
                    errors.append(f"{path}: nested struct missing __struct_id")
                walk_structs(fval, path + ".value", errors, warnings, tag_locations)

            elif ftype == "list":
                if not isinstance(fval, list):
                    errors.append(f"{path}: list field's value is not an array")
                else:
                    for i, item in enumerate(fval):
                        item_path = f"{path}[{i}]"
                        if not isinstance(item, dict) or "__struct_id" not in item:
                            errors.append(f"{item_path}: list entry missing __struct_id")
                        walk_structs(item, item_path, errors, warnings, tag_locations)
            return

        # Otherwise it's a struct-like object — recurse into its fields
        if "Tag" in node:
            tagfield = node["Tag"]
            if isinstance(tagfield, dict) and tagfield.get("type") == "cexostring":
                tag_val = tagfield.get("value")
                if tag_val:
                    tag_locations.setdefault(tag_val, []).append(path)

        for key, value in node.items():
            if key in ("__data_type", "__struct_id"):
                continue
            walk_structs(value, f"{path}.{key}", errors, warnings, tag_locations)

    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk_structs(item, f"{path}[{i}]", errors, warnings, tag_locations)


def validate(path):
    errors = []
    warnings = []

    try:
        data = load(path)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"], []

    if "__data_type" not in data:
        errors.append("Missing __data_type at root — is this really a GFF JSON export?")
    # Note: the root struct does NOT carry __struct_id — that's only present
    # on nested struct fields and list entries. Don't flag its absence here.

    dtype = data.get("__data_type", "").ljust(4) if data.get("__data_type") else ""
    required = REQUIRED_ROOT_FIELDS_BY_TYPE.get(dtype, [])
    for field in required:
        if field not in data:
            errors.append(f"Missing required field '{field}' for file type '{dtype.strip()}'")

    if dtype == "GIT ":
        present_lists = [f for f in GIT_LIST_FIELDS if f in data]
        if not present_lists:
            warnings.append(
                "No recognized *List fields found in a GIT file — "
                "unusual unless this is an intentionally empty area"
            )

    tag_locations = {}
    walk_structs(data, "$", errors, warnings, tag_locations)

    for tag, locations in tag_locations.items():
        if len(locations) > 1:
            warnings.append(
                f"Tag '{tag}' used at {len(locations)} locations: {locations} — "
                f"duplicate tags can cause scripts (GetObjectByTag) to hit the wrong object"
            )

    return errors, warnings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    any_errors = False
    for path_str in sys.argv[1:]:
        path = Path(path_str)
        if not path.exists():
            print(f"✗ {path}: file not found")
            any_errors = True
            continue

        errors, warnings = validate(path)

        print(f"\n=== {path} ===")
        if not errors and not warnings:
            print("✓ No issues found")
        for e in errors:
            print(f"✗ ERROR: {e}")
        for w in warnings:
            print(f"⚠ WARNING: {w}")

        if errors:
            any_errors = True

    sys.exit(1 if any_errors else 0)


if __name__ == "__main__":
    main()
