"""Staged change sets: generators write here; nothing reaches TFN until Apply.

A ChangeSet is a bundle of whole-file replacements (relative to the TFN root,
always under `src/`).  It is persisted under `.studio/changes/<id>/` so the web
UI can show diffs/validation later, and Apply records an undo log under
`.studio/applied/<id>/`.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import gffjson as G
from .project import ProjectError, TfnProject


def sha256_text(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "change"


@dataclass
class FileChange:
    rel: str                       # e.g. "src/git/bandit_cave.git.json"
    new_text: str
    old_text: str | None           # None => file does not exist yet (create)
    base_hash: str | None          # sha256 of the on-disk text when staged
    note: str = ""

    @property
    def action(self) -> str:
        return "create" if self.old_text is None else "modify"

    @property
    def changed(self) -> bool:
        return self.old_text != self.new_text


@dataclass
class ChangeSet:
    project: TfnProject
    title: str
    kind: str = "misc"             # camp | quest | ute | misc
    id: str = ""
    spec: str = ""                 # path/name of the plan that produced it
    created: float = field(default_factory=time.time)
    files: dict[str, FileChange] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.created)) + "-" + slugify(self.title, 28)

    # ----------------------------------------------------------- read/write
    def _disk_text(self, rel: str) -> str | None:
        p = self.project.abs_from_rel(rel)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def pending_text(self, rel: str) -> str | None:
        """Staged text for `rel` if this change set already touches it, else what is on disk."""
        fc = self.files.get(rel)
        return fc.new_text if fc else self._disk_text(rel)

    def stage_text(self, rel: str, text: str, note: str = "") -> FileChange:
        self.project.abs_from_rel(rel)  # path confinement check
        existing = self.files.get(rel)
        if existing:
            existing.new_text = text
            if note:
                existing.note = note
            return existing
        old = self._disk_text(rel)
        fc = FileChange(rel=rel, new_text=text, old_text=old, base_hash=sha256_text(old), note=note)
        self.files[rel] = fc
        if old is not None and fc.rel.endswith(".json"):
            try:
                if G.dumps(G.loads(old)) != old:
                    self.warnings.append(f"{rel}: existing file is not in canonical nwn_gff format; "
                                         "applying will reformat parts of it")
            except ValueError:
                pass
        return fc

    # JSON helpers keyed by (ext, resref)
    def rel_json(self, ext: str, resref: str) -> str:
        return self.project.rel(self.project.json_path(ext, resref))

    def rel_nss(self, resref: str) -> str:
        return self.project.rel(self.project.nss_path(resref))

    def load(self, ext: str, resref: str) -> dict:
        """Parsed JSON as this change set sees it (staged version wins over disk). Private copy."""
        rel = self.rel_json(ext, resref)
        text = self.pending_text(rel)
        if text is None:
            raise ProjectError(f"{ext} {resref!r} not found (disk or staged)")
        return G.loads(text)

    def exists(self, ext: str, resref: str) -> bool:
        return self.pending_text(self.rel_json(ext, resref)) is not None

    def save(self, ext: str, resref: str, obj: dict, note: str = "") -> FileChange:
        return self.stage_text(self.rel_json(ext, resref), G.dumps(obj), note)

    def save_nss(self, resref: str, source: str, note: str = "") -> FileChange:
        if not source.endswith("\n"):
            source += "\n"
        return self.stage_text(self.rel_nss(resref), source, note)

    # ------------------------------------------------------------ reporting
    def changed_files(self) -> list[FileChange]:
        return [f for f in self.files.values() if f.changed]

    def diff(self, rel: str | None = None, context: int = 3) -> str:
        out: list[str] = []
        for fc in (self.files.values() if rel is None else [self.files[rel]]):
            if not fc.changed:
                continue
            a = [] if fc.old_text is None else fc.old_text.splitlines(keepends=True)
            b = fc.new_text.splitlines(keepends=True)
            out.extend(difflib.unified_diff(
                a, b, fromfile="/dev/null" if fc.old_text is None else f"a/{fc.rel}",
                tofile=f"b/{fc.rel}", n=context))
        return "".join(out)

    def summary(self) -> dict:
        files = []
        for fc in self.files.values():
            old_n = 0 if fc.old_text is None else len(fc.old_text.splitlines())
            new_n = len(fc.new_text.splitlines())
            added = removed = 0
            if fc.changed:
                sm = difflib.SequenceMatcher(None, (fc.old_text or "").splitlines(), fc.new_text.splitlines(),
                                             autojunk=False)
                for tag, i1, i2, j1, j2 in sm.get_opcodes():
                    if tag in ("replace", "delete"):
                        removed += i2 - i1
                    if tag in ("replace", "insert"):
                        added += j2 - j1
            files.append({"rel": fc.rel, "action": fc.action, "changed": fc.changed, "lines": new_n,
                          "prev_lines": old_n, "added": added, "removed": removed, "note": fc.note})
        return {"id": self.id, "title": self.title, "kind": self.kind, "spec": self.spec,
                "created": self.created, "files": files, "warnings": self.warnings, "notes": self.notes}

    # ---------------------------------------------------------- persistence
    def _dir(self) -> Path:
        return self.project.studio_dir / "changes" / self.id

    def persist(self) -> Path:
        d = self._dir()
        if d.exists():
            for p in sorted(d.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
        (d / "files").mkdir(parents=True, exist_ok=True)
        meta = {"id": self.id, "title": self.title, "kind": self.kind, "spec": self.spec, "created": self.created,
                "warnings": self.warnings, "notes": self.notes, "files": []}
        for i, fc in enumerate(self.files.values()):
            (d / "files" / f"{i:03d}.new").write_text(fc.new_text, encoding="utf-8")
            if fc.old_text is not None:
                (d / "files" / f"{i:03d}.old").write_text(fc.old_text, encoding="utf-8")
            meta["files"].append({"rel": fc.rel, "idx": i, "base_hash": fc.base_hash, "note": fc.note,
                                  "create": fc.old_text is None})
        (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return d

    @classmethod
    def load_saved(cls, project: TfnProject, change_id: str) -> "ChangeSet":
        if not re.match(r"^[0-9a-z-]{3,80}$", change_id):
            raise ProjectError("invalid change id")
        d = project.studio_dir / "changes" / change_id
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        cs = cls(project, meta["title"], meta.get("kind", "misc"), id=meta["id"], spec=meta.get("spec", ""),
                 created=meta.get("created", time.time()))
        cs.warnings = meta.get("warnings", [])
        cs.notes = meta.get("notes", [])
        for f in meta["files"]:
            new = (d / "files" / f"{f['idx']:03d}.new").read_text(encoding="utf-8")
            old_p = d / "files" / f"{f['idx']:03d}.old"
            old = old_p.read_text(encoding="utf-8") if old_p.is_file() and not f.get("create") else None
            cs.files[f["rel"]] = FileChange(f["rel"], new, old, f.get("base_hash"), f.get("note", ""))
        return cs


def list_saved(project: TfnProject) -> list[dict]:
    root = project.studio_dir / "changes"
    out = []
    if root.is_dir():
        for d in sorted(root.iterdir(), reverse=True):
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            applied = (project.studio_dir / "applied" / meta["id"] / "log.json").is_file()
            out.append({"id": meta["id"], "title": meta["title"], "kind": meta.get("kind", "misc"),
                        "created": meta.get("created"), "files": len(meta["files"]), "applied": applied,
                        "warnings": len(meta.get("warnings", []))})
    return out


def discard(project: TfnProject, change_id: str) -> bool:
    if not re.match(r"^[0-9a-z-]{3,80}$", change_id):
        raise ProjectError("invalid change id")
    d = project.studio_dir / "changes" / change_id
    if not d.is_dir():
        return False
    for p in sorted(d.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    d.rmdir()
    return True


# ---------------------------------------------------------------------------
# Apply / undo
# ---------------------------------------------------------------------------

@dataclass
class ApplyResult:
    ok: bool
    applied: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    dry_run: bool = False


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".studio-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def apply_changeset(project: TfnProject, cs: ChangeSet, *, allow_dirty: bool = False,
                    force_conflicts: bool = False, dry_run: bool = False) -> ApplyResult:
    res = ApplyResult(ok=False, dry_run=dry_run)
    todo = cs.changed_files()
    if not todo:
        res.problems.append("nothing to apply (no changed files)")
        return res

    # 1. conflicts: the file must still be what we staged against
    for fc in todo:
        p = project.abs_from_rel(fc.rel)
        cur = p.read_text(encoding="utf-8") if p.is_file() else None
        if sha256_text(cur) != fc.base_hash and cur != fc.new_text:
            msg = f"{fc.rel}: changed on disk since this change set was staged"
            if force_conflicts:
                res.problems.append("(forced) " + msg)
            else:
                res.problems.append(msg)

    # 2. dirty guard: don't pile generated edits on top of uncommitted work
    dirty = project.git_status([fc.rel for fc in todo])
    for fc in todo:
        code = dirty.get(fc.rel)
        if code and not allow_dirty:
            res.problems.append(f"{fc.rel}: has uncommitted changes in git ({code.strip() or code}); "
                                "commit/stash them or pass allow_dirty")

    blocking = [p for p in res.problems if not p.startswith("(forced)")]
    if blocking:
        return res
    if dry_run:
        res.ok = True
        res.applied = [fc.rel for fc in todo]
        return res

    # 3. write, remembering the previous content for undo
    log_dir = project.studio_dir / "applied" / cs.id
    (log_dir / "before").mkdir(parents=True, exist_ok=True)
    log = {"id": cs.id, "title": cs.title, "when": time.time(), "files": []}
    for i, fc in enumerate(todo):
        p = project.abs_from_rel(fc.rel)
        before = p.read_text(encoding="utf-8") if p.is_file() else None
        if before is not None:
            (log_dir / "before" / f"{i:03d}").write_text(before, encoding="utf-8")
        _atomic_write(p, fc.new_text)
        log["files"].append({"rel": fc.rel, "idx": i, "created": before is None,
                             "after_hash": sha256_text(fc.new_text)})
        res.applied.append(fc.rel)
    (log_dir / "log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    res.ok = True
    return res


def undo_applied(project: TfnProject, change_id: str, *, force: bool = False) -> ApplyResult:
    if not re.match(r"^[0-9a-z-]{3,80}$", change_id):
        raise ProjectError("invalid change id")
    res = ApplyResult(ok=False)
    log_dir = project.studio_dir / "applied" / change_id
    try:
        log = json.loads((log_dir / "log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res.problems.append("no apply log for that change id")
        return res
    # verify nothing was edited since
    for f in log["files"]:
        p = project.abs_from_rel(f["rel"])
        cur = p.read_text(encoding="utf-8") if p.is_file() else None
        if sha256_text(cur) != f["after_hash"] and not force:
            res.problems.append(f"{f['rel']}: modified since it was applied; refusing to overwrite (force to override)")
    if res.problems:
        return res
    for f in log["files"]:
        p = project.abs_from_rel(f["rel"])
        if f["created"]:
            if p.is_file():
                p.unlink()
        else:
            _atomic_write(p, (log_dir / "before" / f"{f['idx']:03d}").read_text(encoding="utf-8"))
        res.applied.append(f["rel"])
    for p in sorted(log_dir.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    log_dir.rmdir()
    res.ok = True
    return res
