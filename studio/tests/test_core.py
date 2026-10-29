"""Core layer tests: gffjson, instances, changeset, validate."""

from __future__ import annotations

import glob
import math
import random
import subprocess
import unittest

from tests.fixture import HAVE_TFN, REAL_TFN, MiniTfnCase, git_init_commit  # noqa: F401  (sets sys.path)

from tfnstudio import gffjson as G
from tfnstudio import instances as I
from tfnstudio import validate as V
from tfnstudio.changeset import ChangeSet, apply_changeset, undo_applied


class FloatFormatTests(unittest.TestCase):
    def test_matches_nwn_gff_style(self):
        self.assertEqual(G.fmt_float(65.2057), "65.20569999999999")  # %.16g, round-trips
        self.assertEqual(G.fmt_float(66.0097), "66.0097")
        self.assertEqual(G.fmt_float(7.0), "7.0")
        self.assertEqual(G.fmt_float(-0.0), "-0.0")
        self.assertEqual(G.fmt_float(0.1), "0.1")
        self.assertEqual(G.fmt_float(1e-05), "1e-05")

    def test_dumps_shape(self):
        obj = {"a": {"type": "int", "value": 1}, "l": [], "d": {}, "n": [1, 2], "s": "é\n"}
        self.assertEqual(G.dumps(obj),
                         '{\n  "a": {\n    "type": "int",\n    "value": 1\n  },\n  "l": [],\n  "d": {},\n'
                         '  "n": [\n    1,\n    2\n  ],\n  "s": "é\\n"\n}\n')


@unittest.skipUnless(HAVE_TFN, "real TFN checkout not found")
class RealFileRoundTrip(unittest.TestCase):
    def test_sample_of_real_files_is_byte_identical(self):
        files = glob.glob(str(REAL_TFN / "src" / "*" / "*.json"))
        random.Random(11).shuffle(files)
        bad = []
        for f in files[:120]:
            with open(f, encoding="utf-8") as fh:
                raw = fh.read()
            if G.dumps(G.loads(raw)) != raw:
                bad.append(f)
        # two known hand-edited files contain literal tabs; random sample should virtually never hit them
        self.assertLessEqual(len(bad), 1, bad)


class VarTableTests(unittest.TestCase):
    def test_set_get_del(self):
        obj = {}
        G.set_var(obj, "cr", 7)
        G.set_var(obj, "random1", "wolf")
        G.set_var(obj, "boss", 1.5)
        self.assertEqual(G.vars_of(obj), {"cr": 7, "random1": "wolf", "boss": 1.5})
        G.set_var(obj, "cr", 9)  # replace, not append
        self.assertEqual(len(obj["VarTable"]["value"]), 3)
        self.assertEqual(G.get_var(obj, "cr"), 9)
        self.assertEqual(obj["VarTable"]["value"][0]["Type"]["value"], G.VAR_INT)
        self.assertEqual(obj["VarTable"]["value"][1]["Type"]["value"], G.VAR_STRING)
        self.assertTrue(G.del_var(obj, "cr"))
        self.assertFalse(G.del_var(obj, "nope"))
        self.assertEqual(G.del_vars_with_prefix(obj, "rand"), 1)


class InstanceTests(MiniTfnCase):
    def test_creature_instance_shape(self):
        p = self.project()
        bp = p.read("utc", "bandit")
        inst = I.creature_instance(bp, 10.123456, 20.0, 1.5, facing=90, plan="camp_a")
        self.assertEqual(inst["__struct_id"], 4)
        self.assertNotIn("Comment", inst)
        self.assertNotIn("PaletteID", inst)
        self.assertNotIn("__data_type", inst)
        self.assertEqual(G.get(inst, "XPosition"), 10.1235)
        self.assertEqual((G.get(inst, "XOrientation"), G.get(inst, "YOrientation")), (0.0, 1.0))
        self.assertEqual(G.get_var(inst, I.PLAN_VAR), "camp_a")
        keys = [k for k in inst if k != "__struct_id"]
        self.assertEqual(keys, sorted(keys, key=str.lower))
        self.assertEqual(next(iter(inst)), "__struct_id")

    def test_empty_vartable_is_omitted(self):
        p = self.project()
        bp = p.read("utc", "bandit")
        bp["VarTable"] = G.list_()  # blueprint with an explicitly empty table
        inst = I.creature_instance(bp, 5, 5, 0)
        self.assertNotIn("VarTable", inst)
        inst2 = I.creature_instance(bp, 5, 5, 0, plan="x")
        self.assertEqual(G.get_var(inst2, I.PLAN_VAR), "x")

    def test_marker_keeps_its_own_vars(self):
        p = self.project()
        inst = I.creature_instance(p.read("utc", "random1"), 5, 5, 0, plan="x")
        self.assertEqual(G.get(inst, "TemplateResRef"), "random1")
        self.assertEqual(G.get_var(inst, "random_spawn"), 1)
        self.assertEqual(G.get_var(inst, I.PLAN_VAR), "x")

    def test_blueprint_vartable_copied(self):
        p = self.project()
        bp = p.read("utc", "kurth")
        inst = I.creature_instance(bp, 5, 5, 0)
        self.assertEqual(G.get_var(inst, "quest1"), "02_q_captain_kurth")

    def test_placeable_from_utp(self):
        p = self.project()
        bp = p.read("utp", "treas_barrel")
        inst = I.placeable_instance(bp, 12.5, 7.25, 0.5, facing=180)
        self.assertEqual(inst["__struct_id"], 9)
        self.assertEqual((G.get(inst, "X"), G.get(inst, "Y"), G.get(inst, "Z")), (12.5, 7.25, 0.5))
        self.assertAlmostEqual(G.get(inst, "Bearing"), 3.1416, places=4)
        self.assertNotIn("PaletteID", inst)

    def test_orientation_and_bearing(self):
        self.assertEqual(I.orientation(0), (1.0, 0.0))
        self.assertEqual(I.orientation(90), (0.0, 1.0))
        x, y = I.orientation(45)
        self.assertAlmostEqual(math.hypot(x, y), 1.0, places=5)
        self.assertAlmostEqual(I.bearing(270), -1.5708, places=4)

    def test_infer_z(self):
        p = self.project()
        git = p.read("git", "bandit_cave")
        near = I.instances(git, "creature")[2]  # hakt at z=3.0
        x, y, z = I.position_of("creature", near)
        zz, how = I.infer_z(git, x + 0.5, y, radius=5)
        self.assertEqual((zz, how), (z, "near"))
        zz, how = I.infer_z(git, 500, 500)
        self.assertEqual(how, "area_median")
        self.assertEqual(I.infer_z({"Creature List": G.list_()}, 1, 1), (0.0, "default"))

    def test_plan_removal(self):
        p = self.project()
        git = p.read("git", "bandit_cave")
        before = len(I.instances(git, "creature"))
        I.add_instance(git, "creature", I.creature_instance(p.read("utc", "bandit"), 5, 5, 0, plan="pp"))
        I.add_instance(git, "placeable", I.placeable_instance(p.read("utp", "treas_barrel"), 6, 6, 0, plan="pp"))
        self.assertEqual(len(list(I.plan_instances(git, "pp"))), 2)
        self.assertEqual(I.remove_plan_instances(git, "pp"), 2)
        self.assertEqual(len(I.instances(git, "creature")), before)


class ChangeSetTests(MiniTfnCase):
    def _cs(self, p):
        return ChangeSet(p, "unit test", "misc")

    def test_stage_diff_apply_undo(self):
        p = self.project()
        cs = self._cs(p)
        git = cs.load("git", "bandit_cave")
        G.set_var(git, "cr", 8)
        fc = cs.save("git", "bandit_cave", git)
        self.assertEqual(fc.action, "modify")
        self.assertIn('"value": 8', cs.diff())
        cs.save_nss("zz_test_script", "void main(){}\n")
        self.assertEqual(cs.files["src/nss/zz_test_script.nss"].action, "create")

        orig = (self.root / "src/git/bandit_cave.git.json").read_text()
        res = apply_changeset(p, cs)
        self.assertTrue(res.ok, res.problems)
        self.assertIn('"value": 8', (self.root / "src/git/bandit_cave.git.json").read_text())
        self.assertTrue((self.root / "src/nss/zz_test_script.nss").is_file())

        undone = undo_applied(p, cs.id)
        self.assertTrue(undone.ok, undone.problems)
        self.assertEqual((self.root / "src/git/bandit_cave.git.json").read_text(), orig)
        self.assertFalse((self.root / "src/nss/zz_test_script.nss").exists())

    def test_persist_and_reload(self):
        p = self.project()
        cs = self._cs(p)
        cs.save_nss("zz_persist", "void main(){}\n")
        cs.persist()
        again = ChangeSet.load_saved(p, cs.id)
        self.assertEqual(again.files["src/nss/zz_persist.nss"].new_text, "void main(){}\n")

    def test_conflict_detected(self):
        p = self.project()
        cs = self._cs(p)
        jrl = cs.load("jrl", "module")
        jrl["Categories"]["value"][0]["Priority"]["value"] = 3
        cs.save("jrl", "module", jrl)
        target = self.root / "src/jrl/module.jrl.json"
        saved = target.read_text()
        try:
            target.write_text(saved.replace('"Comment"', '"Comment"', 1) + " ")  # someone else edits
            res = apply_changeset(p, cs, dry_run=True)
            self.assertFalse(res.ok)
            self.assertTrue(any("changed on disk" in x for x in res.problems), res.problems)
        finally:
            target.write_text(saved)

    def test_refuses_paths_outside_src(self):
        p = self.project()
        cs = self._cs(p)
        with self.assertRaises(Exception):
            cs.stage_text("../evil.txt", "x")
        with self.assertRaises(Exception):
            cs.stage_text("tools/evil.txt", "x")

    def test_dirty_guard(self):
        p = self.project()
        git_init_commit(self.root)
        target = self.root / "src/nss/dlg_q_adv.nss"
        original = target.read_text()
        try:
            target.write_text(original + "\n// local edit\n")
            cs = self._cs(p)
            cs.stage_text("src/nss/dlg_q_adv.nss", original + "\n// generated\n")
            res = apply_changeset(p, cs)
            self.assertFalse(res.ok)
            self.assertTrue(any("uncommitted" in x for x in res.problems), res.problems)
            forced = apply_changeset(p, cs, allow_dirty=True, force_conflicts=True)
            self.assertTrue(forced.ok, forced.problems)
        finally:
            target.write_text(original)


class ValidateTests(MiniTfnCase):
    def test_real_git_roundtrip_ok(self):
        p = self.project()
        cs = ChangeSet(p, "rt", "misc")
        git = cs.load("git", "bandit_cave")
        G.set_var(git, "cr", 7)
        cs.save("git", "bandit_cave", git)
        issues = V.validate_changeset(p, cs, compile_scripts=False)
        errors = [i for i in issues if i.level == "error"]
        self.assertEqual(errors, [], errors)

    def test_git_lint_missing_marker_and_ute(self):
        p = self.project()
        cs = ChangeSet(p, "lint", "camp")
        git = cs.load("git", "bandit_cave")
        G.set_var(git, "random3", "no_such_ute")
        G.set_var(git, "random3_spawns", 0)
        cs.save("git", "bandit_cave", git)
        msgs = [i.message for i in V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)
                if i.level == "error"]
        self.assertTrue(any("no such encounter blueprint" in m for m in msgs), msgs)
        self.assertTrue(any("positive int" in m for m in msgs), msgs)
        self.assertTrue(any("no `random3` marker" in m for m in msgs), msgs)

    def test_out_of_bounds_generated_instance(self):
        p = self.project()
        cs = ChangeSet(p, "oob", "camp")
        git = cs.load("git", "bandit_cave")
        I.add_instance(git, "placeable", I.placeable_instance(p.read("utp", "treas_barrel"), 9999, 5, 0, plan="oob"))
        cs.save("git", "bandit_cave", git)
        issues = V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)
        self.assertTrue(any("outside the area bounds" in i.message for i in issues))

    def test_jrl_lint(self):
        p = self.project()
        cs = ChangeSet(p, "jrl", "quest")
        jrl = cs.load("jrl", "module")
        cat = G.clone(jrl["Categories"]["value"][0])
        cat["Tag"]["value"] = "q_" + "x" * 30
        cat["EntryList"]["value"] = []
        jrl["Categories"]["value"].append(cat)
        cs.save("jrl", "module", jrl)
        msgs = [i.message for i in V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)]
        self.assertTrue(any("longer than 27" in m for m in msgs), msgs)
        self.assertTrue(any("no journal entries" in m for m in msgs), msgs)

    def test_script_compile_ok_and_error(self):
        p = self.project()
        if p.tool("nwnsc") is None:
            self.skipTest("nwnsc not available")
        self.assertEqual(V.compile_script(p, "zz_ok", '#include "inc_quest"\nvoid main(){}\n'), [])
        errs = V.compile_script(p, "zz_bad", "void main(){ NoSuchFunction(); }\n")
        self.assertTrue(errs and "NSC1020" in errs[0], errs)

    def test_ute_lint_all_unique(self):
        p = self.project()
        cs = ChangeSet(p, "ute", "ute")
        ute = cs.load("ute", "bandit_moderate")
        for c in ute["CreatureList"]["value"]:
            c["SingleSpawn"]["value"] = 1
        cs.save("ute", "bandit_moderate", ute)
        msgs = [i.message for i in V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)]
        self.assertTrue(any("common pool is empty" in m for m in msgs), msgs)


class FirstMismatchTests(unittest.TestCase):
    def test_float32_tolerance(self):
        a = {"x": {"type": "float", "value": 64.1549}}
        b = {"x": {"type": "float", "value": 64.15489959716797}}
        self.assertIsNone(V.first_mismatch(a, b))
        c = {"x": {"type": "double", "value": 64.1549}}
        d = {"x": {"type": "double", "value": 64.15489959716797}}
        self.assertIsNotNone(V.first_mismatch(c, d))

    def test_reports_lost_key(self):
        self.assertIn("lost", V.first_mismatch({"a": 1}, {}))


if __name__ == "__main__":
    unittest.main()
