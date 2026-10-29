"""Camp plans -> change sets.

A camp plan is declarative and re-appliable:

  {"id": "wolf_den", "title": "...", "area": "<area resref>", "cr": 4,
   "objects": [{"kind": "placeable|creature|marker|waypoint", "resref": "...", "group": 1,
                "x": 12.0, "y": 8.0, "z": null, "facing": 90, "tag": ""}],
   "groups":  [{"n": 1, "ute": "wolf_forest", "spawns": 12, "script": ""}],
   "events":  [{"n": 1, "script": "spawn_something"}], "event_chance": 50,
   "new_utes": [{... see spawns.build_ute ...}],
   "camp_event": {"script": "eve_wolf_den", "weight": 1, "origin": {"x": 70, "y": 45, "facing": 90},
                  "spots": [{"x": 12, "y": 80, "facing": 0}], "include_origin": false,
                  "replaces_group": 2, "replace_radius": 0}}

Every generated GIT instance carries the local var `studio_plan` = plan id, so
re-generating the same plan replaces its previous output instead of duplicating it.

With a `camp_event` block the plan's placeables and creatures are not written to the GIT: they become the *template* of a
generated event script that builds the camp at one randomly chosen spot when the area refreshes (see campevent.py);
markers and waypoints stay ordinary GIT objects.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional

from . import campevent as CE
from . import gffjson as G
from . import index as IX
from . import instances as I
from . import spawns as S
from .changeset import ChangeSet
from .project import ProjectError, TfnProject, check_new_resref

PLAN_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")
KINDS = ("placeable", "creature", "marker", "waypoint")
MIN_SPACING = 0.5  # meters; closer than this to an existing object triggers a warning


class PlanError(ProjectError):
    pass


def validate_plan(plan: dict, require_template: bool = True) -> dict:
    """Normalise a plan, raising PlanError with a precise message when it is unusable."""
    if not isinstance(plan, dict):
        raise PlanError("plan must be an object")
    pid = str(plan.get("id", ""))
    if not PLAN_ID_RE.match(pid):
        raise PlanError("plan id must be 1-32 chars of a-z, 0-9, _")
    area = str(plan.get("area", ""))
    if not re.match(r"^[A-Za-z0-9_]{1,32}$", area):
        raise PlanError("plan needs an `area` resref")
    out: dict[str, Any] = {"id": pid, "title": str(plan.get("title") or pid), "area": area,
                           "cr": plan.get("cr"), "objects": [], "groups": [], "events": [],
                           "event_chance": plan.get("event_chance"), "new_utes": plan.get("new_utes") or [],
                           "camp_event": None}
    if out["cr"] is not None:
        out["cr"] = int(out["cr"])
        if not 1 <= out["cr"] <= 40:
            raise PlanError("cr must be 1-40")
    for i, o in enumerate(plan.get("objects") or []):
        kind = o.get("kind")
        if kind not in KINDS:
            raise PlanError(f"objects[{i}]: kind must be one of {KINDS}")
        for k in ("x", "y"):
            try:
                float(o[k])
            except (KeyError, TypeError, ValueError):
                raise PlanError(f"objects[{i}]: missing/invalid {k}")
        obj = {"kind": kind, "x": float(o["x"]), "y": float(o["y"]), "facing": float(o.get("facing") or 0),
               "z": None if o.get("z") in (None, "") else float(o["z"])}
        if kind == "marker":
            g = int(o.get("group", 0))
            if not 1 <= g <= 9:
                raise PlanError(f"objects[{i}]: marker needs group 1-9")
            obj["group"] = g
        else:
            res = str(o.get("resref", ""))
            if not re.match(r"^[A-Za-z0-9_]{1,32}$", res):
                raise PlanError(f"objects[{i}]: invalid resref {res!r}")
            obj["resref"] = res
        if o.get("tag"):
            obj["tag"] = str(o["tag"])[:32]
        out["objects"].append(obj)
    seen_groups = set()
    for i, g in enumerate(plan.get("groups") or []):
        n = int(g.get("n", 0))
        if not 1 <= n <= S.MAX_GROUPS or n in seen_groups:
            raise PlanError(f"groups[{i}]: n must be a unique number 1-9")
        seen_groups.add(n)
        ute = str(g.get("ute", ""))
        if not re.match(r"^[A-Za-z0-9_]{1,32}$", ute):
            raise PlanError(f"groups[{i}]: invalid ute resref")
        spawns = int(g.get("spawns", 0))
        if spawns < 1:
            raise PlanError(f"groups[{i}]: spawns must be >= 1")
        script = str(g.get("script") or "")
        out["groups"].append({"n": n, "ute": ute, "spawns": spawns, "script": script})
    for i, e in enumerate(plan.get("events") or []):
        n = int(e.get("n", 0))
        if not 1 <= n <= 9 or not e.get("script"):
            raise PlanError(f"events[{i}]: needs n 1-9 and a script")
        out["events"].append({"n": n, "script": str(e["script"])})
    try:
        out["camp_event"] = CE.parse_camp_event(plan.get("camp_event"), pid)
    except CE.CampEventError as exc:
        raise PlanError(str(exc)) from None
    if out["camp_event"]:
        template = [o for o in out["objects"] if o["kind"] in ("placeable", "creature")]
        if not template and require_template:
            raise PlanError("camp_event: the camp needs at least one placeable or creature (they are what appears)")
        for o in template:
            if o.get("tag") and not CE.TAG_RE.match(o["tag"]):
                raise PlanError(f"camp_event: tag {o['tag']!r} has characters a generated script cannot hold safely "
                                "(use letters, digits, spaces and plain punctuation)")
    return out


class CampBuilder:
    """Generates the change set for one plan (holds the lazily-built area index)."""

    def __init__(self, project: TfnProject, areas: dict[str, dict] | None = None, walk=None):
        self.p = project
        self._areas = areas
        self.walk = walk if (walk is not None and walk.available()) else None

    @property
    def areas(self) -> dict[str, dict]:
        if self._areas is None:
            self._areas = IX.area_index(self.p)
        return self._areas

    # ------------------------------------------------------------ templates
    def placeable_template(self, resref: str) -> tuple[dict, str]:
        if self.p.exists("utp", resref):
            return self.p.read("utp", resref), "src/utp"
        tmpl = IX.mine_placeable_template(self.p, self.areas, resref)
        if tmpl is not None:
            return tmpl, "mined from existing TFN instances"
        raise PlanError(f"unknown placeable {resref!r}: not in src/utp and never placed in any TFN area")

    def _blueprint(self, ext: str, resref: str) -> dict:
        if self.p.exists(ext, resref):
            return self.p.read(ext, resref)
        if ext == "utc":  # base-game creature that TFN already places somewhere: reuse a real instance
            tmpl = IX.mine_creature_template(self.p, self.areas, resref)
            if tmpl is not None:
                return tmpl
        raise PlanError(f"{ext} blueprint {resref!r} not found in TFN src/{ext}"
                        + (" and never placed in any TFN area" if ext == "utc" else
                           " (base-game blueprints are only supported for creatures/props TFN already places)"))

    # -------------------------------------------------------------- helpers
    @staticmethod
    def script_reader(cs: ChangeSet) -> Callable[[str], Optional[str]]:
        """name -> text of src/nss/<name>.nss as this change set sees it (staged wins over disk); None when absent or unreadable."""
        def read(name: str) -> Optional[str]:
            try:
                return cs.pending_text(cs.rel_nss(name))
            except (ProjectError, OSError, ValueError):
                return None
        return read

    def ground_fn(self, are: dict, git: dict) -> Callable[[float, float], CE.Ground]:
        """Ground height + walkability at a point: exact from the tile walkmesh, else guessed from the area's own objects."""
        walk = self.walk

        def ground(x: float, y: float) -> CE.Ground:
            probe = walk.probe(are, x, y) if walk is not None else None
            if probe is not None and probe.walkable and probe.z is not None:
                return CE.Ground(I.snap(probe.z), "walkmesh", True, probe.label)
            z, how = I.infer_z(git, x, y)
            if probe is None:
                return CE.Ground(z, how, None)
            return CE.Ground(z, how, False, probe.label or probe.error)
        return ground

    @staticmethod
    def _positions(git: dict) -> list[tuple[float, float]]:
        return [(x, y) for k in ("creature", "placeable", "waypoint", "door") for inst in I.instances(git, k)
                for (x, y, _z) in [I.position_of(k, inst)]]

    # ------------------------------------------------------------- generate
    def build(self, plan_in: dict, cs: ChangeSet | None = None) -> ChangeSet:
        plan = validate_plan(plan_in)
        pid, area = plan["id"], plan["area"]
        for res in (area,):
            if not self.p.exists("are", res) or not self.p.exists("git", res):
                raise PlanError(f"area {res!r} not found (need both src/are and src/git)")
        cs = cs or ChangeSet(self.p, plan["title"], "camp", spec=f"specs/camps/{pid}.json")
        are = self.p.read("are", area)
        git = cs.load("git", area)
        ce = plan["camp_event"]

        removed = I.remove_plan_instances(git, pid)
        if removed:
            cs.notes.append(f"replaced {removed} objects from the previous version of plan {pid!r}")

        existing_pts = [(k, I.position_of(k, inst)) for k in ("creature", "placeable", "waypoint", "door")
                        for inst in I.instances(git, k)]
        added = {"placeable": 0, "creature": 0, "marker": 0, "waypoint": 0}
        z_conf: dict[str, int] = {}
        tmpl_cache: dict[str, tuple[dict, str]] = {}
        if self.walk is not None:
            self.walk.prepare(are)
        off_ground: dict[str, int] = {}

        for i, o in enumerate(plan["objects"]):
            if ce and o["kind"] in ("placeable", "creature"):
                continue  # the camp template: built at runtime by the event script, never stored in the GIT
            x, y = o["x"], o["y"]
            if not I.in_bounds(are, x, y, margin=0.5):
                raise PlanError(f"objects[{i}] ({o['kind']}) at ({x:.1f}, {y:.1f}) is outside area "
                                f"{area} ({G.get(are, 'Width') * 10:g} x {G.get(are, 'Height') * 10:g} m)")
            probe = self.walk.probe(are, x, y) if self.walk is not None else None
            if o["z"] is None:
                if probe is not None and probe.walkable and probe.z is not None:
                    z, how = I.snap(probe.z), "walkmesh"
                else:
                    z, how = I.infer_z(git, x, y)
                z_conf[how] = z_conf.get(how, 0) + 1
            else:
                z = o["z"]
            if probe is not None and not probe.walkable:
                what = f"{o.get('resref') or 'random' + str(o.get('group'))}"
                why = probe.label or probe.error
                if o["kind"] in ("creature", "marker", "waypoint"):
                    cs.warnings.append(f"objects[{i}] {o['kind']} {what} at ({x:.1f},{y:.1f}) is on non-walkable ground "
                                       f"({why}): it may be stuck or unreachable")
                else:
                    off_ground[why] = off_ground.get(why, 0) + 1
            near = [k for k, (ex, ey, _ez) in existing_pts if math.hypot(ex - x, ey - y) < MIN_SPACING]
            if near:
                cs.warnings.append(f"objects[{i}] {o.get('resref') or 'marker'} at ({x:.1f},{y:.1f}) is within "
                                   f"{MIN_SPACING} m of an existing {near[0]}")
            tag = o.get("tag")
            if o["kind"] == "placeable":
                if o["resref"] not in tmpl_cache:
                    tmpl_cache[o["resref"]] = self.placeable_template(o["resref"])
                inst = I.placeable_instance(tmpl_cache[o["resref"]][0], x, y, z, o["facing"], plan=pid, tag=tag)
                I.add_instance(git, "placeable", inst)
                added["placeable"] += 1
            elif o["kind"] in ("creature", "marker"):
                res = o["resref"] if o["kind"] == "creature" else f"random{o['group']}"
                bp = self._blueprint("utc", res)
                inst = I.creature_instance(bp, x, y, z, o["facing"], plan=pid, tag=tag)
                I.add_instance(git, "creature", inst)
                added[o["kind"]] += 1
            else:  # waypoint
                bp = self._blueprint("utw", o["resref"])
                inst = I.waypoint_instance(bp, x, y, z, o["facing"], plan=pid, tag=tag)
                I.add_instance(git, "waypoint", inst)
                added["waypoint"] += 1
            existing_pts.append((o["kind"], (x, y, z)))

        self._set_area_vars(plan, git)

        # --- new encounter blueprints
        for spec in plan["new_utes"]:
            res = check_new_resref(spec.get("resref", ""), "encounter resref")
            existing = cs.load("ute", res) if cs.exists("ute", res) else None
            ute, warns = S.build_ute(self.p, spec, existing)
            cs.save("ute", res, ute, note="encounter blueprint")
            cs.warnings.extend(f"ute {res}: {w}" for w in warns)

        # --- random camp event (or undoing one this plan made earlier)
        read_script = self.script_reader(cs)
        if ce:
            self._stage_event(cs, plan, self._plan_event(plan, are, git, read_script))
        else:
            wiring = CE.apply_wiring(git, read_script, pid, None)
            cs.notes.extend(wiring.notes)
            if wiring.notes:
                cs.notes.append("The camp scripts stay in src/nss unused; delete them if you do not want them.")

        cs.save("git", area, git, note=f"camp plan {pid}")

        # --- notes for the human
        total = sum(added.values())
        if ce:
            cs.notes.append(f"{total} permanent object(s) in the area file: " + ", ".join(f"{v} {k}" for k, v in added.items() if v)
                            if total else "nothing permanent was added to the area file: the camp is built by its script")
        else:
            cs.notes.append(f"{total} objects: " + ", ".join(f"{v} {k}" for k, v in added.items() if v))
        if z_conf:
            how = ", ".join(f"{v}x {k}" for k, v in z_conf.items())
            if set(z_conf) == {"walkmesh"}:
                cs.notes.append(f"heights taken from the tile walkmesh ({how})")
            else:
                cs.notes.append(f"heights: {how}; 'walkmesh' is exact, the rest are guessed from neighbouring objects - "
                                "check them in the toolset (esp. hills/caves)")
        if off_ground:
            cs.notes.append("props on non-walkable surfaces (fine for rocks/trees/walls): "
                            + ", ".join(f"{v}x {k}" for k, v in off_ground.items()))
        cs.notes.append("No reseed needed for props/spawn groups (see SEED_SYSTEM.md section 12); "
                        "restart the server so area_init re-reads markers/variables.")
        return cs

    @staticmethod
    def _set_area_vars(plan: dict, git: dict) -> None:
        """The plan's area variables: cr, spawn groups, explicit events, event_chance."""
        if plan["cr"] is not None:
            G.set_var(git, "cr", plan["cr"])
        for g in plan["groups"]:
            n = g["n"]
            G.set_var(git, f"random{n}", g["ute"])
            G.set_var(git, f"random{n}_spawns", g["spawns"])
            if g["script"]:
                G.set_var(git, f"random{n}_spawn_script", g["script"])
            else:
                G.del_var(git, f"random{n}_spawn_script")
        for e in plan["events"]:
            G.set_var(git, f"event{e['n']}", e["script"])
        if plan["event_chance"] is not None:
            G.set_var(git, "event_chance", int(plan["event_chance"]))

    # ----------------------------------------------------------- camp event
    def _plan_event(self, plan: dict, are: dict, git: dict, read_script: Callable[[str], Optional[str]]) -> CE.EventPlan:
        """Work out the random camp: template, one variant per spot, the area wiring and both generated scripts.

        Mutates `git` (event variables, gate variable, and an `_wp_event` waypoint when the area has none); writes nothing else.
        """
        ce, pid, area = plan["camp_event"], plan["id"], plan["area"]
        src = [o for o in plan["objects"] if o["kind"] in ("placeable", "creature")]
        origin_is_default = ce["origin"] is None
        origin = ce["origin"] or CE.default_origin(src)
        if self.walk is not None:
            self.walk.prepare(are)
        ground = self.ground_fn(are, git)
        pivot = ground(origin["x"], origin["y"])
        template: list[dict] = []
        for o in src:
            quest_npc = False
            if o["kind"] == "placeable":
                self.placeable_template(o["resref"])           # raises when the blueprint is unknown
            else:
                quest_npc = bool(G.get_var(self._blueprint("utc", o["resref"]), "quest1"))
            g0 = ground(o["x"], o["y"])
            base = g0.z if g0.how == "walkmesh" else pivot.z   # what the explicit height is measured from
            template.append({"kind": o["kind"], "resref": o["resref"], "x": o["x"], "y": o["y"], "z": o["z"],
                             "dz": 0.0 if o["z"] is None else o["z"] - base, "facing": o["facing"],
                             "tag": o.get("tag", ""), "quest_npc": quest_npc})
        cands = CE.candidates(ce, origin)
        variants = CE.build_variants(template, origin, cands, ground, lambda x, y: I.in_bounds(are, x, y, margin=0.5),
                                     self._positions(git), MIN_SPACING)
        wanted = [(ce["script"], "event")] + ([(ce["gate"], "gate")] if ce["replaces_group"] else [])
        try:
            for name, kind in wanted:
                CE.check_script_free(read_script(name), kind, pid, name,
                                     elsewhere=(self.p.root / "nwn-base-scripts" / f"{name}.nss").is_file())
            added_wp = None
            if not CE.event_waypoints(git):      # events only run from a `_wp_event` waypoint
                bp = self._blueprint("utw", CE.EVENT_WP_RESREF)
                c0, v0 = cands[0], variants[0]
                I.add_instance(git, "waypoint", I.waypoint_instance(bp, c0["x"], c0["y"], v0.z, c0["facing"], plan=pid))
                added_wp = {"x": v0.x, "y": v0.y, "z": v0.z, "facing": v0.facing}
            wiring = CE.apply_wiring(git, read_script, pid, ce)
        except CE.CampEventError as exc:
            raise PlanError(str(exc)) from None
        tag = CE.camp_tag(pid)
        event_src = CE.event_script_source(pid, plan["title"], area, variants, tag=tag)
        gate_src = (CE.gate_script_source(pid, area, ce["replaces_group"], ce["replace_radius"], wiring.gate["chain"], tag=tag)
                    if wiring.gate else None)
        return CE.EventPlan(ce, origin, origin_is_default, CE.footprint_radius(src, origin), template, variants, wiring,
                            event_src, gate_src, added_wp)

    def _stage_event(self, cs: ChangeSet, plan: dict, ep: CE.EventPlan) -> None:
        """Save the generated scripts and report what the camp will do."""
        ce, w = ep.ce, ep.wiring
        errors = ep.errors
        if errors:
            more = f" (+{len(errors) - 4} more)" if len(errors) > 4 else ""
            raise PlanError("; ".join(errors[:4]) + more)
        for v in ep.variants:
            for level, msg in v.issues:
                (cs.warnings if level == "warning" else cs.notes).append(msg)
        cs.save_nss(ce["script"], ep.event_source, note=f"random camp event script ({len(ep.variants)} spot(s))")
        if ep.gate_source:
            cs.save_nss(ce["gate"], ep.gate_source, note=f"gate: replaces spawn group random{ce['replaces_group']}")
        n_obj = len(ep.template)
        pct = w.effective * 100
        spots = len(ep.variants)
        cs.notes.append(
            f"random camp {ce['script']!r}: {n_obj} object(s) at one of {spots} spot(s); it appears on about {pct:.1f}% of area "
            f"refreshes (event_chance {w.event_chance}%{', the TFN default because the area sets none' if w.chance_is_default else ''}"
            f" x {len(w.slots)} of {w.slots_total} event slot(s))" + (f", about {pct / spots:.1f}% per spot" if spots > 1 else ""))
        if ep.origin_is_default:
            cs.notes.append(f"the camp's pivot is the centre of its objects ({ep.origin['x']:.1f}, {ep.origin['y']:.1f}) facing "
                            f"{ep.origin['facing']:g}: spot directions rotate it relative to that")
        if w.other_events:
            cs.notes.append("the area's other events (" + ", ".join(w.other_events) + ") now share the event roll with the camp: "
                            "each of them happens a little less often than before")
        if ep.added_waypoint:
            a = ep.added_waypoint
            cs.notes.append(f"the area had no _wp_event waypoint (events cannot run without one): added one at ({a['x']:.1f}, {a['y']:.1f}); "
                            "any other event script would also use it as its location")
        if w.gate:
            g = w.gate
            what = "all of its creatures" if not g["radius"] else f"its creatures within {g['radius']:g} m of the camp"
            cs.notes.append(f"while the camp stands, spawn group random{g['group']} loses {what} (gate script {g['script']}"
                            + (f", chaining to {g['chain']!r}" if g["chain"] else "") + ")")
            if g["chain"] and not self._script_exists(cs, g["chain"]):
                cs.warnings.append(f"the group's spawn script {g['chain']!r} was not found in src/nss or the base scripts: "
                                   "the gate will still call it, which does nothing")
        guessed = sum(1 for v in ep.variants if v.z_how != "walkmesh")
        if guessed:
            cs.warnings.append(f"the ground height at {guessed} of {len(ep.variants)} spot(s) is a guess from neighbouring objects "
                               "(no walkmesh data there): check the camp's height in the game")
        cs.notes.extend(w.notes)
        cs.warnings.extend(w.warnings)

    def _script_exists(self, cs: ChangeSet, name: str) -> bool:
        return (self.script_reader(cs)(name) is not None) or (self.p.root / "nwn-base-scripts" / f"{name}.nss").is_file()

    # -------------------------------------------------------- live preview
    def _scratch(self, plan: dict) -> tuple[ChangeSet, dict, dict]:
        area = plan["area"]
        if not self.p.exists("are", area) or not self.p.exists("git", area):
            raise PlanError(f"area {area!r} not found (need both src/are and src/git)")
        cs = ChangeSet(self.p, plan["title"], "camp")          # scratch only: read through it, never persisted
        git = cs.load("git", area)
        I.remove_plan_instances(git, plan["id"])
        return cs, self.p.read("are", area), git

    def event_info(self, plan_in: dict) -> dict:
        """What the plan's random camp would do, without staging anything (drives the Camp Builder's live panel)."""
        plan = validate_plan(plan_in, require_template=False)
        ce = plan["camp_event"]
        if not ce:
            return {"enabled": False}
        cs, are, git = self._scratch(plan)
        template = [o for o in plan["objects"] if o["kind"] in ("placeable", "creature")]
        out: dict[str, Any] = {"waypoint_spots": CE.waypoint_spots(git, plan["id"]), "max_spots": CE.MAX_SPOTS}
        if not template:
            out.update({"enabled": True, "empty": True, "script": ce["script"], "variants": [], "errors": [],
                        "message": "Place at least one prop or creature on the map: they are the camp that appears."})
            return out
        self._set_area_vars(plan, git)  # what staging would set first: groups to replace, event_chance, explicit events
        for o in plan["objects"]:      # the plan's own event waypoints count towards the area's event spawn points
            if o["kind"] == "waypoint":
                bp = self._blueprint("utw", o["resref"])
                I.add_instance(git, "waypoint", I.waypoint_instance(bp, o["x"], o["y"], 0.0, o["facing"], plan=plan["id"]))
        ep = self._plan_event(plan, are, git, self.script_reader(cs))
        out.update(ep.to_dict())
        out["script_state"] = self._script_state(cs, ce)
        return out

    def _script_state(self, cs: ChangeSet, ce: dict) -> str:
        text = self.script_reader(cs)(ce["script"])
        return "new" if text is None else "regenerate"

    def suggest_spots(self, plan_in: dict, count: int = 6, seed: str = "") -> dict:
        """Well-spread walkable spots where the plan's camp fits (the walkmesh is required)."""
        plan = validate_plan(plan_in, require_template=False)
        if self.walk is None:
            raise PlanError("suggesting spots needs the tile walkmesh (the game data could not be read: run `tfn-studio doctor`)")
        cs, are, git = self._scratch(plan)
        ce = plan["camp_event"]
        template = [o for o in plan["objects"] if o["kind"] in ("placeable", "creature")]
        origin = (ce or {}).get("origin") or (CE.default_origin(template) if template else {"x": 0.0, "y": 0.0, "facing": CE.DEFAULT_FACING})
        w, h = I.area_extent(are)
        taken = [(s["x"], s["y"]) for s in (ce["spots"] if ce else [])]
        spots = CE.suggest_spots(self.walk.grid(are), w, h, template, origin, self._positions(git),
                                 max(1, min(int(count), CE.MAX_SPOTS)), seed or plan["id"], taken)
        return {"spots": spots, "footprint": round(CE.footprint_radius(template, origin), 2)}


def summarize_plan(plan: dict) -> dict:
    p = validate_plan(plan)
    counts: dict[str, int] = {}
    for o in p["objects"]:
        counts[o["kind"]] = counts.get(o["kind"], 0) + 1
    ce = p["camp_event"]
    return {"id": p["id"], "area": p["area"], "counts": counts, "groups": len(p["groups"]),
            "new_utes": len(p["new_utes"]),
            "camp_event": None if not ce else {"script": ce["script"], "spots": len(ce["spots"]) or 1, "weight": ce["weight"],
                                               "replaces_group": ce["replaces_group"]}}
