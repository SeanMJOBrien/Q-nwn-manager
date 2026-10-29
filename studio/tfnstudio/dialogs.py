"""Build and edit NWN dialogs (.dlg JSON) the way TFN's toolset output looks.

Verified against all 417 TFN dialogs: Entry/Reply `__struct_id` == list index, link
`__struct_id` == position in its link list, keys sorted case-insensitively, params are
`{Key, Value}` cexostring structs, header usually `nw_walk_wp`.

Generated nodes can be tagged through their `Comment` (e.g. "studio:q_wolves:offer") so a
later run can remove and regenerate exactly its own nodes inside a hand-written dialog.
"""

from __future__ import annotations

import re
from typing import Iterable

from . import gffjson as G

NO_DELAY = 4294967295
LEAVE = "<StartAction>[Leave.]</Start>"
Params = "dict[str, str] | list[tuple[str, str]] | None"


def action_text(text: str) -> str:
    """Wrap text the way TFN marks descriptive/action lines."""
    t = text.strip()
    return t if t.startswith("<StartAction>") else f"<StartAction>[{t}]</Start>"


def _params(params) -> dict:
    items = list(params.items()) if isinstance(params, dict) else list(params or [])
    return G.list_([G.struct(i, Key=G.cexostring(k), Value=G.cexostring(str(v))) for i, (k, v) in enumerate(items)])


def _sorted(d: dict) -> dict:
    out = {}
    if "__data_type" in d:
        out["__data_type"] = d["__data_type"]
    if "__struct_id" in d:
        out["__struct_id"] = d["__struct_id"]
    for k in sorted((k for k in d if k not in ("__data_type", "__struct_id")), key=str.lower):
        out[k] = d[k]
    return out


def new_dialog(end_script: str = "nw_walk_wp") -> dict:
    return _sorted({
        "__data_type": "DLG ",
        "DelayEntry": G.dword(0), "DelayReply": G.dword(0),
        "EndConverAbort": G.resref(end_script), "EndConversation": G.resref(end_script),
        "EntryList": G.list_(), "NumWords": G.dword(0), "PreventZoomIn": G.byte(0),
        "ReplyList": G.list_(), "StartingList": G.list_(),
    })


class DialogBuilder:
    def __init__(self, dlg: dict | None = None):
        self.d = dlg if dlg is not None else new_dialog()
        self.dirty = dlg is None

    # ----------------------------------------------------------------- views
    @property
    def entries(self) -> list[dict]:
        return self.d["EntryList"]["value"]

    @property
    def replies(self) -> list[dict]:
        return self.d["ReplyList"]["value"]

    @property
    def starts(self) -> list[dict]:
        return self.d["StartingList"]["value"]

    # ----------------------------------------------------------------- nodes
    def _node(self, kind: str, text: str, script: str, params, comment: str, speaker: str) -> dict:
        node = {
            "__struct_id": len(self.entries if kind == "entry" else self.replies),
            "ActionParams": _params(params),
            "Animation": G.dword(0), "AnimLoop": G.byte(1),
            "Comment": G.cexostring(comment), "Delay": G.dword(NO_DELAY),
            "Quest": G.cexostring(""),
            "RepliesList" if kind == "entry" else "EntriesList": G.list_(),
            "Script": G.resref(script), "Sound": G.resref(""), "Text": G.locstring(text),
        }
        if kind == "entry":
            node["Speaker"] = G.cexostring(speaker)
        return _sorted(node)

    def add_entry(self, text: str, *, script: str = "", params=None, comment: str = "", speaker: str = "") -> int:
        self.entries.append(self._node("entry", text, script, params, comment, speaker))
        self.dirty = True
        return len(self.entries) - 1

    def add_reply(self, text: str, *, script: str = "", params=None, comment: str = "") -> int:
        self.replies.append(self._node("reply", text, script, params, comment, ""))
        self.dirty = True
        return len(self.replies) - 1

    @staticmethod
    def _link(pos: int, index: int, active: str, params, comment: str) -> dict:
        return _sorted({
            "__struct_id": pos, "Active": G.resref(active), "ConditionParams": _params(params),
            "Index": G.dword(index), "IsChild": G.byte(0), "LinkComment": G.cexostring(comment),
        })

    def entry_to_reply(self, entry: int, reply: int, *, active: str = "", params=None, comment: str = "") -> None:
        lst = self.entries[entry]["RepliesList"]["value"]
        lst.append(self._link(len(lst), reply, active, params, comment))
        self.dirty = True

    def reply_to_entry(self, reply: int, entry: int, *, active: str = "", params=None, comment: str = "") -> None:
        lst = self.replies[reply]["EntriesList"]["value"]
        lst.append(self._link(len(lst), entry, active, params, comment))
        self.dirty = True

    def add_start(self, entry: int, *, active: str = "", params=None, front: bool = True) -> None:
        item = _sorted({"__struct_id": 0, "Active": G.resref(active), "ConditionParams": _params(params),
                        "Index": G.dword(entry)})
        if front:
            self.starts.insert(0, item)
        else:
            self.starts.append(item)
        for i, s in enumerate(self.starts):
            s["__struct_id"] = i
        self.dirty = True

    # --------------------------------------------------------------- removal
    def remove_generated(self, comment_prefix: str) -> int:
        """Delete every entry/reply whose Comment starts with `comment_prefix`; fix all indices/links."""
        rm_e = {i for i, n in enumerate(self.entries) if G.get(n, "Comment", "").startswith(comment_prefix)}
        rm_r = {i for i, n in enumerate(self.replies) if G.get(n, "Comment", "").startswith(comment_prefix)}
        if not rm_e and not rm_r:
            return 0
        map_e, map_r = {}, {}
        for i in range(len(self.entries)):
            if i not in rm_e:
                map_e[i] = len(map_e)
        for i in range(len(self.replies)):
            if i not in rm_r:
                map_r[i] = len(map_r)

        def fix_links(links: list[dict], mapping: dict[int, int]) -> list[dict]:
            kept = [l for l in links if G.get(l, "Index") in mapping]
            for pos, l in enumerate(kept):
                l["Index"]["value"] = mapping[l["Index"]["value"]]
                l["__struct_id"] = pos
            return kept

        new_entries, new_replies = [], []
        for i, n in enumerate(self.entries):
            if i in rm_e:
                continue
            n["RepliesList"]["value"] = fix_links(n["RepliesList"]["value"], map_r)
            n["__struct_id"] = map_e[i]
            new_entries.append(n)
        for i, n in enumerate(self.replies):
            if i in rm_r:
                continue
            n["EntriesList"]["value"] = fix_links(n["EntriesList"]["value"], map_e)
            n["__struct_id"] = map_r[i]
            new_replies.append(n)
        self.d["EntryList"]["value"] = new_entries
        self.d["ReplyList"]["value"] = new_replies
        self.d["StartingList"]["value"] = fix_links(self.starts, map_e)
        self.dirty = True
        return len(rm_e) + len(rm_r)

    # ---------------------------------------------------------------- finish
    def word_count(self) -> int:
        return sum(len(re.findall(r"\S+", G.get_text(n, "Text"))) for n in self.entries + self.replies)

    def finish(self) -> dict:
        if self.dirty:
            self.d["NumWords"] = G.dword(self.word_count())
        return self.d


# ---------------------------------------------------------------- inspection
def flatten(dlg: dict, max_depth: int = 12) -> str:
    """Readable outline of the conversation (for previews/tests)."""
    entries = dlg["EntryList"]["value"]
    replies = dlg["ReplyList"]["value"]
    lines: list[str] = []

    def fmt_cond(link: dict) -> str:
        active = G.get(link, "Active", "")
        if not active:
            return ""
        params = ",".join(f"{G.get(p, 'Key')}={G.get(p, 'Value')}" for p in (link.get("ConditionParams") or {}).get("value", []))
        return f" [if: {active}{'(' + params + ')' if params else ''}]"

    def fmt_script(node: dict) -> str:
        s = G.get(node, "Script", "")
        if not s:
            return ""
        params = ",".join(f"{G.get(p, 'Key')}={G.get(p, 'Value')}" for p in (node.get("ActionParams") or {}).get("value", []))
        return f" {{runs: {s}{'(' + params + ')' if params else ''}}}"

    def walk_entry(i: int, depth: int, seen: set) -> None:
        pad = "  " * depth
        e = entries[i]
        lines.append(f'{pad}[NPC #{i}] "{G.get_text(e, "Text")}"{fmt_script(e)}')
        if (depth, "e", i) in seen or depth > max_depth:
            return
        seen = seen | {(depth, "e", i)}
        for link in e["RepliesList"]["value"]:
            ri = G.get(link, "Index")
            r = replies[ri]
            lines.append(f'{pad}  [PC #{ri}]{fmt_cond(link)} "{G.get_text(r, "Text")}"{fmt_script(r)}')
            nxt = r["EntriesList"]["value"]
            if not nxt:
                lines[-1] += " [END]"
            for l2 in nxt:
                lines.append(f"{pad}    ->{fmt_cond(l2)}")
                walk_entry(G.get(l2, "Index"), depth + 3, seen)

    for s in dlg["StartingList"]["value"]:
        lines.append(f"START{fmt_cond(s)}:")
        walk_entry(G.get(s, "Index"), 1, set())
    return "\n".join(lines)


def scripts_used(dlg: dict) -> set[str]:
    out: set[str] = set()
    for n in dlg["EntryList"]["value"] + dlg["ReplyList"]["value"]:
        if G.get(n, "Script"):
            out.add(G.get(n, "Script"))
        for k in ("RepliesList", "EntriesList"):
            for l in (n.get(k) or {}).get("value", []):
                if G.get(l, "Active"):
                    out.add(G.get(l, "Active"))
    for s in dlg["StartingList"]["value"]:
        if G.get(s, "Active"):
            out.add(G.get(s, "Active"))
    return out
