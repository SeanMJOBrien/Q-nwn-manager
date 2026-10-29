"""Convert older quest dialogs from slot-numbered scripts to parameterized ones (a staged change set; never run for you).

Older TFN dialogs call one script per quest slot:   dlg_q_adv3       dlg_q_chk_eli2     dlg_q_chk_atc1
The same thing with a dialog parameter:             dlg_q_adv  target=3   dlg_q_chk_eli  target=2   dlg_q_chk_at  target=1

Only the dialog node/link fields `Script` (action) and `Active` (condition) and their `*Params` lists are touched.
Safety rules:
  * a node that already carries parameters is left alone and reported;
  * a dialog is converted only if its before/after "effective calls" (script family + slot, in order) are identical,
    and only if its file round-trips byte-for-byte through our writer (so nothing else in it can change);
  * the numbered scripts themselves are never deleted (other content may still use them);
  * a family is converted only if its numbered scripts really are the generic script with the slot filled in
    (`verify_scripts`); otherwise its nodes are left as they are and reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import dialogs as D
from . import gffjson as G
from .changeset import ChangeSet
from .project import TfnProject
from .quests import GENERIC_AT, GENERIC_AT_SRC

# numbered family -> parameterized script that replaces it
FAMILIES = {
    "dlg_q_adv": "dlg_q_adv",
    "dlg_q_chk_eli": "dlg_q_chk_eli",
    "dlg_q_chk_atp": "dlg_q_chk_atp",
    "dlg_q_chk_advb": "dlg_q_chk_advb",
    "dlg_q_chk_atc": GENERIC_AT,
}
NUMBERED_RE = re.compile(r"^(" + "|".join(sorted(FAMILIES, key=len, reverse=True)) + r")([1-9])$")

MENTIONS_RE = re.compile(r'"(?:' + "|".join(sorted(FAMILIES, key=len, reverse=True)) + r')[1-9]"')

# (field holding the script name, field holding its params) for nodes and links
NODE_FIELDS = ("Script", "ActionParams")
LINK_FIELDS = ("Active", "ConditionParams")


# ---------------------------------------------------------------- script check
def _norm_source(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"\s+", "", text)


def _no_aoe(s: str) -> str:
    """dlg_q_adv: with no `aoe` param (the only case we convert) the script always takes the plain AdvanceQuest branch."""
    return re.sub(r'if\(GetScriptParam\("aoe"\)=="1"\)\{[^}]*\}else\{([^}]*)\}', r"\1", s)


def _expected_numbered(base_src: str, slot: int) -> str:
    """What the numbered script must look like if it is the generic one with `target` fixed to `slot`."""
    s = _norm_source(base_src)
    s = s.replace('intnTarget=StringToInt(GetScriptParam("target"));', "")
    s = re.sub(r"if\(nTarget==0\)return(?:FALSE)?;", "", s)
    s = _no_aoe(s)
    s = s.replace('"quest"+IntToString(nTarget)+"_bluff_dc"', f'"quest{slot}_bluff_dc"')
    s = s.replace("nTarget", str(slot))
    return s


def verify_scripts(project: TfnProject) -> dict[str, dict[str, Any]]:
    """For every family: which numbered scripts are the generic one with the slot filled in?"""
    out: dict[str, dict[str, Any]] = {}
    for fam, target in FAMILIES.items():
        base_name = target if target != GENERIC_AT else None
        if base_name is None:
            base_src = GENERIC_AT_SRC
        elif project.script_exists(base_name):
            base_src = project.nss_path(base_name).read_text(encoding="utf-8", errors="replace")
        else:
            out[fam] = {"ok": False, "slots": [], "bad": [], "why": f"{base_name}.nss not found"}
            continue
        good, bad = [], []
        for slot in range(1, 10):
            name = f"{fam}{slot}"
            if not project.script_exists(name):
                continue
            src = project.nss_path(name).read_text(encoding="utf-8", errors="replace")
            (good if _no_aoe(_norm_source(src)) == _expected_numbered(base_src, slot) else bad).append(slot)
        out[fam] = {"ok": not bad and bool(good), "slots": good, "bad": bad, "why": ""}
    return out


# ------------------------------------------------------------------- dialogs
def _nodes(dlg: dict):
    """Yield (kind, holder, script_key, params_key) for every script-bearing node/link of a dialog."""
    for n in dlg["EntryList"]["value"] + dlg["ReplyList"]["value"]:
        yield "node", n, *NODE_FIELDS
        for k in ("RepliesList", "EntriesList"):
            for link in (n.get(k) or {}).get("value", []):
                yield "link", link, *LINK_FIELDS
    for s in dlg["StartingList"]["value"]:
        yield "link", s, *LINK_FIELDS


def effective_calls(dlg: dict) -> list[tuple[str, str, str]]:
    """Ordered (kind, script family, slot) of every quest call, whichever way it is written.

    A numbered call and its parameterized replacement give the same triple, so before == after proves
    that a rewrite changed the spelling only.
    """
    out = []
    for kind, holder, sk, pk in _nodes(dlg):
        name = G.get(holder, sk, "")
        m = NUMBERED_RE.match(name)
        if m:
            out.append((kind, FAMILIES[m.group(1)], m.group(2)))
            continue
        if name in set(FAMILIES.values()):
            params = {G.get(p, "Key"): G.get(p, "Value") for p in (holder.get(pk) or {}).get("value", [])}
            out.append((kind, name, params.get("target", "")))
    return out


@dataclass
class DialogResult:
    resref: str
    converted: int = 0
    skipped_params: list[str] = field(default_factory=list)
    skipped_family: list[str] = field(default_factory=list)
    refused: str = ""                       # why the whole dialog was left alone
    text: Optional[str] = None             # new file text when converted

    def to_dict(self) -> dict:
        return {"dialog": self.resref, "converted": self.converted, "skipped_with_params": self.skipped_params,
                "skipped_unverified_family": self.skipped_family, "refused": self.refused}


def convert_dialog(resref: str, text: str, ok_families: set[str]) -> DialogResult:
    res = DialogResult(resref)
    dlg = G.loads(text)
    if G.dumps(dlg) != text:
        res.refused = "file does not round-trip byte-for-byte through the studio writer; convert it by hand"
        return res
    before = effective_calls(dlg)
    for kind, holder, sk, pk in _nodes(dlg):
        name = G.get(holder, sk, "")
        m = NUMBERED_RE.match(name)
        if not m:
            continue
        if m.group(1) not in ok_families:
            res.skipped_family.append(name)
            continue
        if (holder.get(pk) or {}).get("value"):
            res.skipped_params.append(name)
            continue
        holder[sk] = G.resref(FAMILIES[m.group(1)])
        holder[pk] = D._params({"target": m.group(2)})
        res.converted += 1
    if not res.converted:
        return res
    if effective_calls(dlg) != before:      # cannot happen unless the rewrite above is wrong: fail closed
        res.refused = "internal check failed: effective quest calls changed"
        res.converted = 0
        return res
    res.text = G.dumps(dlg)
    return res


def convert_project(project: TfnProject, cs: Optional[ChangeSet] = None, only: Optional[list[str]] = None) -> dict:
    """Scan (and, when `cs` is given, stage) the conversion. Returns a report; writes nothing itself."""
    scripts = verify_scripts(project)
    ok_families = {f for f, v in scripts.items() if v["ok"]}
    results: list[DialogResult] = []
    wanted = set(only) if only else None
    for resref in project.list_resrefs("dlg"):
        if wanted is not None and resref not in wanted:
            continue
        text = project.json_path("dlg", resref).read_text(encoding="utf-8")
        if not MENTIONS_RE.search(text):
            continue
        res = convert_dialog(resref, text, ok_families)
        results.append(res)
        if cs is not None and res.text is not None:
            cs.stage_text(cs.rel_json("dlg", resref), res.text, note=f"{res.converted} numbered quest call(s) -> parameters")
    changed = [r for r in results if r.converted]
    if cs is not None and changed and "dlg_q_chk_atc" in ok_families:
        if not project.script_exists(GENERIC_AT) and cs.pending_text(cs.rel_nss(GENERIC_AT)) is None:
            cs.save_nss(GENERIC_AT, GENERIC_AT_SRC, note="generic 'currently at quest stage' check")
    if cs is not None:
        cs.notes.append("Numbered scripts (dlg_q_adv1..9, ...) are kept: nothing was deleted. "
                        "Restart the server after applying; no reseed is needed.")
    return {
        "scripts": scripts,
        "dialogs_changed": len(changed),
        "calls_converted": sum(r.converted for r in changed),
        "dialogs": [r.to_dict() for r in results],
    }
