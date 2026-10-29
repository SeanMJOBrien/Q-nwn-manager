"""Walkmesh: parsing, geometry, and calibration against real TFN object positions (needs the NWN install)."""

from __future__ import annotations

import statistics
import unittest

from tests.fixture import HAVE_TFN, MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import gffjson as G
from tfnstudio import instances as I
from tfnstudio import walkmesh as W
from tfnstudio.camps import CampBuilder
from tfnstudio.gamedata import GameData

WOK = """\
beginwalkmeshgeom demo
node aabb wok
  parent demo
  position 0.0 0.0 1.5
  verts 4
    5.0 5.0 -1.5
    -5.0 5.0 -1.5
    5.0 -5.0 -1.5
    -5.0 -5.0 -1.5
  faces 2
    0 1 2  1  0 1 2  3
    3 2 1  1  3 2 1  7
endnode
endwalkmeshgeom demo
"""


class ParsingTests(unittest.TestCase):
    def test_wok_applies_node_offset_and_materials(self):
        wok = W.parse_wok(WOK)
        self.assertEqual(len(wok.verts), 4)
        self.assertEqual([f[3] for f in wok.faces], [3, 7])
        self.assertAlmostEqual(wok.verts[0][2], 0.0)       # -1.5 + node z 1.5
        self.assertEqual(len(wok.boxes), 2)

    def test_set_and_surfacemat(self):
        models = W.parse_set("[GENERAL]\nName=x\n[TILE0]\nModel=Abc_01\nWalkMesh=msb01\n[TILE2]\nModel=abc_03\n[TILE0DOOR0]\nX=1\n")
        self.assertEqual(models, ["abc_01", "", "abc_03"])
        surf = W.parse_surfacemat("2DA V2.0\n\n   Label Walk WalkCheck\n0 NotDefined 0 0\n1 Dirt 1 1\n7 Nonwalk 0 1\n")
        self.assertEqual(surf[1], ("Dirt", True))
        self.assertEqual(surf[7], ("Nonwalk", False))

    def test_transition_is_the_per_tileset_height_step(self):
        self.assertEqual(W.parse_transition("[GENERAL]\nName=x\nTransition=4\n[TILE0]\nModel=a\n"), 4.0)
        self.assertEqual(W.parse_transition("[GENERAL]\nTransition=2.5\n"), 2.5)
        self.assertEqual(W.parse_transition("[GENERAL]\nName=x\n"), W.HEIGHT_STEP)          # absent
        self.assertEqual(W.parse_transition("[GENERAL]\nTransition=\n"), W.HEIGHT_STEP)      # empty
        self.assertEqual(W.parse_transition("[GENERAL]\nTransition=0\n"), W.HEIGHT_STEP)     # not positive
        self.assertEqual(W.parse_transition("[OTHER]\nTransition=9\n[GENERAL]\nName=x\n"), W.HEIGHT_STEP)  # wrong section

    def test_unrotate_is_inverse_of_tile_rotation(self):
        self.assertEqual(W.unrotate(3, 1, 0), (3, 1))
        self.assertEqual(W.unrotate(3, 1, 1), (1, -3))
        self.assertEqual(W.unrotate(3, 1, 2), (-3, -1))
        self.assertEqual(W.unrotate(3, 1, 3), (-1, 3))
        self.assertEqual(W.unrotate(3, 1, 4), (3, 1))

    def test_probe_prefers_walkable_highest_face(self):
        class FakeGD:
            def available(self): return True
            def fetch_many(self, names): pass
            def read_text(self, name): return None
        wm = W.Walkmesh(FakeGD())
        wok = W.parse_wok(WOK)
        wm._woks["demo"] = wok
        wm._sets["ts"] = ["demo"]
        wm._surf = dict(W.DEFAULT_SURFACES)
        are = {"Width": G.int_(1), "Height": G.int_(1), "Tileset": G.resref("ts"), "ResRef": G.resref("a"),
               "Tile_List": G.list_([G.struct(0, Tile_ID=G.int_(0), Tile_Orientation=G.int_(0), Tile_Height=G.int_(2))])}
        p = wm.probe(are, 7.0, 7.0)                    # upper-right half -> face 0 (material 3 grass)
        self.assertTrue(p.walkable)
        self.assertAlmostEqual(p.z, 10.0, places=3)    # mesh 0.0 + tile height 2 * 5 m (default step)
        q = wm.probe(are, 3.0, 3.0)                    # lower-left half -> face 1 (material 7 Nonwalk)
        self.assertFalse(q.walkable)
        self.assertEqual(q.label, "Nonwalk")
        self.assertFalse(wm.probe(are, -1, 5).walkable)  # outside the area
        grid = wm.grid(are)
        self.assertEqual((grid.width, grid.height), (10, 10))
        self.assertEqual(grid.at(7.5, 7.5), 1)
        self.assertEqual(grid.at(2.5, 2.5), 0)


class HeightStepTests(unittest.TestCase):
    """The ARE Tile_Height step is the tileset's `Transition=` (tcn01 = 4 m, tno01 = 2 m), not a constant 5 m."""

    def make(self, set_text):
        class FakeGD:
            def available(self): return True
            def fetch_many(self, names): pass
            def read_text(self, name): return set_text if name.endswith(".set") else None
        wm = W.Walkmesh(FakeGD())
        wm._woks["demo"] = W.parse_wok(WOK)
        wm._surf = dict(W.DEFAULT_SURFACES)
        return wm

    @staticmethod
    def area(height):
        return {"Width": G.int_(1), "Height": G.int_(1), "Tileset": G.resref("ts"), "ResRef": G.resref("a"),
                "Tile_List": G.list_([G.struct(0, Tile_ID=G.int_(0), Tile_Orientation=G.int_(0), Tile_Height=G.int_(height))])}

    def test_lift_follows_the_tilesets_transition(self):
        for transition, expected in ((4, 8.0), (2, 4.0), (5, 10.0)):
            wm = self.make(f"[GENERAL]\nTransition={transition}\n[TILE0]\nModel=demo\n")
            self.assertEqual(wm.height_step("ts"), transition)
            self.assertAlmostEqual(wm.probe(self.area(2), 7.0, 7.0).z, expected, places=3)

    def test_unknown_tileset_falls_back_to_five_metres(self):
        wm = self.make(None)
        wm._sets["ts"] = ["demo"]
        self.assertEqual(wm.height_step("ts"), 5.0)
        self.assertAlmostEqual(wm.probe(self.area(1), 7.0, 7.0).z, 5.0, places=3)


@unittest.skipUnless(HAVE_TFN, "real TFN checkout not found")
class CalibrationTests(MiniTfnCase):
    """Existing TFN creatures/waypoints stand on walkable ground at the mesh height: validates the port."""

    def setUp(self):
        self.p = self.project()
        self.gd = GameData(self.p)
        if not self.gd.available():
            self.skipTest("NWN game data / nwn_resman_extract not available")
        self.wm = W.Walkmesh(self.gd)

    def test_existing_objects_are_walkable_at_mesh_height(self):
        total = ok = close = 0
        for area in ("bandit_cave", "goblin2"):
            are, git = self.p.read("are", area), self.p.read("git", area)
            self.wm.prepare(are)
            for kind in ("creature", "waypoint"):
                for inst in I.instances(git, kind):
                    x, y, z = I.position_of(kind, inst)
                    pr = self.wm.probe(are, x, y)
                    total += 1
                    if pr.walkable:
                        ok += 1
                        close += abs(z - pr.z) <= 0.5
        self.assertGreater(total, 10)
        self.assertGreaterEqual(ok / total, 0.9, f"{ok}/{total} walkable")
        self.assertGreaterEqual(close / max(ok, 1), 0.9, f"{close}/{ok} heights within 0.5 m")

    def test_raised_tiles_use_the_tileset_transition_not_a_flat_five_metres(self):
        """Real objects on raised tiles of tcn01 (Transition 4) and tno01 (Transition 2) areas of TFN."""
        from tfnstudio.project import TfnProject
        from tests.fixture import REAL_TFN
        real = TfnProject(REAL_TFN, studio_dir=self.p.studio_dir)
        for area, tileset, step in (("benzor", "tcn01", 4), ("river_mirar", "tno01", 2), ("luskan_south", "tno01", 2)):
            if not (real.src / "are" / f"{area}.are.json").is_file():
                continue
            are, git = real.read("are", area), real.read("git", area)
            self.wm.prepare(are)
            self.assertEqual(self.wm.height_step(tileset), step)
            total = right = wrong = 0
            for kind in ("creature", "waypoint", "placeable"):
                for inst in I.instances(git, kind):
                    x, y, z = I.position_of(kind, inst)
                    tile = self.wm._tile(are, int(x // 10), int(y // 10))
                    pr = self.wm.probe(are, x, y)
                    if not tile or not tile[2] or not pr.walkable:
                        continue
                    flat = pr.z - tile[2] * step           # mesh height with no tile lift
                    total += 1
                    right += abs(z - (flat + tile[2] * step)) <= 0.5
                    wrong += abs(z - (flat + tile[2] * 5.0)) <= 0.5
            self.assertGreaterEqual(total, 5, f"{area}: need objects on raised tiles")
            self.assertGreaterEqual(right / total, 0.8, f"{area}: {right}/{total} within 0.5 m using Transition={step}")
            self.assertLessEqual(wrong / total, 0.2, f"{area}: {wrong}/{total} also match a flat 5 m - test would not discriminate")

    def test_grid_shape_and_fraction(self):
        are = self.p.read("are", "bandit_cave")
        grid = self.wm.grid(are)
        self.assertEqual((grid.width, grid.height), (80, 80))
        self.assertTrue(0.05 < grid.walkable_fraction() < 1.0)
        self.assertEqual(len(grid.to_rows()), 80)

    def test_camp_builder_uses_walkmesh_height_and_warns_off_ground(self):
        are, git = self.p.read("are", "bandit_cave"), self.p.read("git", "bandit_cave")
        cx, cy, cz = I.position_of("creature", I.instances(git, "creature")[2])      # hakt, z = 3.0 (raised cave floor)
        plan = {"id": "wm_test", "area": "bandit_cave", "objects": [
            {"kind": "placeable", "resref": "treas_barrel", "x": cx + 1.0, "y": cy, "facing": 0}]}
        cs = CampBuilder(self.p, walk=self.wm).build(plan)
        placed = [i for k, i in I.plan_instances(cs.load("git", "bandit_cave"), "wm_test")][0]
        self.assertAlmostEqual(G.get(placed, "Z"), self.wm.probe(are, cx + 1.0, cy).z, places=2)
        self.assertTrue(any("walkmesh" in n for n in cs.notes), cs.notes)
        # a creature in the middle of solid rock is flagged
        wall = next(((x + 0.5, y + 0.5) for y in range(0, 80, 2) for x in range(0, 80, 2)
                     if not self.wm.probe(are, x + 0.5, y + 0.5).walkable and self.wm.probe(are, x + 0.5, y + 0.5).error == ""), None)
        self.assertIsNotNone(wall)
        plan["objects"] = [{"kind": "creature", "resref": "bandit", "x": wall[0], "y": wall[1], "facing": 0}]
        cs2 = CampBuilder(self.p, walk=self.wm).build(plan)
        self.assertTrue(any("non-walkable" in w for w in cs2.warnings), cs2.warnings)


if __name__ == "__main__":
    unittest.main()
