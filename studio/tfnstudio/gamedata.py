"""Access to base-game resources (tileset .set, walkmesh .wok, 2DAs) through `nwn_resman_extract`.

The NWN install is $NWN_ROOT when set, otherwise the first of the usual places that contains
`data/nwn_base.key` (see `candidate_roots`).  The user directory ($NWN_USER, else the first usual one that
exists) is only passed to the extractor when it exists.  Extracted files are cached under
`<studio>/.studio/gamedata/`.  TFN uses no haks and no custom TLK, so the base game is the complete source
for its tilesets.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from .project import TfnProject


def candidate_roots() -> list[Path]:
    """Places an NWN:EE install (the folder that contains `data/`) usually is, most likely first."""
    home = Path.home()
    roots = [home / "nwn-data",
             home / "Library" / "Application Support" / "Steam" / "steamapps" / "common" / "Neverwinter Nights",   # macOS
             home / ".local" / "share" / "Steam" / "steamapps" / "common" / "Neverwinter Nights",                 # Linux
             home / ".steam" / "steam" / "steamapps" / "common" / "Neverwinter Nights"]
    if platform.system().lower() == "windows":
        for base in ("C:/Program Files (x86)", "C:/Program Files"):
            roots.append(Path(base) / "Steam" / "steamapps" / "common" / "Neverwinter Nights")
        roots.append(Path("C:/GOG Games/Neverwinter Nights Enhanced Edition"))
    return roots


def candidate_user_dirs(root: Path) -> list[Path]:
    home = Path.home()
    return [root / "user", home / "Documents" / "Neverwinter Nights", home / ".local" / "share" / "Neverwinter Nights"]


def find_root() -> Path:
    """$NWN_ROOT, else the first usual install location that has data/nwn_base.key, else ~/nwn-data."""
    env = os.environ.get("NWN_ROOT")
    if env:
        return Path(env).expanduser()
    for cand in candidate_roots():
        if (cand / "data" / "nwn_base.key").is_file():
            return cand
    return Path.home() / "nwn-data"


def find_user_dir(root: Path) -> Path:
    env = os.environ.get("NWN_USER")
    if env:
        return Path(env).expanduser()
    for cand in candidate_user_dirs(root):
        if cand.is_dir():
            return cand
    return root / "user"


class GameData:
    def __init__(self, project: TfnProject, root: str | Path | None = None, user: str | Path | None = None):
        self.project = project
        self.root = Path(root).expanduser() if root else find_root()
        self.user = Path(user).expanduser() if user else find_user_dir(self.root)
        self.cache = project.studio_dir / "gamedata"
        self._missing: set[str] = set()

    def available(self) -> bool:
        return self.project.tool("nwn_resman_extract") is not None and (self.root / "data" / "nwn_base.key").is_file()

    def path(self, name: str) -> Path:
        return self.cache / name.lower()

    def fetch_many(self, names: list[str], timeout: int = 120) -> None:
        """Extract the exact-named resources that are not cached yet, in as few extractor runs as possible.

        `nwn_resman_extract` extracts NOTHING when any requested resource does not exist, and some tilesets have
        tiles without a walkmesh, so a failed batch is bisected until every resource that exists is extracted
        (the rest are remembered as missing and never requested again).
        """
        todo = sorted({n.lower() for n in names if not self.path(n).is_file() and n.lower() not in self._missing})
        if not todo:
            return
        tool = self.project.tool("nwn_resman_extract")
        if tool is None or not self.available():
            self._missing.update(todo)
            return
        self.cache.mkdir(parents=True, exist_ok=True)
        # very long argument lists are split to stay well under OS limits
        for i in range(0, len(todo), 200):
            self._extract(tool, todo[i:i + 200], timeout, {"calls": 0, "ok": False})
        self._missing.update(n for n in todo if not self.path(n).is_file())

    # Without any success after this many runs the extractor itself is broken (not just short of a resource): stop.
    MAX_RUNS_WITHOUT_SUCCESS = 6

    def _extract(self, tool: Path, batch: list[str], timeout: int, state: dict) -> None:
        batch = [n for n in batch if not self.path(n).is_file()]
        if not batch or (not state["ok"] and state["calls"] >= self.MAX_RUNS_WITHOUT_SUCCESS):
            return
        state["calls"] += 1
        cmd = [str(tool), "--root", str(self.root)]
        if self.user.is_dir():
            cmd += ["--userdirectory", str(self.user)]
        try:
            subprocess.run([*cmd, "-d", str(self.cache), *batch],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
        if all(self.path(n).is_file() for n in batch):
            state["ok"] = True
            return
        batch = [n for n in batch if not self.path(n).is_file()]
        if len(batch) == 1:
            return
        mid = (len(batch) + 1) // 2
        self._extract(tool, batch[:mid], timeout, state)
        self._extract(tool, batch[mid:], timeout, state)

    def fetch(self, name: str) -> Path | None:
        self.fetch_many([name])
        p = self.path(name)
        return p if p.is_file() else None

    def read_text(self, name: str) -> str | None:
        p = self.fetch(name)
        return p.read_text(encoding="latin-1") if p else None
