"""High-level operations shared by the CLI and the web server."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import campevent as CE
from . import camps as CP
from . import changeset as CS
from . import convert_quests as CQ
from . import gffjson as G
from . import index as IX
from . import prefabs as PF
from . import quests as QS
from . import runtime as RT
from . import spawns as SP
from . import validate as VA
from .gamedata import GameData
from .walkmesh import Walkmesh
from .project import STUDIO_ROOT, ProjectError, TfnProject, check_new_resref

SPEC_ROOT = STUDIO_ROOT / "specs"
SPEC_KINDS = ("camps", "quests", "utes")
SPEC_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")


@dataclass
class StageResult:
    change: CS.ChangeSet
    issues: list[VA.Issue]
    report: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not VA.has_errors(self.issues)

    def to_dict(self) -> dict:
        d = self.change.summary()
        d["issues"] = [i.to_dict() for i in self.issues]
        d["ok"] = self.ok
        d["report"] = self.report
        return d


class Studio:
    """Holds the TFN project and (lazily, thread-safely) its cached indexes."""

    def __init__(self, tfn_root: str | Path | None = None, studio_dir: str | Path | None = None,
                 spec_root: Path | None = None, prefab_dir: Path | None = None):
        self.project = TfnProject(tfn_root, studio_dir)
        # plans/drafts of a module other than TFN live in that module (commit them with it)
        default_specs = SPEC_ROOT if self.project.profile == "tfn" else self.project.root / "studio-specs"
        self.spec_root = Path(spec_root) if spec_root else default_specs
        self.prefab_dir = Path(prefab_dir) if prefab_dir else PF.PREFAB_DIR
        self._lock = threading.RLock()
        self._areas: dict[str, dict] | None = None
        self._creatures: dict[str, dict] | None = None
        self._items: dict[str, dict] | None = None
        self._utes: dict[str, dict] | None = None
        self.index_state: dict[str, Any] = {"building": False, "progress": "", "seconds": None, "error": None}
        self.walkmesh = Walkmesh(GameData(self.project))

    # ------------------------------------------------------------- indexes
    def refresh(self, progress=None) -> None:
        with self._lock:
            self._areas = IX.area_index(self.project, progress)
            self._creatures = IX.creature_index(self.project, progress)
            self._items = IX.item_index(self.project, progress)
            self._utes = IX.ute_index(self.project, progress)

    def invalidate(self) -> None:
        with self._lock:
            self._areas = self._creatures = self._items = self._utes = None

    @property
    def areas(self) -> dict[str, dict]:
        with self._lock:
            if self._areas is None:
                self._areas = IX.area_index(self.project)
            return self._areas

    @property
    def creatures(self) -> dict[str, dict]:
        with self._lock:
            if self._creatures is None:
                self._creatures = IX.creature_index(self.project)
            return self._creatures

    @property
    def items(self) -> dict[str, dict]:
        with self._lock:
            if self._items is None:
                self._items = IX.item_index(self.project)
            return self._items

    @property
    def utes(self) -> dict[str, dict]:
        with self._lock:
            if self._utes is None:
                self._utes = IX.ute_index(self.project)
            return self._utes

    def refresh_background(self) -> None:
        """Rebuild indexes on a worker thread, publishing progress in `index_state`."""
        if self.index_state["building"]:
            return

        def work() -> None:
            t0 = time.time()
            self.index_state.update(building=True, error=None, progress="starting")
            try:
                self.refresh(lambda what, i, n: self.index_state.update(progress=f"{what} {i}/{n}"))
                self.index_state.update(seconds=round(time.time() - t0, 1), progress="done")
            except Exception as exc:  # surfaced in the UI
                self.index_state.update(error=str(exc))
            finally:
                self.index_state["building"] = False

        threading.Thread(target=work, daemon=True).start()

    def palette(self) -> list[dict]:
        return IX.placeable_palette(self.project, self.areas)

    def journal(self) -> list[dict]:
        return IX.journal_index(self.project)

    def quest_wiring(self) -> dict:
        return IX.quest_wiring(self.project, self.areas, self.creatures, self.items)

    # ------------------------------------------------------------- queries
    def status(self) -> dict:
        p = self.project
        dirty = p.git_status()
        return {
            "tfn_root": str(p.root), "branch": p.git_branch(), "head": p.git_head(),
            "walkmesh": self.walkmesh.available(),
            "dirty_files": len(dirty), "tools": {t: str(p.tool(t) or "") for t in ("nwn_gff", "nwnsc", "nasher")},
            "counts": {ext: len(p.list_resrefs(ext)) for ext in ("are", "utc", "utp", "ute", "uti", "dlg")},
            "index": self.index_state, "changes": CS.list_saved(p),
        }

    def area_detail(self, resref: str) -> dict:
        p = self.project
        are, git = p.read("are", resref), p.read("git", resref)
        out = IX.summarize_area(resref, are, git)
        out.pop("pl", None)
        out["vars"] = G.vars_of(git)
        out["tiles"] = [[G.get(t, "Tile_ID"), G.get(t, "Tile_Orientation"), G.get(t, "Tile_Height")]
                        for t in (are.get("Tile_List") or {}).get("value", [])]
        objs = []
        for kind, name in (("creature", "Creature List"), ("placeable", "Placeable List"), ("waypoint", "WaypointList"),
                           ("door", "Door List"), ("trigger", "TriggerList"), ("sound", "SoundList"),
                           ("store", "StoreList"), ("encounter", "Encounter List")):
            from . import instances as I
            for inst in I.instances(git, kind):
                x, y, z = I.position_of(kind, inst)
                obj = {"kind": kind, "resref": G.get(inst, "TemplateResRef", ""), "x": round(x, 2),
                       "y": round(y, 2), "z": round(z, 2), "tag": G.get(inst, "Tag", ""),
                       "plan": G.get_var(inst, "studio_plan", "")}
                if kind == "waypoint":
                    obj["facing"] = CE.facing_of(inst)
                objs.append(obj)
        out["objects"] = objs
        return out

    def walk_grid(self, resref: str) -> dict:
        """1 m walkability raster of an area for the map overlay ('0' no, '1' yes, '2' unknown), bottom row first."""
        if not self.walkmesh.available():
            return {"available": False}
        grid = self.walkmesh.grid(self.project.read("are", resref))
        return {"available": True, "width": grid.width, "height": grid.height, "rows": grid.to_rows(),
                "walkable_fraction": round(grid.walkable_fraction(), 3)}

    # --------------------------------------------------------------- specs
    def _spec_path(self, kind: str, spec_id: str) -> Path:
        if kind not in SPEC_KINDS or not SPEC_ID_RE.match(spec_id):
            raise ProjectError("invalid spec kind/id")
        return self.spec_root / kind / f"{spec_id}.json"

    def save_spec(self, kind: str, spec: dict) -> str:
        key = spec.get("tag") if kind == "quests" else spec.get("id") or spec.get("resref")
        if not key or not SPEC_ID_RE.match(str(key)):
            raise ProjectError("spec needs a valid id (a-z, 0-9, _)")
        path = self._spec_path(kind, str(key))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return str(key)

    def load_spec(self, kind: str, spec_id: str) -> dict:
        path = self._spec_path(kind, spec_id)
        if not path.is_file():
            raise ProjectError(f"no saved {kind} spec {spec_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_specs(self, kind: str) -> list[dict]:
        d = self.spec_root / kind
        out = []
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                out.append({"id": p.stem, "title": data.get("title") or data.get("name") or p.stem,
                            "area": data.get("area", ""), "mtime": p.stat().st_mtime})
        return out

    def delete_spec(self, kind: str, spec_id: str) -> bool:
        path = self._spec_path(kind, spec_id)
        if path.is_file():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------ staging
    def _finish(self, cs: CS.ChangeSet, report: dict, persist: bool, validate: bool,
                roundtrip: bool = True) -> StageResult:
        issues = VA.validate_changeset(self.project, cs, roundtrip=roundtrip) if validate else []
        if persist:
            cs.persist()
        return StageResult(cs, issues, report)

    def _require_tfn_engine(self, what: str) -> None:
        if self.project.profile == "generic":
            raise ProjectError(f"{what} needs The Frozen North's area_init/spawn engine, which this module does not have. "
                               "Plain camps (props and fixed creatures) and quests work in any module")

    def stage_camp(self, plan: dict, *, persist: bool = True, validate: bool = True) -> StageResult:
        if plan.get("groups") or plan.get("camp_event") or plan.get("events") or any(
                (o or {}).get("kind") == "marker" for o in plan.get("objects") or []):
            self._require_tfn_engine("Spawn groups, markers and random camps")
        cs = CP.CampBuilder(self.project, self.areas, self.walkmesh).build(plan)
        report = {"summary": CP.summarize_plan(plan)}
        return self._finish(cs, report, persist, validate)

    def camp_event_info(self, plan: dict) -> dict:
        """Dry run of a plan's random camp (per-spot variants, issues, probability, wiring); nothing is staged."""
        return CP.CampBuilder(self.project, self.areas, self.walkmesh).event_info(plan)

    def suggest_camp_spots(self, plan: dict, count: int = 6, seed: str = "") -> dict:
        return CP.CampBuilder(self.project, self.areas, self.walkmesh).suggest_spots(plan, count, seed)

    def stage_quest(self, spec: dict, *, persist: bool = True, validate: bool = True) -> StageResult:
        cs, report = QS.QuestBuilder(self.project, self.walkmesh).build(spec)
        return self._finish(cs, report, persist, validate)

    def convert_quests_check(self, only: list[str] | None = None) -> dict:
        """Dry run of the older-quest -> parameters conversion; nothing is staged or written."""
        return CQ.convert_project(self.project, None, only)

    def stage_convert_quests(self, only: list[str] | None = None, *, persist: bool = True,
                             validate: bool = True) -> StageResult:
        cs = CS.ChangeSet(self.project, "Convert older quest dialogs to parameters", "misc")
        report = CQ.convert_project(self.project, cs, only)
        return self._finish(cs, report, persist and bool(cs.changed_files()), validate and bool(cs.changed_files()))

    def runtime_status(self) -> dict:
        return {"profile": self.project.profile, "layout": self.project.layout, **RT.status(self.project)}

    def stage_runtime(self, *, persist: bool = True, validate: bool = True) -> StageResult:
        """Stage the studio's quest runtime into a generic module (nothing to do for The Frozen North)."""
        if self.project.profile != "generic":
            raise ProjectError("this module ships its own quest scripts (The Frozen North profile); nothing to install")
        cs = CS.ChangeSet(self.project, "Install the studio quest runtime", "misc")
        notes = RT.ensure(self.project, cs)
        cs.notes.append("Installed: " + (", ".join(notes) if notes else "nothing (already up to date)"))
        has_files = bool(cs.changed_files())
        return self._finish(cs, {"installed": notes}, persist and has_files, validate and has_files)

    def stage_ute(self, spec: dict, *, persist: bool = True, validate: bool = True) -> StageResult:
        self._require_tfn_engine("Encounter (spawn) blueprints")
        res = check_new_resref(spec.get("resref", ""), "encounter resref")
        cs = CS.ChangeSet(self.project, f"Encounter {res}", "ute", spec=f"specs/utes/{res}.json")
        existing = cs.load("ute", res) if cs.exists("ute", res) else None
        ute, warns = SP.build_ute(self.project, spec, existing)
        cs.save("ute", res, ute, note="encounter blueprint")
        cs.warnings.extend(warns)
        return self._finish(cs, {"describe": SP.describe_ute(ute)}, persist, validate)

    # ------------------------------------------------------------- changes
    def load_change(self, change_id: str) -> CS.ChangeSet:
        return CS.ChangeSet.load_saved(self.project, change_id)

    def validate_change(self, change_id: str, **kw) -> list[VA.Issue]:
        return VA.validate_changeset(self.project, self.load_change(change_id), **kw)

    def apply_change(self, change_id: str, *, allow_dirty: bool = False, force: bool = False) -> dict:
        cs = self.load_change(change_id)
        issues = VA.validate_changeset(self.project, cs)
        if VA.has_errors(issues) and not force:
            return {"ok": False, "problems": ["validation has errors; fix them or force"], "applied": [],
                    "issues": [i.to_dict() for i in issues]}
        res = CS.apply_changeset(self.project, cs, allow_dirty=allow_dirty, force_conflicts=force)
        if res.ok:
            self.invalidate()  # indexes are mtime-cached, so the next access is cheap
        return {"ok": res.ok, "problems": res.problems, "applied": res.applied,
                "issues": [i.to_dict() for i in issues]}

    def undo_change(self, change_id: str, *, force: bool = False) -> dict:
        res = CS.undo_applied(self.project, change_id, force=force)
        if res.ok:
            self.invalidate()
        return {"ok": res.ok, "problems": res.problems, "restored": res.applied}

    def discard_change(self, change_id: str) -> bool:
        return CS.discard(self.project, change_id)

    # --------------------------------------------------------------- prefabs
    def prefabs(self) -> dict[str, dict]:
        return PF.load_prefabs(self.prefab_dir)

    def save_prefab(self, data: dict) -> str:
        return PF.save_prefab(data, self.prefab_dir).name
