#!/usr/bin/env python3
"""Build the bundled stock NWN1 lookup JSONs in this directory from a
local NWN install. Run when bumping NWN versions (Beamdog EE patches
occasionally tweak labels — Divine Champion → Champion of Torm, etc.)
or to bootstrap a fresh checkout from authoritative sources.

Reads via `nwn_resman_extract`:
  - baseitems.2da, racialtypes.2da, classes.2da, iprp_feats.2da,
    appearance.2da, ambientmusic.2da
  - lang/en/data/dialog.tlk (TLK ref → pretty name)

Writes:
  - baseitems.json, racialtypes.json, classes.json, iprp_feats.json,
    appearance.json, music.json

Usage:
  ./_build_stock.py [--nwn DIR]

Default --nwn is ~/.local/share/Steam/steamapps/common/Neverwinter Nights.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _2da_lib import (
    col_index, load_tlk_entries, parse_2da, require_tools, resolve_name,
    tlk_to_json,
)

# (2da basename, output json basename, "Name" col, "Label" col)
#
# placeables.2da is intentionally absent: stock placeable rows are rarely
# interesting (player-visible placeables almost always come from a HAK)
# and bundling 1000+ rows of "PLC_*"-style labels would dwarf the rest of
# the file. Custom HAKs supply placeable names through the auto-detected
# CEP overlay or `--2da-dir`.
TARGETS = [
    ("baseitems.2da",   "baseitems",   "Name", "label"),
    ("racialtypes.2da", "racialtypes", "Name", "Label"),
    ("classes.2da",     "classes",     "Name", "Label"),
    ("iprp_feats.2da",  "iprp_feats",  "Name", "Label"),
    ("appearance.2da",  "appearance",  "STRING_REF", "LABEL"),
    # feat.2da / skills.2da / spells.2da power the expanded creature page
    # (named feats, skill ranks, memorized spell lists). The 2da basename
    # is "feat" (singular) but the engine uses "Feat" id refs from FeatList.
    ("feat.2da",        "feat",        "FEAT", "LABEL"),
    ("skills.2da",      "skills",      "Name", "Label"),
    ("spells.2da",      "spells",      "Name", "Label"),
    # portraits.2da has no TLK-referenced display name - BaseResRef doubles
    # as both columns, same as the CEP overlay builder (cep/_build.py).
    ("portraits.2da",   "portraits",   "BaseResRef", "BaseResRef"),
]

# baseitems.2da columns we cache as raw numeric values for weapon damage /
# range / crit display. Pure numbers — no TLK lookup needed.
WEAPON_COLS = [
    "WeaponType", "WeaponSize", "RangedWeapon", "MinRange", "MaxRange",
    "NumDice", "DieToRoll", "CritThreat", "CritHitMult", "WeaponWield",
    "AmmunitionType", "BaseAC", "ArmorCheckPen", "AC_Enchant",
]


def extract_stock_2da(nwn_root: Path, name: str, dest: Path,
                      user_dir: Path | None = None) -> Path:
    """Pull a stock 2DA out of the NWN install via nwn_resman_extract."""
    cmd = ["nwn_resman_extract", "--root", str(nwn_root)]
    if user_dir is not None:
        cmd += ["--userdirectory", str(user_dir)]
    cmd.append(name)
    subprocess.run(
        cmd, cwd=dest, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    p = dest / name
    if not p.is_file():
        raise FileNotFoundError(f"{name} not produced from {nwn_root}")
    return p


def build(nwn_dir: Path, out_dir: Path, user_dir: Path | None = None) -> None:
    require_tools()
    if shutil.which("nwn_resman_extract") is None:
        sys.exit("error: nwn_resman_extract must be on PATH "
                 "(included in the neverwinter package).")

    dialog_tlk = nwn_dir / "lang" / "en" / "data" / "dialog.tlk"
    if not dialog_tlk.exists():
        sys.exit(f"error: missing {dialog_tlk}")

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        print(f"converting dialog.tlk → json (in {tmp})")
        dialog_strings = load_tlk_entries(tlk_to_json(dialog_tlk, tmp))
        print(f"  dialog.tlk: {len(dialog_strings)} entries")

        for twoda_name, out_name, name_col, label_col in TARGETS:
            print(f"  · stock → {twoda_name}")
            try:
                twoda = extract_stock_2da(nwn_dir, twoda_name, tmp, user_dir)
            except Exception as e:
                print(f"    warn: could not extract {twoda_name}: {e}",
                      file=sys.stderr)
                continue
            headers, rows = parse_2da(twoda)
            n_idx = col_index(headers, name_col)
            l_idx = col_index(headers, label_col)
            if l_idx is None and n_idx is None:
                print(f"    warn: no '{name_col}' or '{label_col}' column; skipping",
                      file=sys.stderr)
                continue

            mapping: dict[str, str] = {}
            for row in rows:
                if not row:
                    continue
                try:
                    ridx = int(row[0])
                except ValueError:
                    continue
                name_cell = row[n_idx] if (n_idx is not None and n_idx < len(row)) else ""
                label_cell = row[l_idx] if (l_idx is not None and l_idx < len(row)) else ""
                pretty = resolve_name(name_cell, label_cell, dialog_strings, {})
                if pretty:
                    mapping[str(ridx)] = pretty

            out_path = out_dir / f"{out_name}.json"
            out_path.write_text(
                json.dumps({"_source": f"stock NWN :: {twoda_name}",
                            **mapping},
                           indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"    wrote {out_path.name}: {len(mapping)} rows")

        # Weapon stats: parse baseitems.2da once more, this time keeping
        # the numeric fields the wiki needs for the creature attack
        # schedule. Keyed by row id, so it sits alongside `baseitems.json`.
        try:
            twoda = extract_stock_2da(nwn_dir, "baseitems.2da", tmp, user_dir)
        except Exception as e:
            print(f"    warn: weapon stats: could not re-extract baseitems.2da: {e}",
                  file=sys.stderr)
        else:
            headers, rows = parse_2da(twoda)
            col_idxs = {c: col_index(headers, c) for c in WEAPON_COLS}
            weapons: dict[str, dict[str, str]] = {}
            for row in rows:
                if not row:
                    continue
                try:
                    ridx = int(row[0])
                except ValueError:
                    continue
                stats: dict[str, str] = {}
                for col, idx in col_idxs.items():
                    if idx is None or idx >= len(row):
                        continue
                    val = row[idx]
                    if val:
                        stats[col] = val
                if stats:
                    weapons[str(ridx)] = stats
            wpath = out_dir / "weapons.json"
            wpath.write_text(
                json.dumps({"_source": "stock NWN :: baseitems.2da (weapon cols)",
                            **weapons},
                           indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"    wrote {wpath.name}: {len(weapons)} rows")

        # Racial ability-score adjustments. The engine adds these to the UTC's
        # stored Str/Dex/... at runtime (e.g. Elf +2 Dex / -2 Con), so the wiki
        # must too. Keyed by race id; non-zero adjustments only.
        try:
            twoda = extract_stock_2da(nwn_dir, "racialtypes.2da", tmp, user_dir)
        except Exception as e:
            print(f"    warn: race adjust: could not re-extract racialtypes.2da: {e}",
                  file=sys.stderr)
        else:
            headers, rows = parse_2da(twoda)
            adj_cols = {ab: col_index(headers, f"{ab}Adjust")
                        for ab in ("Str", "Dex", "Con", "Int", "Wis", "Cha")}
            adjusts: dict[str, dict[str, int]] = {}
            for row in rows:
                if not row:
                    continue
                try:
                    ridx = int(row[0])
                except ValueError:
                    continue
                vals: dict[str, int] = {}
                for ab, idx in adj_cols.items():
                    if idx is None or idx >= len(row):
                        continue
                    cell = row[idx]
                    if not cell or cell == "****":
                        continue
                    try:
                        n = int(cell)
                    except ValueError:
                        continue
                    if n:
                        vals[ab] = n
                if vals:
                    adjusts[str(ridx)] = vals
            apath = out_dir / "race_adjust.json"
            apath.write_text(
                json.dumps({"_source": "stock NWN :: racialtypes.2da (*Adjust cols)",
                            **adjusts},
                           indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"    wrote {apath.name}: {len(adjusts)} rows")

        # Area music track names, as shown in the toolset's Music
        # Day/Night/Battle pickers. ambientmusic.2da doesn't fit the generic
        # TARGETS loop above: base-game rows resolve a "Description" TLK
        # strref same as everywhere else, but expansion-pack tracks (SoA/
        # HotU/Daggerford stingers) carry no strref at all and instead give
        # a literal string in "DisplayName" - resolve_name()'s Label
        # fallback would otherwise just title-case the mus_* resref.
        try:
            twoda = extract_stock_2da(nwn_dir, "ambientmusic.2da", tmp, user_dir)
        except Exception as e:
            print(f"    warn: music: could not extract ambientmusic.2da: {e}",
                  file=sys.stderr)
        else:
            headers, rows = parse_2da(twoda)
            d_idx = col_index(headers, "Description")
            r_idx = col_index(headers, "Resource")
            dn_idx = col_index(headers, "DisplayName")
            music: dict[str, str] = {}
            for row in rows:
                if not row:
                    continue
                try:
                    ridx = int(row[0])
                except ValueError:
                    continue
                desc_cell = row[d_idx] if (d_idx is not None and d_idx < len(row)) else ""
                res_cell = row[r_idx] if (r_idx is not None and r_idx < len(row)) else ""
                dn_cell = row[dn_idx] if (dn_idx is not None and dn_idx < len(row)) else ""
                pretty = resolve_name(desc_cell, res_cell, dialog_strings, {})
                if not desc_cell and dn_cell:
                    pretty = dn_cell
                if pretty:
                    music[str(ridx)] = pretty
            mpath = out_dir / "music.json"
            mpath.write_text(
                json.dumps({"_source": "stock NWN :: ambientmusic.2da",
                            **music},
                           indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"    wrote {mpath.name}: {len(music)} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    home = Path(os.path.expanduser("~"))
    ap.add_argument("--nwn", type=Path,
                    default=home / ".local" / "share" / "Steam" / "steamapps"
                    / "common" / "Neverwinter Nights",
                    help="NWN install root (containing lang/en/data/dialog.tlk)")
    ap.add_argument("--userdirectory", type=Path, default=None,
                    help="NWN user directory, if nwn_resman_extract can't "
                         "find one on its own (needed when --nwn points at "
                         "a bare data dir with no databuild.txt)")
    args = ap.parse_args()

    out_dir = Path(__file__).resolve().parent
    build(args.nwn, out_dir, args.userdirectory)
    print("done.")


if __name__ == "__main__":
    main()
