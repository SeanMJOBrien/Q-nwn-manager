"""Validation of staged change sets (lint + nwn_gff round trip + nwnsc compile).

Levels: "error" blocks Apply in the UI; "warning" needs a human look; "info" is FYI.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

from . import gffjson as G
from . import instances as I
from .changeset import ChangeSet
from .project import NEW_RESREF_RE, TfnProject

QUEST_VAR_RE = re.compile(r"^quest(\d{1,2})$")
QUEST_VALUE_RE = re.compile(r"^(\d\d)_([qb]_[A-Za-z0-9_]{1,24})$")
QUEST_SCRIPT_TARGET = {"dlg_q_adv", "dlg_q_chk_eli", "dlg_q_chk_atp", "dlg_q_chk_advb"}
HIGHEST_QUEST_COUNT = 20


@dataclass
class Issue:
    level: str   # error | warning | info
    rel: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# semantic comparison for the nwn_gff round trip (floats are 32-bit in GFF)
# ---------------------------------------------------------------------------

def _f32(x: float) -> float:
    try:
        return struct.unpack("f", struct.pack("f", x))[0]
    except (OverflowError, struct.error):
        return x


def first_mismatch(a, b, path: str = "") -> str | None:
    if isinstance(a, dict) and isinstance(b, dict):
        if a.get("type") == "float" and b.get("type") == "float" and "value" in a and "value" in b:
            return None if _f32(a["value"]) == _f32(b["value"]) else f"{path}: {a['value']} != {b['value']}"
        for k in a.keys() | b.keys():
            if k not in a:
                return f"{path}/{k}: missing in source"
            if k not in b:
                return f"{path}/{k}: lost in round trip"
            m = first_mismatch(a[k], b[k], f"{path}/{k}")
            if m:
                return m
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: list length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            m = first_mismatch(x, y, f"{path}[{i}]")
            if m:
                return m
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def gff_roundtrip(project: TfnProject, text: str, timeout: int = 90) -> str | None:
    """None when JSON->GFF->JSON preserves the data; otherwise a problem description."""
    tool = project.tool("nwn_gff")
    if tool is None:
        return "SKIP: nwn_gff not found"
    with tempfile.TemporaryDirectory(prefix="tfnstudio-") as td:
        tdp = Path(td)
        (tdp / "in.json").write_text(text, encoding="utf-8")
        try:
            r1 = subprocess.run([str(tool), "-i", str(tdp / "in.json"), "-l", "json", "-o", str(tdp / "x.gff"),
                                 "-k", "gff"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            if r1.returncode != 0:
                return f"nwn_gff JSON->GFF failed: {(r1.stderr or r1.stdout).strip()[:300]}"
            r2 = subprocess.run([str(tool), "-i", str(tdp / "x.gff"), "-l", "gff", "-o", str(tdp / "back.json"),
                                 "-k", "json"], capture_output=True, text=True, timeout=timeout,
                                stdin=subprocess.DEVNULL)
            if r2.returncode != 0:
                return f"nwn_gff GFF->JSON failed: {(r2.stderr or r2.stdout).strip()[:300]}"
        except subprocess.TimeoutExpired:
            return "nwn_gff timed out"
        except OSError as exc:
            return f"SKIP: nwn_gff cannot run on this machine ({exc})"
        back = json.loads((tdp / "back.json").read_text(encoding="utf-8"))
    mm = first_mismatch(json.loads(text), back)
    return f"round trip altered data at {mm}" if mm else None


_ENTRY_RE = re.compile(r"\b(?:void\s+main|int\s+StartingConditional)\s*\(")


def compile_script(project: TfnProject, name: str, source: str, timeout: int = 30,
                   staged: "dict[str, str] | None" = None) -> list[str]:
    """Compile with nwnsc; returns error lines (empty = OK). nwnsc can hang on some syntax errors.

    `staged` = {script name: source} of scripts that are in the change set but not on disk yet, so includes between
    them resolve. A file with no main()/StartingConditional() is an include: it is compiled only as part of its users.
    """
    tool = project.tool("nwnsc")
    if tool is None:
        return ["SKIP: nwnsc not found"]
    if not _ENTRY_RE.search(source):
        return []
    with tempfile.TemporaryDirectory(prefix="tfnstudio-") as td:
        tdp = Path(td)
        (tdp / "out").mkdir()
        (tdp / "inc").mkdir()
        for sname, ssrc in (staged or {}).items():
            if sname != name:
                (tdp / "inc" / f"{sname}.nss").write_text(ssrc, encoding="utf-8")
        incs = ";".join([str(tdp / "inc")] + [str(d) for d in project.include_dirs()])
        (tdp / f"{name}.nss").write_text(source, encoding="utf-8")
        try:
            r = subprocess.run([str(tool), "-i", incs, "-b", "out", f"{name}.nss"], cwd=td, capture_output=True,
                               text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return ["compiler timed out (nwnsc hangs on some syntax errors) - check the script for typos"]
        except OSError as exc:
            return [f"SKIP: nwnsc cannot run on this machine ({exc})"]
        if r.returncode == 0 and (tdp / "out" / f"{name}.ncs").is_file():
            return []
        errs = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if "Error" in ln]
        return errs or [f"compile failed (exit {r.returncode})"]


# ---------------------------------------------------------------------------
# lints
# ---------------------------------------------------------------------------

class Validator:
    def __init__(self, project: TfnProject, cs: ChangeSet):
        self.p = project
        self.cs = cs
        self.issues: list[Issue] = []
        self._journal_tags: set[str] | None = None

    # ------------------------------------------------------------- helpers
    def add(self, level: str, rel: str, msg: str) -> None:
        self.issues.append(Issue(level, rel, msg))

    def script_known(self, name: str) -> bool:
        if not name:
            return True
        if self.cs.pending_text(self.cs.rel_nss(name)) is not None:
            return True
        return self.p.base_script_exists(name)

    def journal_tags(self) -> set[str]:
        if self._journal_tags is None:
            try:
                jrl = self.cs.load("jrl", "module")
                self._journal_tags = {G.get(c, "Tag", "") for c in jrl["Categories"]["value"]}
            except Exception:
                self._journal_tags = set()
        return self._journal_tags

    # ---------------------------------------------------------------- run
    def run(self, *, roundtrip: bool = True, compile_scripts: bool = True) -> list[Issue]:
        for fc in self.cs.changed_files():
            rel = fc.rel
            if rel.endswith(".json"):
                self.check_json(fc)
            elif rel.endswith(".nss"):
                if compile_scripts:
                    staged = {Path(f.rel).stem: f.new_text for f in self.cs.changed_files() if f.rel.endswith(".nss")}
                    for err in compile_script(self.p, Path(rel).stem, fc.new_text, staged=staged):
                        self.add("info" if err.startswith("SKIP") else "error", rel, err)
        return self.issues

    def check_json(self, fc) -> None:
        rel = fc.rel
        try:
            obj = G.loads(fc.new_text)
        except ValueError as exc:
            self.add("error", rel, f"invalid JSON: {exc}")
            return
        if G.dumps(obj) != fc.new_text:
            self.add("warning", rel, "not in canonical nwn_gff format (will cause noisy diffs)")
        ext, resref = self.p.parse_rel(rel)
        lint = getattr(self, f"lint_{ext}", None)
        if lint:
            before = len(self.issues)
            lint(rel, resref, obj, fc)
            self._downgrade_preexisting(ext, rel, resref, fc, before)
        if getattr(self, "_roundtrip", True):
            problem = gff_roundtrip(self.p, fc.new_text)
            if problem:
                self.add("info" if problem.startswith("SKIP") else "error", rel, problem)

    def _downgrade_preexisting(self, ext: str, rel: str, resref: str, fc, start: int) -> None:
        """Errors that the file already had before this change are legacy problems: show, don't block."""
        new = self.issues[start:]
        if not new or not fc.old_text:
            return
        try:
            old_obj = G.loads(fc.old_text)
        except ValueError:
            return
        probe = Validator(self.p, self.cs)
        try:
            getattr(probe, f"lint_{ext}")(rel, resref, old_obj, fc)
        except Exception:
            return
        old_msgs = {i.message for i in probe.issues if i.level == "error"}
        for issue in new:
            if issue.level == "error" and issue.message in old_msgs:
                issue.level = "warning"
                issue.message = "(pre-existing) " + issue.message

    # ----------------------------------------------------------- per type
    def lint_git(self, rel: str, resref: str, git: dict, fc) -> None:
        try:
            are = self.cs.load("are", resref)
        except Exception:
            are = None
            self.add("error", rel, f"no matching ARE for area {resref!r}")
        for kind, lname in I.KIND_LIST.items():
            for i, inst in enumerate(I.instances(git, kind)):
                if inst.get("__struct_id") != I.STRUCT_ID[kind]:
                    self.add("error", rel, f"{lname}[{i}]: __struct_id should be {I.STRUCT_ID[kind]}")
                plan = G.get_var(inst, I.PLAN_VAR)
                if not plan:
                    continue  # only deep-check what the studio generated
                x, y, _z = I.position_of(kind, inst)
                if are is not None and not I.in_bounds(are, x, y):
                    self.add("error", rel, f"{kind} {G.get(inst, 'TemplateResRef')} at ({x:.1f},{y:.1f}) "
                                           "is outside the area bounds")
                res = G.get(inst, "TemplateResRef", "")
                if kind == "creature" and not self.cs.exists("utc", res):
                    self.add("warning", rel, f"creature blueprint {res!r} not found in src/utc "
                                             "(base-game creature?)")
        gv = G.vars_of(git)
        groups = [n for n in range(1, 10) if gv.get(f"random{n}")]
        markers = {n: 0 for n in groups}
        for inst in I.instances(git, "creature"):
            mm = re.match(r"^random([1-9])$", G.get(inst, "TemplateResRef", ""))
            if mm and int(mm.group(1)) in markers:
                markers[int(mm.group(1))] += 1
        if groups and not isinstance(gv.get("cr"), int):
            self.add("error", rel, "area has spawn groups but no int `cr` variable (loot/XP/treasure maps need it)")
        elif isinstance(gv.get("cr"), int) and not 1 <= gv["cr"] <= 40:
            self.add("warning", rel, f"area `cr` = {gv['cr']} looks out of range (1-40)")
        for n in groups:
            ute = gv[f"random{n}"]
            if not self.cs.exists("ute", ute):
                self.add("error", rel, f"random{n} = {ute!r}: no such encounter blueprint (src/ute)")
            sp = gv.get(f"random{n}_spawns")
            if not isinstance(sp, int) or sp <= 0:
                self.add("error", rel, f"random{n}_spawns must be a positive int (defaults to 0 = nothing spawns)")
            if markers[n] == 0:
                self.add("error", rel, f"random{n} has no `random{n}` marker creatures placed: group will not spawn")
            script = gv.get(f"random{n}_spawn_script")
            if script and not self.script_known(script):
                self.add("error", rel, f"random{n}_spawn_script {script!r} does not exist")
        for n in range(1, 10):
            ev = gv.get(f"event{n}")
            if ev and not self.script_known(ev):
                self.add("error", rel, f"event{n} script {ev!r} does not exist")
        first_gap = next((n for n in range(1, 10) if not gv.get(f"event{n}")), 10)
        for n in range(first_gap + 1, 10):
            if gv.get(f"event{n}"):
                self.add("warning", rel, f"event{n} = {gv[f'event{n}']!r} follows an empty slot (event{first_gap}): area_init counts "
                                         "events only up to the first empty slot, so it never runs")
        if first_gap > 1 and not any(G.get(w, "TemplateResRef", "") == "_wp_event" for w in I.instances(git, "waypoint")):
            self.add("warning", rel, "event scripts are set but the area has no `_wp_event` waypoint: area_refresh runs events "
                                     "from one, so none of them ever fires")
        for hook in I_HOOKS:
            if gv.get(hook) and not self.script_known(gv[hook]):
                self.add("error", rel, f"{hook} script {gv[hook]!r} does not exist")

    def lint_ute(self, rel: str, resref: str, ute: dict, fc) -> None:
        if G.get(ute, "TemplateResRef") != resref:
            self.add("error", rel, "TemplateResRef does not match file name")
        if len(G.get(ute, "Tag", "")) > 32:
            self.add("error", rel, "Tag longer than 32 chars")
        creatures = (ute.get("CreatureList") or {}).get("value", [])
        if not creatures:
            self.add("error", rel, "encounter has no creatures")
        if creatures and all(G.get(c, "SingleSpawn", 0) for c in creatures):
            self.add("error", rel, "every creature is 'Single Spawn' (unique) - the common pool is empty")
        for c in creatures:
            r = G.get(c, "ResRef", "")
            if not self.cs.exists("utc", r):
                self.add("warning", rel, f"creature {r!r} not found in src/utc (base-game creature?)")
        if G.get(ute, "DifficultyIndex", 0) not in range(0, 5):
            self.add("error", rel, "DifficultyIndex must be 0-4")
        rare = G.get_var(ute, "rare")
        if rare and not self.cs.exists("utc", rare):
            self.add("warning", rel, f"rare creature {rare!r} not found in src/utc")

    def _lint_quest_vars(self, rel: str, owner: dict, what: str) -> None:
        vars_ = G.vars_of(owner)
        slots = set()
        for name, val in vars_.items():
            m = QUEST_VAR_RE.match(name)
            if not m:
                continue
            slots.add(int(m.group(1)))
            if not isinstance(val, str) or not QUEST_VALUE_RE.match(val):
                self.add("error", rel, f"{what}: {name} = {val!r} is not '<NN>_<q_|b_tag>' (e.g. 02_q_wolves)")
                continue
            tag = QUEST_VALUE_RE.match(val).group(2)
            if tag not in self.journal_tags():
                self.add("error", rel, f"{what}: {name} refers to quest {tag!r} which is not in the journal")
            if int(m.group(1)) >= HIGHEST_QUEST_COUNT:
                self.add("error", rel, f"{what}: quest slot {name} is >= {HIGHEST_QUEST_COUNT} and is never checked")
        kill = vars_.get("quest_kill")
        if kill is not None and f"quest{kill}" not in vars_:
            self.add("error", rel, f"{what}: quest_kill = {kill} but there is no quest{kill} variable")

    def lint_utc(self, rel: str, resref: str, utc: dict, fc) -> None:
        if G.get(utc, "TemplateResRef") != resref:
            self.add("error", rel, "TemplateResRef does not match file name")
        if len(G.get(utc, "Tag", "")) > 32:
            self.add("error", rel, "Tag longer than 32 chars")
        conv = G.get(utc, "Conversation", "")
        if conv and not self.cs.exists("dlg", conv):
            self.add("error", rel, f"Conversation {conv!r} does not exist in src/dlg")
        self._lint_quest_vars(rel, utc, f"creature {resref}")

    def lint_uti(self, rel: str, resref: str, uti: dict, fc) -> None:
        if G.get(uti, "TemplateResRef") != resref:
            self.add("error", rel, "TemplateResRef does not match file name")
        vars_ = G.vars_of(uti)
        if any(QUEST_VAR_RE.match(k) for k in vars_):
            if G.get(uti, "Tag") != "quest":
                self.add("error", rel, "quest item must have Tag 'quest' (on_item_acq only advances items with that tag)")
            self._lint_quest_vars(rel, uti, f"item {resref}")

    def lint_jrl(self, rel: str, resref: str, jrl: dict, fc) -> None:
        old = {}
        if fc.old_text:
            try:
                old = {G.get(c, "Tag"): c for c in G.loads(fc.old_text)["Categories"]["value"]}
            except Exception:
                old = {}
        seen = set()
        for cat in jrl["Categories"]["value"]:
            tag = G.get(cat, "Tag", "")
            if tag in seen:
                self.add("error", rel, f"duplicate journal tag {tag!r}")
            seen.add(tag)
            if old.get(tag) == cat:
                continue  # unchanged: don't lint legacy content
            if tag[:2] in ("q_", "b_") and len(tag) > 27:
                self.add("error", rel, f"journal tag {tag!r} is longer than 27 chars (inc_quest truncates it)")
            if tag[:2] not in ("q_", "b_"):
                self.add("warning", rel, f"journal tag {tag!r} does not start with q_ or b_ (not auto-registered)")
            entries = (cat.get("EntryList") or {}).get("value", [])
            ids = [G.get(e, "ID") for e in entries]
            if not entries:
                self.add("error", rel, f"{tag}: no journal entries")
            if len(set(ids)) != len(ids):
                self.add("error", rel, f"{tag}: duplicate entry IDs {ids}")
            if ids != sorted(ids):
                self.add("warning", rel, f"{tag}: entry IDs not ascending {ids}")
            if any(not (1 <= i <= 99) for i in ids if isinstance(i, int)):
                self.add("error", rel, f"{tag}: entry IDs must be 1-99 (two-digit stage numbers)")
            if entries and not G.get(entries[-1], "End", 0):
                self.add("warning", rel, f"{tag}: last entry is not marked End (quest never shows as completed)")
            for e in entries:
                if not G.get_text(e, "Text").strip():
                    self.add("error", rel, f"{tag}: entry {G.get(e, 'ID')} has empty text")

    def lint_dlg(self, rel: str, resref: str, dlg: dict, fc) -> None:
        entries = (dlg.get("EntryList") or {}).get("value", [])
        replies = (dlg.get("ReplyList") or {}).get("value", [])
        starts = (dlg.get("StartingList") or {}).get("value", [])
        if not starts:
            self.add("error", rel, "dialog has no starting entries")
        reach_e: set[int] = set()
        reach_r: set[int] = set()

        def check_script(name: str, where: str, params: list) -> None:
            if name and not self.script_known(name):
                self.add("error", rel, f"{where}: script {name!r} does not exist")
            keys = {G.get(p, "Key"): G.get(p, "Value") for p in params}
            if name in QUEST_SCRIPT_TARGET:
                t = keys.get("target", "")
                if not str(t).isdigit() or not 1 <= int(t) < HIGHEST_QUEST_COUNT:
                    self.add("error", rel, f"{where}: {name} needs param target=1..{HIGHEST_QUEST_COUNT - 1}")
            if name == "dlg_q_chk_multi" and not ({"quest", "stages"} <= set(keys)):
                self.add("error", rel, f"{where}: dlg_q_chk_multi needs params 'quest' and 'stages'")

        for i, s in enumerate(starts):
            idx = G.get(s, "Index")
            if not isinstance(idx, int) or not 0 <= idx < len(entries):
                self.add("error", rel, f"StartingList[{i}] points at missing entry {idx}")
                continue
            reach_e.add(idx)
            check_script(G.get(s, "Active", ""), f"StartingList[{i}]", (s.get("ConditionParams") or {}).get("value", []))
        for i, e in enumerate(entries):
            check_script(G.get(e, "Script", ""), f"Entry[{i}]", (e.get("ActionParams") or {}).get("value", []))
            for l in (e.get("RepliesList") or {}).get("value", []):
                idx = G.get(l, "Index")
                if not isinstance(idx, int) or not 0 <= idx < len(replies):
                    self.add("error", rel, f"Entry[{i}] links to missing reply {idx}")
                else:
                    reach_r.add(idx)
                check_script(G.get(l, "Active", ""), f"Entry[{i}] link", (l.get("ConditionParams") or {}).get("value", []))
            if not G.get_text(e, "Text").strip():
                self.add("warning", rel, f"Entry[{i}] has empty text")
        for i, r in enumerate(replies):
            check_script(G.get(r, "Script", ""), f"Reply[{i}]", (r.get("ActionParams") or {}).get("value", []))
            for l in (r.get("EntriesList") or {}).get("value", []):
                idx = G.get(l, "Index")
                if not isinstance(idx, int) or not 0 <= idx < len(entries):
                    self.add("error", rel, f"Reply[{i}] links to missing entry {idx}")
                else:
                    reach_e.add(idx)
                check_script(G.get(l, "Active", ""), f"Reply[{i}] link", (l.get("ConditionParams") or {}).get("value", []))
        # reachability: flood fill from starting entries
        seen_e, seen_r = set(), set()
        stack = [("e", s) for s in {G.get(x, "Index") for x in starts if isinstance(G.get(x, "Index"), int)}]
        while stack:
            kind, idx = stack.pop()
            if kind == "e" and idx not in seen_e and 0 <= idx < len(entries):
                seen_e.add(idx)
                for l in (entries[idx].get("RepliesList") or {}).get("value", []):
                    stack.append(("r", G.get(l, "Index")))
            elif kind == "r" and idx not in seen_r and isinstance(idx, int) and 0 <= idx < len(replies):
                seen_r.add(idx)
                for l in (replies[idx].get("EntriesList") or {}).get("value", []):
                    stack.append(("e", G.get(l, "Index")))
        if len(seen_e) < len(entries) or len(seen_r) < len(replies):
            self.add("warning", rel, f"{len(entries) - len(seen_e)} entries / {len(replies) - len(seen_r)} replies "
                                     "are unreachable from the starting list")


I_HOOKS = ("init_script", "enter_script", "exit_script", "refresh_script")


def validate_changeset(project: TfnProject, cs: ChangeSet, *, roundtrip: bool = True,
                       compile_scripts: bool = True) -> list[Issue]:
    v = Validator(project, cs)
    v._roundtrip = roundtrip  # type: ignore[attr-defined]
    issues = v.run(roundtrip=roundtrip, compile_scripts=compile_scripts)
    for w in cs.warnings:
        issues.append(Issue("warning", "", w))
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order.get(i.level, 3), i.rel))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
