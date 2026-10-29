"""A tiny nwn-manager style module (flat unpacked/ layout, no Frozen North files) for testing generic mode."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tfnstudio import gffjson as G  # noqa: E402

ARE_TILE = G.struct(0, Tile_AnimLoop1=G.byte(0), Tile_AnimLoop2=G.byte(0), Tile_AnimLoop3=G.byte(0), Tile_Height=G.int_(0),
                    Tile_ID=G.int_(0), Tile_MainLight1=G.byte(0), Tile_MainLight2=G.byte(0), Tile_Orientation=G.int_(0),
                    Tile_SrcLight1=G.byte(0), Tile_SrcLight2=G.byte(0))


def area_are(res: str, name: str) -> dict:
    return {"__data_type": "ARE ", "Height": G.int_(1), "Width": G.int_(1), "Name": G.locstring(name), "Tag": G.cexostring(res),
            "ResRef": G.resref(res), "OnEnter": G.resref(""), "OnExit": G.resref(""), "OnHeartbeat": G.resref(""),
            "OnUserDefined": G.resref(""), "Tile_List": G.list_([ARE_TILE])}


def area_git(creatures=()) -> dict:
    return {"__data_type": "GIT ", "Creature List": G.list_(list(creatures)), "Placeable List": G.list_(),
            "Waypoint List": G.list_(), "TriggerList": G.list_(), "Door List": G.list_(), "List": G.list_(),
            "SoundList": G.list_(), "StoreList": G.list_(), "EncounterList": G.list_()}


def module_ifo() -> dict:
    return {"__data_type": "IFO ", "Mod_Name": G.locstring("Fixture Module"), "Mod_Tag": G.cexostring("fixture"),
            "Mod_OnAcquirItem": G.resref(""), "Mod_Entry_Area": G.resref("start")}


def make_generic_module(dest: Path) -> Path:
    root = dest.resolve() / "mod"
    unp = root / "unpacked"
    unp.mkdir(parents=True)
    (root / "nasher.cfg").write_text("[Package]\nname = \"fixture\"\n")
    for res, name in (("start", "Start Area"), ("cave", "The Cave")):
        (unp / f"{res}.are.json").write_text(G.dumps(area_are(res, name)))
        (unp / f"{res}.git.json").write_text(G.dumps(area_git()))
    (unp / "module.ifo.json").write_text(G.dumps(module_ifo()))
    (root / ".gitignore").write_text(".studio/\n")
    env = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    import os
    env = dict(os.environ, **env)
    for args in (["init", "-q", "-b", "main"], ["add", "-A", "."], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)
    return root


class GenericCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="tfnstudio-generic-")
        cls.root = make_generic_module(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def studio(self):
        from tfnstudio.service import Studio
        return Studio(self.root)
