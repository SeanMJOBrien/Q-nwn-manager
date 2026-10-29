"""Cached, incremental summaries of TFN content for the UI and the generators.

Parsing all of src/git (hundreds of MB of JSON) takes tens of seconds, so each
summary is cached on disk keyed by file mtime+size and only changed files are
re-read.  Caches live in `<studio>/.studio/cache/` and are safe to delete.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from . import gffjson as G
from .project import TfnProject

Progress = Optional[Callable[[str, int, int], None]]   # (Optional keeps Python 3.9 working)

QUEST_VALUE_RE = re.compile(r"^(\d\d)_([qb]_[A-Za-z0-9_]+)$")
CACHE_VERSION = 6


# ---------------------------------------------------------------------------
# cache plumbing
# ---------------------------------------------------------------------------

def _load_cache(project: TfnProject, name: str) -> dict:
    p = project.cache_dir / f"{name}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") == CACHE_VERSION:
            return data.get("entries", {})
    except (OSError, ValueError):
        pass
    return {}


def _save_cache(project: TfnProject, name: str, entries: dict) -> None:
    project.cache_dir.mkdir(parents=True, exist_ok=True)
    p = project.cache_dir / f"{name}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": CACHE_VERSION, "entries": entries}, separators=(",", ":")),
                   encoding="utf-8")
    tmp.replace(p)


def _stamp(p: Path) -> list[int]:
    try:
        st = p.stat()
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return [0, 0]


def _incremental(project: TfnProject, cache_name: str, ext: str,
                 summarize: Callable[[str, dict], dict], progress: Progress = None) -> dict[str, dict]:
    cache = _load_cache(project, cache_name)
    names = project.list_resrefs(ext)
    out: dict[str, dict] = {}
    changed = False
    for i, resref in enumerate(names):
        path = project.json_path(ext, resref)
        stamp = _stamp(path)
        ent = cache.get(resref)
        if ent and ent.get("k") == stamp:
            out[resref] = ent["s"]
        else:
            try:
                s = summarize(resref, G.read(path))
            except (OSError, ValueError) as exc:  # unreadable file: record the problem, keep going
                s = {"resref": resref, "error": str(exc)}
            cache[resref] = {"k": stamp, "s": s}
            out[resref] = s
            changed = True
        if progress and i % 25 == 0:
            progress(f"{ext}", i, len(names))
    for gone in set(cache) - set(names):
        del cache[gone]
        changed = True
    if changed:
        _save_cache(project, cache_name, cache)
    if progress:
        progress(f"{ext}", len(names), len(names))
    return out


# ---------------------------------------------------------------------------
# creatures
# ---------------------------------------------------------------------------

MARKER_RE = re.compile(r"^random([1-9])$")


def creature_kind(resref: str, bp: dict) -> str:
    if MARKER_RE.match(resref):
        return "marker"
    if resref.startswith("hen_"):
        return "henchman"
    if G.get(bp, "Conversation") or G.get(bp, "Plot"):
        return "npc"
    if G.get(bp, "FactionID") == 1:
        return "monster"
    return "other"


def summarize_creature(resref: str, bp: dict) -> dict:
    vars_ = G.vars_of(bp)
    first, last = G.get_text(bp, "FirstName"), G.get_text(bp, "LastName")
    return {
        "resref": resref,
        "name": (first + " " + last).strip(),
        "cr": G.get(bp, "ChallengeRating", 0.0),
        "faction": G.get(bp, "FactionID"),
        "race": G.get(bp, "Race"),
        "appearance": G.get(bp, "Appearance_Type"),
        "gender": G.get(bp, "Gender"),
        "classes": [[G.get(c, "Class"), G.get(c, "ClassLevel")] for c in (bp.get("ClassList") or {}).get("value", [])],
        "plot": G.get(bp, "Plot", 0),
        "immortal": G.get(bp, "IsImmortal", 0),
        "conversation": G.get(bp, "Conversation", ""),
        "script_death": G.get(bp, "ScriptDeath", ""),
        "palette": G.get(bp, "PaletteID"),
        "boss": vars_.get("boss", 0),
        "quest_vars": {k: v for k, v in vars_.items() if k.startswith("quest")},
        "kind": creature_kind(resref, bp),
    }


def creature_index(project: TfnProject, progress: Progress = None) -> dict[str, dict]:
    return _incremental(project, "creatures", "utc", summarize_creature, progress)


# ---------------------------------------------------------------------------
# items
# ---------------------------------------------------------------------------

def summarize_item(resref: str, bp: dict) -> dict:
    vars_ = G.vars_of(bp)
    return {
        "resref": resref,
        "name": G.get_text(bp, "LocalizedName"),
        "tag": G.get(bp, "Tag", ""),
        "base_item": G.get(bp, "BaseItem"),
        "cost": G.get(bp, "Cost", 0),
        "plot": G.get(bp, "Plot", 0),
        "quest_vars": {k: v for k, v in vars_.items() if k.startswith("quest")},
    }


def item_index(project: TfnProject, progress: Progress = None) -> dict[str, dict]:
    return _incremental(project, "items", "uti", summarize_item, progress)


# ---------------------------------------------------------------------------
# encounter blueprints (.ute)
# ---------------------------------------------------------------------------

UNIQUE_CHANCE = {0: 5, 1: 10, 2: 15, 3: 20, 4: 25}
DIFFICULTY_NAMES = {0: "Very Easy", 1: "Easy", 2: "Normal", 3: "Hard", 4: "Impossible"}


def summarize_ute(resref: str, bp: dict) -> dict:
    creatures = [{
        "resref": G.get(c, "ResRef", ""),
        "cr": G.get(c, "CR", 0.0),
        "unique": bool(G.get(c, "SingleSpawn", 0)),
        "appearance": G.get(c, "Appearance", 0),
    } for c in (bp.get("CreatureList") or {}).get("value", [])]
    diff = G.get(bp, "DifficultyIndex", 2)
    return {
        "resref": resref,
        "name": G.get_text(bp, "LocalizedName", resref),
        "difficulty": diff,
        "unique_chance": UNIQUE_CHANCE.get(diff, 5),
        "creatures": creatures,
        "rare": G.get_var(bp, "rare", ""),
    }


def ute_index(project: TfnProject, progress: Progress = None) -> dict[str, dict]:
    return _incremental(project, "utes", "ute", summarize_ute, progress)


# ---------------------------------------------------------------------------
# areas (ARE + GIT)
# ---------------------------------------------------------------------------

OBJECT_LISTS = {
    "creatures": "Creature List",
    "placeables": "Placeable List",
    "waypoints": "WaypointList",
    "doors": "Door List",
    "triggers": "TriggerList",
    "encounters": "Encounter List",
    "sounds": "SoundList",
    "stores": "StoreList",
}
HOOK_VARS = ("init_script", "enter_script", "exit_script", "refresh_script", "prettify_script")


def summarize_area(resref: str, are: dict, git: dict | None) -> dict:
    flags = G.get(are, "Flags", 0)
    s: dict = {
        "resref": resref,
        "tag": G.get(are, "Tag", resref),
        "name": G.get_text(are, "Name", resref),
        "width": G.get(are, "Width", 0),
        "height": G.get(are, "Height", 0),
        "tileset": G.get(are, "Tileset", ""),
        "interior": bool(flags & 1),
        "underground": bool(flags & 2),
        "natural": bool(flags & 4),
        "has_git": git is not None,
        "cr": None, "groups": [], "events": [], "hooks": {}, "counts": {}, "markers": {},
        "plans": [], "quest_refs": [], "pl": {}, "cre": {}, "cre_meta": {}, "event_wps": 0,
    }
    if git is None:
        return s
    gv = G.vars_of(git)
    s["cr"] = gv.get("cr")
    s["trapped"] = gv.get("trapped")
    s["event_chance"] = gv.get("event_chance")
    for n in range(1, 10):
        if gv.get(f"random{n}"):
            s["groups"].append({"n": n, "ute": gv[f"random{n}"],
                                "spawns": gv.get(f"random{n}_spawns", 0),
                                "script": gv.get(f"random{n}_spawn_script", "")})
        if gv.get(f"event{n}"):
            s["events"].append({"n": n, "script": gv[f"event{n}"]})
    s["hooks"] = {k: gv[k] for k in HOOK_VARS if gv.get(k)}
    plans: set[str] = set()
    markers: Counter = Counter()
    pl: dict[str, list] = {}
    quest_refs: list[dict] = []
    for key, list_name in OBJECT_LISTS.items():
        items = (git.get(list_name) or {}).get("value", [])
        s["counts"][key] = len(items)
        for inst in items:
            iv = G.vars_of(inst)
            if iv.get("studio_plan"):
                plans.add(iv["studio_plan"])
            if key == "waypoints" and G.get(inst, "TemplateResRef", "") == "_wp_event":
                s["event_wps"] += 1     # area_init counts these: events only run when there is at least one
            if key == "creatures":
                res = G.get(inst, "TemplateResRef", "")
                s["cre"][res] = s["cre"].get(res, 0) + 1
                if res not in s["cre_meta"]:
                    nm = (G.get_text(inst, "FirstName") + " " + G.get_text(inst, "LastName")).strip()
                    s["cre_meta"][res] = [nm or G.get(inst, "Tag", "") or res, G.get(inst, "ChallengeRating", 0.0),
                                          G.get(inst, "FactionID")]
                m = MARKER_RE.match(res)
                if m:
                    markers[int(m.group(1))] += 1
                for vn, vv in iv.items():
                    if vn.startswith("quest") and isinstance(vv, str) and QUEST_VALUE_RE.match(vv):
                        quest_refs.append({"npc": res, "var": vn, "value": vv})
            elif key == "placeables":
                res = G.get(inst, "TemplateResRef", "")
                ent = pl.get(res)
                if ent is None:
                    pl[res] = [1, G.get(inst, "Appearance", 0), G.get_text(inst, "LocName"),
                               G.get(inst, "HasInventory", 0), G.get(inst, "Useable", 0),
                               G.get(inst, "Static", 0), G.get(inst, "Plot", 0)]
                else:
                    ent[0] += 1
    s["markers"] = {str(k): v for k, v in sorted(markers.items())}
    s["plans"] = sorted(plans)
    s["quest_refs"] = quest_refs
    s["pl"] = pl
    return s


def area_index(project: TfnProject, progress: Progress = None) -> dict[str, dict]:
    cache = _load_cache(project, "areas")
    names = project.list_resrefs("are")
    out: dict[str, dict] = {}
    changed = False
    for i, resref in enumerate(names):
        are_p = project.json_path("are", resref)
        git_p = project.json_path("git", resref)
        stamp = _stamp(are_p) + _stamp(git_p)
        ent = cache.get(resref)
        if ent and ent.get("k") == stamp:
            out[resref] = ent["s"]
        else:
            try:
                are = G.read(are_p)
                git = G.read(git_p) if git_p.is_file() else None
                s = summarize_area(resref, are, git)
            except (OSError, ValueError) as exc:
                s = {"resref": resref, "error": str(exc), "groups": [], "counts": {}, "plans": [], "pl": {},
                     "name": resref, "width": 0, "height": 0}
            cache[resref] = {"k": stamp, "s": s}
            out[resref] = s
            changed = True
        if progress and i % 10 == 0:
            progress("areas", i, len(names))
    for gone in set(cache) - set(names):
        del cache[gone]
        changed = True
    if changed:
        _save_cache(project, "areas", cache)
    if progress:
        progress("areas", len(names), len(names))
    return out


def refresh_area(project: TfnProject, resref: str) -> dict:
    """Re-summarize a single area (after Apply) without a full index pass."""
    cache = _load_cache(project, "areas")
    are_p, git_p = project.json_path("are", resref), project.json_path("git", resref)
    are = G.read(are_p)
    git = G.read(git_p) if git_p.is_file() else None
    s = summarize_area(resref, are, git)
    cache[resref] = {"k": _stamp(are_p) + _stamp(git_p), "s": s}
    _save_cache(project, "areas", cache)
    return s


# ---------------------------------------------------------------------------
# placeable palette (mined from real GIT instances)
# ---------------------------------------------------------------------------

def classify_placeable(resref: str, has_inventory: int, useable: int, name: str) -> str:
    low = (resref + " " + name).lower()
    if resref.startswith("plx_"):
        return "respawning"
    if has_inventory:
        return "container"
    if any(w in low for w in ("fire", "flame", "torch", "lamp", "candle", "brazier", "lantern")):
        return "light"
    if useable:
        return "usable"
    return "decor"


def placeable_palette(project: TfnProject, areas: dict[str, dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for a in areas.values():
        for res, v in (a.get("pl") or {}).items():
            e = agg.get(res)
            if e is None:
                agg[res] = {"resref": res, "count": v[0], "areas": 1, "appearance": v[1], "name": v[2],
                            "has_inventory": v[3], "useable": v[4], "static": v[5], "plot": v[6]}
            else:
                e["count"] += v[0]
                e["areas"] += 1
                if not e["name"] and v[2]:
                    e["name"] = v[2]
    utp = set(project.list_resrefs("utp"))
    out = []
    for e in agg.values():
        e["tfn_blueprint"] = e["resref"] in utp
        e["kind"] = classify_placeable(e["resref"], e["has_inventory"], e["useable"], e["name"])
        out.append(e)
    # blueprints that exist in src/utp but are not used in any GIT yet
    for res in sorted(utp - set(agg)):
        try:
            bp = project.read("utp", res)
        except Exception:
            continue
        name = G.get_text(bp, "LocName")
        e = {"resref": res, "count": 0, "areas": 0, "appearance": G.get(bp, "Appearance", 0), "name": name,
             "has_inventory": G.get(bp, "HasInventory", 0), "useable": G.get(bp, "Useable", 0),
             "static": G.get(bp, "Static", 0), "plot": G.get(bp, "Plot", 0), "tfn_blueprint": True}
        e["kind"] = classify_placeable(res, e["has_inventory"], e["useable"], name)
        out.append(e)
    out.sort(key=lambda e: (-e["count"], e["resref"]))
    return out


_PLACE_VOLATILE = ("X", "Y", "Z", "Bearing", "Tag", "VarTable", "__struct_id")
_CREATURE_VOLATILE = ("XPosition", "YPosition", "ZPosition", "XOrientation", "YOrientation", "Tag", "VarTable",
                      "__struct_id")


def _signature(inst: dict) -> str:
    return json.dumps({k: v for k, v in inst.items() if k not in _PLACE_VOLATILE}, sort_keys=True)


def mine_placeable_template(project: TfnProject, areas: dict[str, dict], resref: str) -> dict | None:
    """The most common (mode) full instance struct for `resref` seen in TFN GITs.

    Scans at most a few areas, smallest GIT first, so it stays fast.  Returns a
    deep copy with position fields still present (callers overwrite them).
    """
    holders = [a["resref"] for a in areas.values() if resref in (a.get("pl") or {})]
    holders.sort(key=lambda r: project.json_path("git", r).stat().st_size)
    sigs: Counter = Counter()
    example: dict[str, dict] = {}
    for area in holders[:3]:
        git = project.read_path(project.json_path("git", area))
        for inst in (git.get("Placeable List") or {}).get("value", []):
            if G.get(inst, "TemplateResRef") != resref:
                continue
            sig = _signature(inst)
            sigs[sig] += 1
            example.setdefault(sig, inst)
        if sigs and sum(sigs.values()) >= 5:
            break
    if not sigs:
        return None
    best = sigs.most_common(1)[0][0]
    return G.clone(example[best])


def base_creature_palette(areas: dict[str, dict], tfn_creatures: dict[str, dict]) -> list[dict]:
    """Creatures TFN areas place that have no `src/utc` blueprint (base-game ones), mined from real instances."""
    agg: dict[str, dict] = {}
    for a in areas.values():
        for res, n in (a.get("cre") or {}).items():
            if res in tfn_creatures or MARKER_RE.match(res) or not res:
                continue
            meta = (a.get("cre_meta") or {}).get(res) or [res, 0.0, None]
            e = agg.setdefault(res, {"resref": res, "name": meta[0], "cr": meta[1], "faction": meta[2], "count": 0,
                                     "areas": 0, "kind": "base", "source": "placed in TFN"})
            e["count"] += n
            e["areas"] += 1
    return sorted(agg.values(), key=lambda e: (-e["count"], e["resref"]))


def mine_creature_template(project: TfnProject, areas: dict[str, dict], resref: str) -> dict | None:
    """The most common real instance of a creature that has no TFN blueprint, minus instance-specific variables."""
    holders = [a["resref"] for a in areas.values() if (a.get("cre") or {}).get(resref)]
    holders.sort(key=lambda r: project.json_path("git", r).stat().st_size)
    sigs: Counter = Counter()
    example: dict[str, dict] = {}
    for area in holders[:3]:
        git = project.read_path(project.json_path("git", area))
        for inst in (git.get("Creature List") or {}).get("value", []):
            if G.get(inst, "TemplateResRef") != resref:
                continue
            sig = json.dumps({k: v for k, v in inst.items() if k not in _CREATURE_VOLATILE}, sort_keys=True)
            sigs[sig] += 1
            example.setdefault(sig, inst)
        if sigs and sum(sigs.values()) >= 5:
            break
    if not sigs:
        return None
    tmpl = G.clone(example[sigs.most_common(1)[0][0]])
    tmpl.pop("VarTable", None)  # instance-specific wiring (quests, spawn scripts) must not leak into new placements
    return tmpl


# ---------------------------------------------------------------------------
# journal / quests
# ---------------------------------------------------------------------------

def journal_index(project: TfnProject) -> list[dict]:
    out = []
    for cat in project.journal().get("Categories", {}).get("value", []):
        entries = (cat.get("EntryList") or {}).get("value", [])
        out.append({
            "tag": G.get(cat, "Tag", ""),
            "name": G.get_text(cat, "Name"),
            "priority": G.get(cat, "Priority", 0),
            "stages": [{"id": G.get(e, "ID"), "end": bool(G.get(e, "End", 0)), "text": G.get_text(e, "Text")}
                       for e in entries],
        })
    return out


def quest_wiring(project: TfnProject, areas: dict[str, dict], creatures: dict[str, dict],
                 items: dict[str, dict]) -> dict[str, list[dict]]:
    """{quest tag: [where it is wired]} from creature/item blueprints and placed instances."""
    wiring: dict[str, list[dict]] = {}

    def add(tag: str, entry: dict) -> None:
        wiring.setdefault(tag, []).append(entry)

    for res, c in creatures.items():
        for var, val in (c.get("quest_vars") or {}).items():
            m = QUEST_VALUE_RE.match(val) if isinstance(val, str) else None
            if m:
                add(m.group(2), {"type": "creature", "resref": res, "var": var, "stage": int(m.group(1))})
    for res, it in items.items():
        for var, val in (it.get("quest_vars") or {}).items():
            m = QUEST_VALUE_RE.match(val) if isinstance(val, str) else None
            if m:
                add(m.group(2), {"type": "item", "resref": res, "var": var, "stage": int(m.group(1))})
    for a in areas.values():
        for ref in a.get("quest_refs") or []:
            m = QUEST_VALUE_RE.match(ref["value"])
            if m:
                add(m.group(2), {"type": "placed", "area": a["resref"], "npc": ref["npc"], "var": ref["var"],
                                 "stage": int(m.group(1))})
    return wiring


def build_all(project: TfnProject, progress: Progress = None) -> dict:
    t0 = time.time()
    areas = area_index(project, progress)
    creatures = creature_index(project, progress)
    items = item_index(project, progress)
    utes = ute_index(project, progress)
    return {"areas": areas, "creatures": creatures, "items": items, "utes": utes,
            "seconds": round(time.time() - t0, 1)}
