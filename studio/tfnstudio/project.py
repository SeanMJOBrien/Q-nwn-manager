"""Access to a module project: paths, cached reads, git state, tools.

Two project layouts are understood (see `detect_layout`):
  by_ext  nasher project with one folder per file type: src/are, src/git, src/utc, src/nss, src/jrl (The Frozen North)
  flat    nwn-manager project: everything side by side in one folder, unpacked/<resref>.<ext>.json and unpacked/<name>.nss
and two profiles (`detect_profile`): "tfn" (the module ships TFN's own quest/spawn scripts) and "generic" (any other
module; the studio installs a small runtime of its own, see runtime.py).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

from . import gffjson as G

# Resrefs we *create* are strict; ones we merely look up are lenient (but still path-safe).
NEW_RESREF_RE = re.compile(r"^[a-z0-9_]{1,16}$")
LOOKUP_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")

GFF_EXTS = ("are", "git", "gic", "utc", "utd", "ute", "uti", "utm", "utp", "utt", "utw",
            "dlg", "jrl", "ifo", "fac", "itp")

DEFAULT_TFN_ROOT = Path.home() / "git" / "the-frozen-north"
STUDIO_ROOT = Path(__file__).resolve().parent.parent

# Where the NWN command-line tools live, per OS: <tools root>/<platform dir>/<folder>/<program>.
# Tools roots searched: $NWN_TOOLS, <TFN>/tools, <TFN>/../nwn-tools, <studio>/../nwn-tools.
TOOL_LAYOUT = {
    "nwn_gff": (("neverwinter", "neverwinter64"), "nwn_gff"),
    "nwn_resman_extract": (("neverwinter", "neverwinter64"), "nwn_resman_extract"),
    "nwnsc": (("nwnsc",), "nwnsc"),
    "nasher": (("nasher",), "nasher"),
}


def platform_dirs() -> list[str]:
    """Names of the per-OS tool folders for this machine, best match first (linux / macos_arm64 / win)."""
    system = platform.system().lower()
    if system == "darwin":
        return ["macos_arm64"]      # the only macOS build that is shipped (Apple silicon)
    if system == "windows":
        return ["win"]
    return ["linux"]


def exe_suffix() -> str:
    return ".exe" if platform.system().lower() == "windows" else ""


def tool_roots(root: Path | None) -> list[Path]:
    """Folders that may contain the per-OS tool folders, most specific first (duplicates removed)."""
    roots: list[Path] = []
    for var in ("NWN_TOOLS", "NWN_TOOLS_DIR"):
        env = os.environ.get(var)
        if env:
            roots.append(Path(env).expanduser())
    if root is not None:
        roots += [root / "tools", root.parent / "nwn-tools"]
    roots.append(STUDIO_ROOT.parent / "nwn-tools")
    seen: set[Path] = set()
    return [r for r in roots if not (r in seen or seen.add(r))]


def tool_candidates(name: str, root: Path | None) -> list[Path]:
    """Every path where `name` is looked for on this OS (for diagnostics and lookup)."""
    layout = TOOL_LAYOUT.get(name)
    if layout is None:
        return []
    folders, exe = layout
    return [base / plat / folder / (exe + exe_suffix())
            for base in tool_roots(root) for plat in platform_dirs() for folder in folders]


def find_tool(name: str, root: Path | None) -> Path | None:
    """Locate an NWN tool: $NWN_GFF / $NWNSC / $NASHER / $NWN_RESMAN_EXTRACT first, then the per-OS folders."""
    env = os.environ.get(name.upper())
    if env and Path(env).expanduser().is_file():
        return Path(env).expanduser()
    for cand in tool_candidates(name, root):
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    on_path = shutil.which(name + exe_suffix())     # nwn-manager puts its bundled tools on PATH
    return Path(on_path) if on_path else None


LAYOUT_BY_EXT = "by_ext"
LAYOUT_FLAT = "flat"
PROFILES = ("tfn", "generic")


def detect_layout(path: Path) -> "tuple[str, Path] | None":
    """(layout, source folder) of a module project at `path`, or None when it is not one.

    studio.json in the project root can force it:  {"layout": "flat", "source": "unpacked", "profile": "generic"}
    """
    cfg = read_project_config(path)
    src = cfg.get("source")
    layout = cfg.get("layout")
    if src and layout in (LAYOUT_BY_EXT, LAYOUT_FLAT) and (path / src).is_dir():
        return layout, path / src
    if (path / "src" / "git").is_dir() and (path / "src" / "are").is_dir():
        return LAYOUT_BY_EXT, path / "src"
    for name in ("unpacked", "src"):
        d = path / name
        if d.is_dir() and (any(d.glob("*.are.json")) or any(d.glob("*.ifo.json"))):
            return LAYOUT_FLAT, d
    return None


def read_project_config(path: Path) -> dict:
    f = path / "studio.json"
    if not f.is_file():
        return {}
    try:
        data = G.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_checkout(path: Path) -> bool:
    return detect_layout(path) is not None


def looks_like_tfn(path: Path) -> bool:
    """A module checkout that is specifically The Frozen North (it ships inc_quest.nss / SPAWN_SYSTEM.md)."""
    found = detect_layout(path)
    if found is None:
        return False
    layout, src = found
    nss = src / "nss" / "inc_quest.nss" if layout == LAYOUT_BY_EXT else src / "inc_quest.nss"
    if nss.is_file():       # the studio's own runtime ships an inc_quest too (it says so in its first lines)
        return "tfn-content-studio" not in nss.read_text(encoding="utf-8", errors="replace")[:600]
    return (path / "SPAWN_SYSTEM.md").is_file()


def detect_profile(path: Path) -> str:
    forced = os.environ.get("STUDIO_PROFILE") or read_project_config(path).get("profile")
    if forced in PROFILES:
        return forced
    return "tfn" if looks_like_tfn(path) else "generic"


def find_checkouts(near: list[Path], limit: int = 5) -> list[Path]:
    """TFN checkouts among `near` and their direct children (for "did you mean" hints)."""
    found: list[Path] = []
    for base in near:
        try:
            candidates = [base] + (sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else [])
        except OSError:
            continue
        for cand in candidates:
            if cand not in found and looks_like_tfn(cand):
                found.append(cand)
            if len(found) >= limit:
                return found
    return found


def prog_name() -> str:
    """How the user invoked the studio (./bin/tfn-studio, tfn-studio, ...), for hints in messages."""
    import sys
    arg0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    return arg0 if Path(arg0).name == "tfn-studio" else "tfn-studio"


def checkout_problem(root: Path, source: str) -> str | None:
    """None when `root` is a TFN checkout; otherwise an actionable explanation."""
    if is_checkout(root):
        return None
    if not root.exists():
        why = "that folder does not exist"
    elif not root.is_dir():
        why = "that is a file, not a folder"
    else:
        why = ("expected src/are + src/git (nasher layout) or unpacked/*.are.json (nwn-manager project); "
               "the project root is the folder that contains them")
    lines = [f"{root} is not a module project: {why}.",
             f"  (path taken from {source})"]
    near = [root.parent, Path.cwd(), Path.home() / "git", STUDIO_ROOT.parent]
    if root.is_dir():
        near.insert(0, root)
    hints = [h for h in find_checkouts(near) if h != root]
    if hints:
        lines.append("  module projects nearby:")
        lines += [f"    {h}" for h in hints]
        lines.append(f'  Try:  {prog_name()} --tfn "{hints[0]}" <command>      (or:  export TFN_ROOT="{hints[0]}")')
    else:
        lines.append("  Point the studio at your module project (a nwn-manager project, or a nasher project that has src/are and src/git):")
        lines.append(f'    {prog_name()} --tfn "/path/to/the-frozen-north" <command>     or     export TFN_ROOT="/path/to/the-frozen-north"')
    lines.append(f"  Run `{prog_name()} doctor` for a full environment check.")
    manual = STUDIO_ROOT / "MANUAL.html"
    if manual.is_file():
        lines.append(f"  The manual needs no setup - open it in a browser: {manual}")
    return "\n".join(lines)


def find_project_above(start: Path) -> "Path | None":
    """Nearest folder at or above `start` that has a nasher.cfg and is a module project (like git finding .git)."""
    for d in [start, *start.parents]:
        if (d / "nasher.cfg").is_file() and is_checkout(d):
            return d
    return None


def resolve_root(root: str | Path | None) -> tuple[Path, str]:
    """The project root to use and where it came from: --module/--tfn, $MODULE_ROOT / $TFN_ROOT, the current
    nwn-manager project, or the default TFN location."""
    if root:
        return Path(root).expanduser().resolve(), "--tfn"
    for var in ("MODULE_ROOT", "TFN_ROOT"):
        env = os.environ.get(var)
        if env:
            return Path(env).expanduser().resolve(), f"the {var} environment variable"
    here = find_project_above(Path.cwd())
    if here is not None:
        return here, "the current folder (nearest nasher.cfg)"
    return DEFAULT_TFN_ROOT.expanduser().resolve(), "the default location ~/git/the-frozen-north"


class ProjectError(Exception):
    """Raised for problems with the TFN checkout or with user-supplied names."""


class NotFoundError(ProjectError):
    """A requested resource does not exist in the TFN checkout (HTTP 404)."""


def check_new_resref(name: str, what: str = "resref") -> str:
    if not isinstance(name, str) or not NEW_RESREF_RE.match(name):
        raise ProjectError(f"invalid {what} {name!r}: use 1-16 chars of a-z, 0-9, _")
    return name


def check_lookup_name(name: str, what: str = "name") -> str:
    if not isinstance(name, str) or not LOOKUP_NAME_RE.match(name):
        raise ProjectError(f"invalid {what} {name!r}")
    return name


class TfnProject:
    def __init__(self, root: str | Path | None = None, studio_dir: str | Path | None = None):
        root, source = resolve_root(root)
        problem = checkout_problem(root, source)
        if problem:
            raise ProjectError(problem)
        self.root = root
        self.layout, self.src = detect_layout(root)
        self.profile = detect_profile(root)
        # The Frozen North keeps its staging area next to the studio (as always); any other module keeps it in the project
        default_dir = STUDIO_ROOT / ".studio" if self.profile == "tfn" else root / ".studio"
        self.studio_dir = Path(studio_dir) if studio_dir else default_dir
        self.cache_dir = self.studio_dir / "cache"
        self._lru: OrderedDict[tuple, dict] = OrderedDict()

    # ------------------------------------------------------------------ paths
    def json_path(self, ext: str, resref: str) -> Path:
        if ext not in GFF_EXTS:
            raise ProjectError(f"unknown resource type {ext!r}")
        check_lookup_name(resref, "resref")
        if self.layout == LAYOUT_FLAT:
            return self.src / f"{resref}.{ext}.json"
        return self.src / ext / f"{resref}.{ext}.json"

    def nss_path(self, resref: str) -> Path:
        check_lookup_name(resref, "script name")
        return (self.src if self.layout == LAYOUT_FLAT else self.src / "nss") / f"{resref}.nss"

    def rel(self, path: str | Path) -> str:
        """Path relative to the TFN root, POSIX style (the form used in change sets)."""
        return Path(path).resolve().relative_to(self.root).as_posix()

    def abs_from_rel(self, rel: str) -> Path:
        """Resolve a change-set path, refusing anything outside <root>/src."""
        p = (self.root / rel).resolve()
        try:
            p.relative_to(self.src.resolve())
        except ValueError:
            raise ProjectError(f"refusing path outside {self.src.name}/: {rel}")
        return p

    def exists(self, ext: str, resref: str) -> bool:
        return self.json_path(ext, resref).is_file()

    def script_exists(self, resref: str) -> bool:
        return self.nss_path(resref).is_file()

    def list_resrefs(self, ext: str) -> list[str]:
        suffix = f".{ext}.json"
        d = self.src if self.layout == LAYOUT_FLAT else self.src / ext
        if not d.is_dir():
            return []
        return sorted(p.name[: -len(suffix)] for p in d.iterdir() if p.name.endswith(suffix))

    def nss_names(self) -> set[str]:
        d = self.nss_dir
        return {p.stem for p in d.iterdir() if p.suffix == ".nss"} if d.is_dir() else set()

    @property
    def nss_dir(self) -> Path:
        return self.src if self.layout == LAYOUT_FLAT else self.src / "nss"

    def jrl_path(self) -> Path:
        return self.src / "module.jrl.json" if self.layout == LAYOUT_FLAT else self.src / "jrl" / "module.jrl.json"

    def parse_rel(self, rel: str) -> "tuple[str, str]":
        """(ext, resref) of a project-relative JSON path as used in change sets; ("", "") for anything else."""
        try:
            inner = Path(rel).relative_to(self.src.relative_to(self.root)).as_posix()
        except ValueError:
            return "", ""
        if self.layout == LAYOUT_FLAT:
            m = re.match(r"^([^/]+)\.([a-z]+)\.json$", inner)
            return (m.group(2), m.group(1)) if m else ("", "")
        m = re.match(r"^([a-z]+)/(.+)\.([a-z]+)\.json$", inner)
        return (m.group(1), m.group(2)) if m else ("", "")

    def base_script_dirs(self) -> list[Path]:
        """Folders with the base game's nwscript.nss and includes (for compiling and for "does this script exist")."""
        dirs = [self.root / "nwn-base-scripts"]
        env = os.environ.get("NWN_BASE_SCRIPTS_DIR")
        if env:
            dirs.insert(0, Path(env).expanduser())
        dirs += [r / "base-scripts" for r in tool_roots(self.root)]
        return [d for d in dirs if d.is_dir()]

    def base_script_exists(self, name: str) -> bool:
        return any((d / f"{name}.nss").is_file() for d in self.base_script_dirs())

    # ------------------------------------------------------------------ reads
    def read_path(self, path: Path) -> dict:
        """Parsed JSON for `path`. Small files are LRU-cached; callers get a private copy."""
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
        hit = self._lru.get(key)
        if hit is not None:
            self._lru.move_to_end(key)
            return G.clone(hit)
        data = G.read(path)
        if st.st_size < 2_000_000:
            self._lru[key] = data
            while len(self._lru) > 128:
                self._lru.popitem(last=False)
            return G.clone(data)
        return data

    def read(self, ext: str, resref: str) -> dict:
        p = self.json_path(ext, resref)
        if not p.is_file():
            raise NotFoundError(f"{ext} {resref!r} not found in {self.src.name}/")
        return self.read_path(p)

    def journal(self) -> dict:
        p = self.jrl_path()
        if not p.is_file():
            if self.profile == "generic":       # a new module has no journal until its first quest creates one
                return {"__data_type": "JRL ", "Categories": G.list_()}
            raise ProjectError(f"{self.rel(p)} not found")
        return self.read_path(p)

    # ------------------------------------------------------------------ tools
    def tool(self, name: str) -> Path | None:
        """Locate a bundled/shared NWN tool ('nwn_gff', 'nwnsc', 'nasher', 'nwn_resman_extract') for this OS."""
        return find_tool(name, self.root)

    def include_dirs(self) -> list[Path]:
        dirs = [self.nss_dir, *self.base_script_dirs()]
        return [d for d in dirs if d.is_dir()]

    # -------------------------------------------------------------------- git
    def _git(self, *args: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout if r.returncode == 0 else ""

    def git_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def git_head(self) -> str:
        return self._git("rev-parse", "--short", "HEAD").strip()

    def git_status(self, rel_paths: list[str] | None = None) -> dict[str, str]:
        """{relative path: two-letter porcelain status} for dirty/untracked paths."""
        args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
        if rel_paths:
            args += ["--", *rel_paths]
        out = self._git(*args)
        status: dict[str, str] = {}
        parts = out.split("\0")
        i = 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            code, path = entry[:2], entry[3:]
            if code[0] in "RC":  # rename/copy has an extra "from" path entry
                i += 1
            status[path] = code
        return status
