"""Camp plans, prefabs and spawn groups."""

from __future__ import annotations

import unittest

from tests.fixture import MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import gffjson as G
from tfnstudio import instances as I
from tfnstudio import prefabs as PF
from tfnstudio import spawns as S
from tfnstudio import validate as V
from tfnstudio.camps import CampBuilder, PlanError, validate_plan
from tfnstudio.changeset import apply_changeset, undo_applied

PLAN = {
    "id": "unit_camp",
    "title": "Unit test camp",
    "area": "bandit_cave",
    "cr": 6,
    "objects": [
        {"kind": "placeable", "resref": "plc_bedrolls", "x": 40.0, "y": 40.0, "facing": 90},   # mined template
        {"kind": "placeable", "resref": "treas_barrel", "x": 42.0, "y": 40.5, "facing": 0},    # src/utp blueprint
        {"kind": "marker", "group": 2, "x": 30.0, "y": 30.0},
        {"kind": "marker", "group": 2, "x": 50.0, "y": 20.0},
        {"kind": "creature", "resref": "bandit", "x": 44.0, "y": 44.0, "facing": 180},
        {"kind": "waypoint", "resref": "_wp_event", "x": 35.0, "y": 35.0},
    ],
    "groups": [{"n": 2, "ute": "unit_grp", "spawns": 6, "script": ""}],
    "events": [],
    "new_utes": [{"resref": "unit_grp", "name": "Unit bandits", "difficulty": 3,
                  "creatures": [{"resref": "bandit"}, {"resref": "bandit_fighter", "unique": True},
                                {"resref": "bandit_mage", "unique": True}],
                  "rare": "bandit_leader"}],
}


def clone(d):
    return G.clone(d)


class PrefabTests(unittest.TestCase):
    def test_stamp_rotation_and_group_map(self):
        pf = {"id": "t", "items": [{"kind": "placeable", "resref": "a", "dx": 1, "dy": 0, "facing": 0},
                                   {"kind": "marker", "group": 1, "dx": 0, "dy": 2}]}
        out = PF.stamp(pf, 50, 50, rotation=90, group_map={1: 4})
        self.assertAlmostEqual(out[0]["x"], 50.0, places=3)
        self.assertAlmostEqual(out[0]["y"], 51.0, places=3)
        self.assertEqual(out[0]["facing"], 90.0)
        self.assertAlmostEqual(out[1]["x"], 48.0, places=3)
        self.assertEqual(out[1]["group"], 4)

    def test_validation(self):
        with self.assertRaises(Exception):
            PF.validate_prefab({"id": "Bad Id", "items": [{"kind": "placeable", "resref": "a"}]})
        with self.assertRaises(Exception):
            PF.validate_prefab({"id": "ok", "items": [{"kind": "marker", "group": 12}]})
        with self.assertRaises(Exception):
            PF.validate_prefab({"id": "ok", "items": []})

    def test_starter_library_loads(self):
        lib = PF.load_prefabs()
        self.assertGreaterEqual(len(lib), 8)
        self.assertIn("bandit_camp", lib)
        self.assertTrue(any(i["kind"] == "marker" for i in lib["bandit_camp"]["items"]))

    def test_from_objects_roundtrip(self):
        objs = [{"kind": "placeable", "resref": "plc_barrel", "x": 12, "y": 9, "facing": 30},
                {"kind": "marker", "group": 3, "x": 8, "y": 9}]
        pf = PF.from_objects("mine", "Mine", objs, origin=(10, 10))
        again = PF.stamp(pf, 10, 10)
        self.assertEqual([(o["x"], o["y"]) for o in again], [(12.0, 9.0), (8.0, 9.0)])


class PlanValidationTests(unittest.TestCase):
    def test_rejects_bad_input(self):
        for bad in (
            {"id": "BAD", "area": "x"},
            {"id": "ok", "area": "x", "objects": [{"kind": "tree", "x": 1, "y": 1}]},
            {"id": "ok", "area": "x", "objects": [{"kind": "marker", "x": 1, "y": 1, "group": 0}]},
            {"id": "ok", "area": "x", "groups": [{"n": 1, "ute": "u", "spawns": 0}]},
            {"id": "ok", "area": "x", "groups": [{"n": 1, "ute": "u", "spawns": 2}, {"n": 1, "ute": "v", "spawns": 2}]},
            {"id": "ok", "area": "x", "cr": 99},
        ):
            with self.assertRaises(PlanError, msg=str(bad)):
                validate_plan(bad)


class CampBuildTests(MiniTfnCase):
    def test_build_adds_objects_vars_and_ute(self):
        p = self.project()
        cs = CampBuilder(p).build(clone(PLAN))
        git = cs.load("git", "bandit_cave")
        mine = list(I.plan_instances(git, "unit_camp"))
        self.assertEqual(len(mine), 6)
        kinds = sorted(k for k, _ in mine)
        self.assertEqual(kinds, ["creature", "creature", "creature", "placeable", "placeable", "waypoint"])
        markers = [i for k, i in mine if G.get(i, "TemplateResRef") == "random2"]
        self.assertEqual(len(markers), 2)
        gv = G.vars_of(git)
        self.assertEqual((gv["cr"], gv["random2"], gv["random2_spawns"]), (6, "unit_grp", 6))
        self.assertIn("src/ute/unit_grp.ute.json", cs.files)
        ute = cs.load("ute", "unit_grp")
        self.assertEqual(G.get(ute, "TemplateResRef"), "unit_grp")
        self.assertEqual(G.get(ute, "DifficultyIndex"), 3)
        self.assertEqual(G.get_var(ute, "rare"), "bandit_leader")
        res = [G.get(c, "ResRef") for c in ute["CreatureList"]["value"]]
        self.assertEqual(res, ["bandit", "bandit_fighter", "bandit_mage"])
        self.assertEqual([G.get(c, "SingleSpawn") for c in ute["CreatureList"]["value"]], [0, 1, 1])

    def test_generated_content_validates(self):
        p = self.project()
        cs = CampBuilder(p).build(clone(PLAN))
        issues = V.validate_changeset(p, cs, compile_scripts=False)
        errors = [i for i in issues if i.level == "error"]
        self.assertEqual(errors, [], [e.message for e in errors])
        # bandit_cave's legacy random1 group points at a ute the mini fixture lacks: pre-existing, not blocking
        self.assertTrue(any(i.level == "warning" and i.message.startswith("(pre-existing)") for i in issues))

    def test_rebuild_is_idempotent(self):
        p = self.project()
        first = CampBuilder(p).build(clone(PLAN))
        res = apply_changeset(p, first)
        self.assertTrue(res.ok, res.problems)
        try:
            second = CampBuilder(p).build(clone(PLAN))
            git = second.load("git", "bandit_cave")
            self.assertEqual(len(list(I.plan_instances(git, "unit_camp"))), 6)  # replaced, not doubled
            self.assertTrue(any("replaced 6 objects" in n for n in second.notes), second.notes)
            # changing the plan removes objects that are no longer in it
            smaller = clone(PLAN)
            smaller["objects"] = smaller["objects"][:3]
            third = CampBuilder(p).build(smaller)
            self.assertEqual(len(list(I.plan_instances(third.load("git", "bandit_cave"), "unit_camp"))), 3)
        finally:
            undo_applied(p, first.id)

    def test_other_objects_untouched(self):
        p = self.project()
        before = p.read("git", "bandit_cave")
        cs = CampBuilder(p).build(clone(PLAN))
        after = cs.load("git", "bandit_cave")
        for kind in I.KIND_LIST:
            keep = [i for i in I.instances(after, kind) if not G.get_var(i, I.PLAN_VAR)]
            self.assertEqual(keep, I.instances(before, kind), kind)

    def test_out_of_bounds_and_unknowns_raise(self):
        p = self.project()
        bad = clone(PLAN)
        bad["objects"][0]["x"] = 5000
        with self.assertRaises(PlanError):
            CampBuilder(p).build(bad)
        bad = clone(PLAN)
        bad["objects"][0]["resref"] = "no_such_placeable_zz"
        with self.assertRaises(PlanError):
            CampBuilder(p).build(bad)
        bad = clone(PLAN)
        bad["objects"][4]["resref"] = "no_such_creature"
        with self.assertRaises(PlanError):
            CampBuilder(p).build(bad)
        bad = clone(PLAN)
        bad["area"] = "no_such_area"
        with self.assertRaises(PlanError):
            CampBuilder(p).build(bad)

    def test_spacing_warning(self):
        p = self.project()
        git = p.read("git", "bandit_cave")
        x, y, _ = I.position_of("placeable", I.instances(git, "placeable")[0])
        plan = clone(PLAN)
        plan["objects"] = [{"kind": "placeable", "resref": "treas_barrel", "x": x + 0.1, "y": y}]
        plan["groups"], plan["new_utes"] = [], []
        cs = CampBuilder(p).build(plan)
        self.assertTrue(any("within" in w for w in cs.warnings), cs.warnings)


class SpawnTests(MiniTfnCase):
    def test_build_ute_validations(self):
        p = self.project()
        with self.assertRaises(Exception):
            S.build_ute(p, {"resref": "x", "creatures": []})
        with self.assertRaises(Exception):
            S.build_ute(p, {"resref": "x", "creatures": [{"resref": "bandit", "unique": True}]})
        with self.assertRaises(Exception):
            S.build_ute(p, {"resref": "x", "difficulty": 9, "creatures": [{"resref": "bandit"}]})
        with self.assertRaises(Exception):
            S.build_ute(p, {"resref": "Bad-Name", "creatures": [{"resref": "bandit"}]})

    def test_edit_existing_preserves_unmanaged_fields(self):
        p = self.project()
        existing = p.read("ute", "bandit_moderate")
        ute, _ = S.build_ute(p, {"resref": "bandit_moderate", "difficulty": 0,
                                 "creatures": [{"resref": "bandit"}]}, existing)
        self.assertEqual(G.get(ute, "ResetTime"), G.get(existing, "ResetTime"))
        self.assertIsNone(G.get_var(ute, "rare"))  # rare dropped when spec has none
        self.assertEqual(G.get(ute, "DifficultyIndex"), 0)

    def test_expected_mix_and_cr_check(self):
        p = self.project()
        desc = S.describe_ute(p.read("ute", "bandit_moderate"))
        self.assertEqual(desc["unique_chance"], 20)
        mix = S.expected_mix(desc, 10)
        total = sum(r["expected"] for r in mix["rows"])
        self.assertAlmostEqual(total, mix["expected_total"], delta=0.1)
        self.assertEqual(mix["rare_chance"], 15)
        self.assertTrue(S.cr_check(desc, 20))  # CR far below area cr
        self.assertEqual(S.cr_check(desc, None), [])

    def test_usage(self):
        areas = {"a": {"resref": "a", "name": "A", "cr": 3, "groups": [{"n": 1, "ute": "u1", "spawns": 4}]},
                 "b": {"resref": "b", "name": "B", "cr": 5, "groups": [{"n": 2, "ute": "u2", "spawns": 4}]}}
        self.assertEqual([u["area"] for u in S.usage(areas, "u1")], ["a"])


if __name__ == "__main__":
    unittest.main()


class MinedCreatureTests(MiniTfnCase):
    def test_base_game_creature_placed_from_real_instance(self):
        """goblin_shaman has no blueprint in the mini project (like base-game creatures in TFN): a real instance is reused."""
        p = self.project()
        self.assertFalse(p.exists("utc", "goblin_shaman"))
        from tfnstudio import index as IX
        areas = IX.area_index(p)
        pal = IX.base_creature_palette(areas, IX.creature_index(p))
        entry = next(e for e in pal if e["resref"] == "goblin_shaman")
        self.assertEqual(entry["kind"], "base")
        self.assertTrue(entry["name"])
        plan = {"id": "mined_c", "area": "bandit_cave", "objects": [
            {"kind": "creature", "resref": "goblin_shaman", "x": 40.0, "y": 40.0, "facing": 90}]}
        cs = CampBuilder(p, areas).build(plan)
        git = cs.load("git", "bandit_cave")
        placed = [i for k, i in I.plan_instances(git, "mined_c")]
        self.assertEqual([G.get(i, "TemplateResRef") for i in placed], ["goblin_shaman"])
        self.assertEqual(G.vars_of(placed[0]), {"studio_plan": "mined_c"})   # no instance-specific vars leaked
        self.assertEqual((G.get(placed[0], "XPosition"), G.get(placed[0], "YPosition")), (40.0, 40.0))
        with self.assertRaises(PlanError):
            CampBuilder(p, areas).build({**plan, "objects": [{"kind": "creature", "resref": "never_placed_zz", "x": 40, "y": 40}]})
