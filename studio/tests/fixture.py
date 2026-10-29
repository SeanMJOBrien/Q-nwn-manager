"""Test fixture: a throw-away mini TFN checkout built from real TFN files.

Real TFN (default ~/git/the-frozen-north, or $TFN_ROOT) is only ever *read*.
Everything the tests write goes to a temp dir.  Tests skip when TFN is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REAL_TFN = Path(os.environ.get("TFN_ROOT") or Path.home() / "git" / "the-frozen-north")
HAVE_TFN = (REAL_TFN / "src" / "git").is_dir()

# (ext, resref) files copied into every mini project
CORE_FILES = (
    [("are", "bandit_cave"), ("git", "bandit_cave"), ("are", "goblin2"), ("git", "goblin2")]
    + [("utc", f"random{n}") for n in range(1, 10)]
    + [("utc", r) for r in ("bandit", "bandit_fighter", "bandit_mage", "bandit_dog", "bandit_leader",
                            "guzud", "jolie", "kurth", "goblin_chieftain")]
    + [("utp", r) for r in ("_campfire", "treas_barrel", "treas_chest", "plx_ppchest")]
    + [("ute", "bandit_moderate"), ("uti", "q_brain"), ("utw", "_wp_event"),
       ("dlg", "jolie"), ("dlg", "corpse_orlane"), ("jrl", "module")]
)


def make_mini_tfn(dest: Path) -> Path:
    """Create <dest>/tfn with the core files, a copy of src/nss, and symlinked tools."""
    root = dest / "tfn"
    for ext, res in CORE_FILES:
        src = REAL_TFN / "src" / ext / f"{res}.{ext}.json"
        if not src.is_file():
            continue
        dst = root / "src" / ext / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    nss_dst = root / "src" / "nss"
    nss_dst.mkdir(parents=True, exist_ok=True)
    for p in (REAL_TFN / "src" / "nss").glob("*.nss"):
        shutil.copy2(p, nss_dst / p.name)
    for d in ("tools", "nwn-base-scripts"):  # read-only use; studio never writes outside src/
        if (REAL_TFN / d).exists():
            os.symlink(REAL_TFN / d, root / d)
    (root / "src" / "dlg").mkdir(parents=True, exist_ok=True)
    shared = REAL_TFN.parent / "nwn-tools"          # sibling of the project, like in ~/git (resman extract, etc.)
    if shared.exists():
        os.symlink(shared, dest / "nwn-tools")
    return root


def git_init_commit(root: Path) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    for args in (["init", "-q", "-b", "main"], ["add", "-A", "src"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)


class MiniTfnCase(unittest.TestCase):
    """Base class: a fresh mini TFN per test class (copy is cheap but not free)."""

    tmp: tempfile.TemporaryDirectory
    root: Path

    @classmethod
    def setUpClass(cls) -> None:
        if not HAVE_TFN:
            raise unittest.SkipTest("real TFN checkout not found (set TFN_ROOT)")
        cls.tmp = tempfile.TemporaryDirectory(prefix="tfnstudio-test-")
        cls.root = make_mini_tfn(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def project(self):
        from tfnstudio.project import TfnProject
        return TfnProject(self.root, studio_dir=Path(self.tmp.name) / "studio")
