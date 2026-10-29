"""Camp prefabs: reusable layouts of props/creatures/spawn markers, stamped at a point.

A prefab is a JSON file in `prefabs/`:
  {"id", "name", "description", "tags": [...], "radius": meters,
   "items": [{"kind": "placeable|creature|marker|waypoint", "resref": "...", "group": 1,
              "dx": 0.0, "dy": 0.0, "facing": 0.0, "tag": ""}]}
Offsets are meters relative to the stamp point, +y = north.  `facing` is degrees
(0 = east, 90 = north).  Markers use `group` (1-9) instead of a resref.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .project import STUDIO_ROOT, ProjectError

PREFAB_DIR = STUDIO_ROOT / "prefabs"
ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
KINDS = ("placeable", "creature", "marker", "waypoint")


def validate_prefab(data: dict) -> dict:
    if not isinstance(data, dict) or not ID_RE.match(str(data.get("id", ""))):
        raise ProjectError("prefab id must be 1-40 chars of a-z, 0-9, _")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ProjectError("prefab needs a non-empty items list")
    clean = []
    for i, it in enumerate(items):
        kind = it.get("kind")
        if kind not in KINDS:
            raise ProjectError(f"item {i}: kind must be one of {KINDS}")
        item = {"kind": kind, "dx": float(it.get("dx", 0)), "dy": float(it.get("dy", 0)),
                "facing": float(it.get("facing", 0))}
        if kind == "marker":
            g = int(it.get("group", 1))
            if not 1 <= g <= 9:
                raise ProjectError(f"item {i}: marker group must be 1-9")
            item["group"] = g
        else:
            res = str(it.get("resref", ""))
            if not re.match(r"^[A-Za-z0-9_]{1,32}$", res):
                raise ProjectError(f"item {i}: bad resref {res!r}")
            item["resref"] = res
        if it.get("tag"):
            item["tag"] = str(it["tag"])[:32]
        clean.append(item)
    radius = float(data.get("radius") or max((math.hypot(c["dx"], c["dy"]) for c in clean), default=1.0))
    return {"id": data["id"], "name": str(data.get("name") or data["id"]), "description": str(data.get("description", "")),
            "tags": [str(t) for t in data.get("tags", [])], "radius": round(radius, 2), "items": clean}


def load_prefabs(directory: Path | None = None) -> dict[str, dict]:
    d = directory or PREFAB_DIR
    out: dict[str, dict] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            data = validate_prefab(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, ProjectError):
            continue
        out[data["id"]] = data
    return out


def save_prefab(data: dict, directory: Path | None = None) -> Path:
    clean = validate_prefab(data)
    d = directory or PREFAB_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{clean['id']}.json"
    p.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    return p


def stamp(prefab: dict, x: float, y: float, rotation: float = 0.0,
          group_map: dict[int, int] | None = None) -> list[dict]:
    """Camp-plan objects for `prefab` placed at (x, y), rotated CCW by `rotation` degrees."""
    p = validate_prefab(prefab)
    rad = math.radians(rotation)
    c, s = math.cos(rad), math.sin(rad)
    out = []
    for it in p["items"]:
        ox = it["dx"] * c - it["dy"] * s
        oy = it["dx"] * s + it["dy"] * c
        obj = {"kind": it["kind"], "x": round(x + ox, 4), "y": round(y + oy, 4),
               "facing": round((it["facing"] + rotation) % 360, 2)}
        if it["kind"] == "marker":
            obj["group"] = (group_map or {}).get(it["group"], it["group"])
        else:
            obj["resref"] = it["resref"]
        if it.get("tag"):
            obj["tag"] = it["tag"]
        out.append(obj)
    return out


def from_objects(prefab_id: str, name: str, objects: list[dict], origin: tuple[float, float],
                 description: str = "", tags: list[str] | None = None) -> dict:
    """Build a prefab from absolute-positioned plan objects (e.g. a UI selection)."""
    ox, oy = origin
    items = []
    for o in objects:
        it = {"kind": o["kind"], "dx": round(o["x"] - ox, 3), "dy": round(o["y"] - oy, 3),
              "facing": round(float(o.get("facing", 0)), 2)}
        if o["kind"] == "marker":
            it["group"] = int(o.get("group", 1))
        else:
            it["resref"] = o["resref"]
        if o.get("tag"):
            it["tag"] = o["tag"]
        items.append(it)
    return validate_prefab({"id": prefab_id, "name": name, "description": description,
                            "tags": tags or [], "items": items})
