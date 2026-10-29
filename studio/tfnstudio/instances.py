"""Build GIT object instances from blueprints/templates and manipulate GIT lists.

Conventions verified against TFN's own nasher output:
  * creature  instance = UTC blueprint - {Comment, PaletteID, __data_type}
                         + {XPosition, YPosition, ZPosition, XOrientation, YOrientation}
  * placeable instance = UTP-shaped struct + {X, Y, Z, Bearing}
  * waypoint  instance = UTW blueprint - {Comment, PaletteID, __data_type} + position/orientation
  * the blueprint's VarTable is copied onto the instance (omitted when empty)
  * instance keys are sorted case-insensitively after `__struct_id`
"""

from __future__ import annotations

import math
import statistics
from typing import Iterable

from . import gffjson as G

PLAN_VAR = "studio_plan"
TILE_SIZE = 10.0

KIND_LIST = {
    "creature": "Creature List",
    "placeable": "Placeable List",
    "waypoint": "WaypointList",
    "door": "Door List",
    "trigger": "TriggerList",
    "sound": "SoundList",
    "store": "StoreList",
    "encounter": "Encounter List",
}
STRUCT_ID = {"creature": 4, "placeable": 9, "waypoint": 5, "door": 8, "trigger": 1,
             "sound": 6, "store": 11, "encounter": 7}
_BLUEPRINT_ONLY = ("__data_type", "Comment", "PaletteID")


# ------------------------------------------------------------------ geometry
def snap(v: float, ndigits: int = 4) -> float:
    """Round like the toolset (4 decimals) and never emit -0.0."""
    return round(float(v), ndigits) + 0.0


def orientation(facing_deg: float) -> tuple[float, float]:
    """(XOrientation, YOrientation) for a facing in degrees (0 = east, 90 = north)."""
    rad = math.radians(facing_deg)
    return snap(math.cos(rad), 6), snap(math.sin(rad), 6)


def bearing(facing_deg: float) -> float:
    """Placeable `Bearing` (radians, normalised to (-pi, pi])."""
    rad = math.radians(facing_deg)
    rad = math.atan2(math.sin(rad), math.cos(rad))
    return snap(rad, 4)


def area_extent(are: dict) -> tuple[float, float]:
    return G.get(are, "Width", 0) * TILE_SIZE, G.get(are, "Height", 0) * TILE_SIZE


def in_bounds(are: dict, x: float, y: float, margin: float = 0.0) -> bool:
    w, h = area_extent(are)
    return margin <= x <= w - margin and margin <= y <= h - margin


def position_of(kind: str, inst: dict) -> tuple[float, float, float]:
    if kind in ("creature", "waypoint"):
        return (G.get(inst, "XPosition", 0.0), G.get(inst, "YPosition", 0.0), G.get(inst, "ZPosition", 0.0))
    return (G.get(inst, "X", 0.0), G.get(inst, "Y", 0.0), G.get(inst, "Z", 0.0))


def all_positions(git: dict) -> list[tuple[float, float, float]]:
    pts = []
    for kind in ("creature", "placeable", "waypoint", "door"):
        for inst in (git.get(KIND_LIST[kind]) or {}).get("value", []):
            pts.append(position_of(kind, inst))
    return pts


def infer_z(git: dict, x: float, y: float, radius: float = 8.0) -> tuple[float, str]:
    """Best-guess ground height at (x, y) from existing objects. Returns (z, confidence)."""
    pts = all_positions(git)
    if not pts:
        return 0.0, "default"
    px, py, pz = min(pts, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)
    if math.hypot(px - x, py - y) <= radius:
        return snap(pz), "near"
    zs = [p[2] for p in pts]
    if max(zs) - min(zs) < 0.01:
        return snap(zs[0]), "flat"
    return snap(statistics.median(zs)), "area_median"


# ------------------------------------------------------------- key ordering
def sort_instance(inst: dict) -> dict:
    """`__struct_id` first, then case-insensitive alphabetical (what the toolset writes)."""
    keys = sorted((k for k in inst if k != "__struct_id"), key=str.lower)
    out = {"__struct_id": inst.get("__struct_id", 0)}
    for k in keys:
        out[k] = inst[k]
    return out


def _finish(inst: dict, kind: str, plan: str | None, tag: str | None,
            extra_vars: dict | None) -> dict:
    inst["__struct_id"] = STRUCT_ID[kind]
    if tag is not None:
        inst["Tag"] = G.cexostring(tag)
    if plan:
        G.set_var(inst, PLAN_VAR, plan)
    for name, value in (extra_vars or {}).items():
        G.set_var(inst, name, value)
    vt = inst.get("VarTable")
    if vt is not None and not vt["value"]:
        del inst["VarTable"]  # the toolset omits empty VarTables on instances
    return sort_instance(inst)


# ---------------------------------------------------------------- builders
def creature_instance(blueprint: dict, x: float, y: float, z: float, facing: float = 90.0, *,
                      plan: str | None = None, tag: str | None = None,
                      extra_vars: dict | None = None) -> dict:
    inst = G.clone(blueprint)
    for k in _BLUEPRINT_ONLY:
        inst.pop(k, None)
    xo, yo = orientation(facing)
    inst["XPosition"] = G.float_(snap(x))
    inst["YPosition"] = G.float_(snap(y))
    inst["ZPosition"] = G.float_(snap(z))
    inst["XOrientation"] = G.float_(xo)
    inst["YOrientation"] = G.float_(yo)
    return _finish(inst, "creature", plan, tag, extra_vars)


def placeable_instance(template: dict, x: float, y: float, z: float, facing: float = 0.0, *,
                       plan: str | None = None, tag: str | None = None,
                       extra_vars: dict | None = None) -> dict:
    """`template` is a UTP blueprint or a full placeable instance struct."""
    inst = G.clone(template)
    for k in _BLUEPRINT_ONLY:
        inst.pop(k, None)
    inst["X"] = G.float_(snap(x))
    inst["Y"] = G.float_(snap(y))
    inst["Z"] = G.float_(snap(z))
    inst["Bearing"] = G.float_(bearing(facing))
    return _finish(inst, "placeable", plan, tag, extra_vars)


def waypoint_instance(blueprint: dict, x: float, y: float, z: float, facing: float = 90.0, *,
                      plan: str | None = None, tag: str | None = None,
                      extra_vars: dict | None = None) -> dict:
    inst = G.clone(blueprint)
    for k in _BLUEPRINT_ONLY:
        inst.pop(k, None)
    xo, yo = orientation(facing)
    inst["XPosition"] = G.float_(snap(x))
    inst["YPosition"] = G.float_(snap(y))
    inst["ZPosition"] = G.float_(snap(z))
    inst["XOrientation"] = G.float_(xo)
    inst["YOrientation"] = G.float_(yo)
    return _finish(inst, "waypoint", plan, tag, extra_vars)


# --------------------------------------------------------------- GIT lists
def instances(git: dict, kind: str) -> list[dict]:
    return (git.get(KIND_LIST[kind]) or {}).get("value", [])


def add_instance(git: dict, kind: str, inst: dict) -> None:
    name = KIND_LIST[kind]
    if git.get(name) is None:
        git[name] = G.list_()
    git[name]["value"].append(inst)


def remove_plan_instances(git: dict, plan: str) -> int:
    """Remove every instance (any kind) generated by `plan`. Returns how many were removed."""
    removed = 0
    for kind, name in KIND_LIST.items():
        lst = git.get(name)
        if not lst:
            continue
        keep = [i for i in lst["value"] if G.get_var(i, PLAN_VAR) != plan]
        removed += len(lst["value"]) - len(keep)
        lst["value"] = keep
    return removed


def plan_instances(git: dict, plan: str) -> Iterable[tuple[str, dict]]:
    for kind in KIND_LIST:
        for inst in instances(git, kind):
            if G.get_var(inst, PLAN_VAR) == plan:
                yield kind, inst


def set_area_var(git: dict, name: str, value: int | float | str) -> None:
    G.set_var(git, name, value)


def del_area_var(git: dict, name: str) -> bool:
    return G.del_var(git, name)
