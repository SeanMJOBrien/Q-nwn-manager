"""The studio's own quest runtime, for modules that do not ship one (profile "generic").

A module such as The Frozen North already contains the scripts quests need (inc_quest, ai_ondeath, ...). Any other
module does not, so the studio can install a small, self-contained set from `runtime/generic/` as an ordinary change set
(reviewed, applied and undone like any other):

  inc_quest.nss, dlg_q_adv.nss, dlg_q_chk_eli.nss, dlg_q_chk_atp.nss, dlg_q_chk_at.nss   quest logic + dialog scripts
  enter_quest_adv.nss      area OnEnter script for "enter an area" stages
  qs_ondeath.nss           creature OnDeath script that credits kills
  qs_acquire.nss           module OnAcquireItem script for "pick up an item" stages (set in module.ifo when empty)
  qs_npc.utc.json, qs_questitem.uti.json   neutral blueprints to clone quest NPCs / quest items from

Our scripts carry the text "tfn-content-studio"; that is how we tell them from a module's own scripts of the same name
(we never overwrite those) and how a module with our inc_quest is told apart from The Frozen North.
"""

from __future__ import annotations

from pathlib import Path

from . import gffjson as G
from .changeset import ChangeSet
from .project import STUDIO_ROOT, TfnProject

MARK = "tfn-content-studio"
RUNTIME_DIR = STUDIO_ROOT / "runtime" / "generic"
ACQUIRE_SCRIPT = "qs_acquire"
DEATH_SCRIPT = "qs_ondeath"
NPC_TEMPLATE = "qs_npc"
ITEM_TEMPLATE = "qs_questitem"
SCRIPT_NAMES = ("inc_quest", "dlg_q_adv", "dlg_q_chk_eli", "dlg_q_chk_atp", "qs_ondeath", "qs_acquire")


def runtime_scripts() -> dict[str, str]:
    """{script name: source} of everything the runtime installs."""
    from .quests import GENERIC_AT, GENERIC_AT_SRC, GENERIC_ENTER, GENERIC_ENTER_SRC
    out = {n: (RUNTIME_DIR / f"{n}.nss").read_text(encoding="utf-8") for n in SCRIPT_NAMES}
    out[GENERIC_AT] = GENERIC_AT_SRC
    out[GENERIC_ENTER] = GENERIC_ENTER_SRC
    return out


def runtime_blueprints() -> dict[tuple[str, str], str]:
    return {("utc", NPC_TEMPLATE): (RUNTIME_DIR / f"{NPC_TEMPLATE}.utc.json").read_text(encoding="utf-8"),
            ("uti", ITEM_TEMPLATE): (RUNTIME_DIR / f"{ITEM_TEMPLATE}.uti.json").read_text(encoding="utf-8")}


def is_ours(project: TfnProject, name: str) -> bool:
    p = project.nss_path(name)
    return p.is_file() and MARK in p.read_text(encoding="utf-8", errors="replace")


def status(project: TfnProject) -> dict:
    """What is installed: {"installed": bool, "missing": [...], "foreign": [...] (module scripts with our names)}."""
    missing, foreign = [], []
    for name in runtime_scripts():
        if not project.script_exists(name):
            missing.append(name)
        elif not is_ours(project, name):
            foreign.append(name)
    for ext, res in runtime_blueprints():
        if not project.exists(ext, res):
            missing.append(f"{res}.{ext}")
    return {"installed": not missing and not foreign, "missing": missing, "foreign": foreign}


def ensure(project: TfnProject, cs: ChangeSet) -> list[str]:
    """Stage whatever part of the runtime is missing or out of date into `cs`. Returns notes about what it did.

    Raises ProjectError (via the caller) is not needed: a module script that already uses one of our names is never
    touched; it is reported in the change set's warnings and the quest generator then refuses to continue.
    """
    notes: list[str] = []
    for name, src in runtime_scripts().items():
        if cs.pending_text(cs.rel_nss(name)) is not None:
            continue
        if project.script_exists(name) and not is_ours(project, name):
            cs.warnings.append(f"script {name}.nss already exists in this module and is not the studio's: left alone. "
                               "Rename it, or write the quest scripts by hand")
            continue
        text = src if src.endswith("\n") else src + "\n"
        if not project.script_exists(name) or project.nss_path(name).read_text(encoding="utf-8") != text:
            cs.save_nss(name, src, note="studio quest runtime")
            notes.append(name)
    for (ext, res), text in runtime_blueprints().items():
        rel = cs.rel_json(ext, res)
        if cs.pending_text(rel) is None and not project.exists(ext, res):
            cs.stage_text(rel, text, note="studio template blueprint")
            notes.append(f"{res}.{ext}")
    _wire_module_acquire(project, cs, notes)
    return notes


def _wire_module_acquire(project: TfnProject, cs: ChangeSet, notes: list[str]) -> None:
    """Point module.ifo's OnAcquireItem at qs_acquire when it is empty; otherwise tell the user what to add."""
    if not project.exists("ifo", "module"):
        cs.notes.append(f"No module.ifo found: set the module's OnAcquireItem script to {ACQUIRE_SCRIPT} yourself "
                        "(needed only for 'pick up an item' stages)")
        return
    ifo = cs.load("ifo", "module")
    cur = G.get(ifo, "Mod_OnAcquirItem", "")
    if cur == ACQUIRE_SCRIPT:
        return
    if cur:
        cs.notes.append(f"module OnAcquireItem is {cur!r}: add `AdvanceQuest(oItem, oPC, 1)` for items tagged \"quest\" "
                        f"(see {ACQUIRE_SCRIPT}.nss) if you use 'pick up an item' stages")
        return
    ifo["Mod_OnAcquirItem"] = G.resref(ACQUIRE_SCRIPT)
    cs.save("ifo", "module", ifo, note=f"module OnAcquireItem -> {ACQUIRE_SCRIPT}")
    notes.append("module.ifo")
