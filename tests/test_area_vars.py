#!/usr/bin/env python3
"""Bulk area-variable editor (.git VarTable) in the standalone web editor.
gff_load/gff_save are swapped for plain JSON I/O.

Run: python3 tests/test_area_vars.py
"""
import json
import os
import shutil
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = SourceFileLoader(
    "nwn_web_editor_under_test__vars",
    str(REPO_ROOT / "skills" / "nwn-web-editor" / "scripts" /
        "nwn_web_editor.py")).load_module()


def var(name, type_id, gff_type, value):
    return {"__struct_id": 0,
            "Name": {"type": "cexostring", "value": name},
            "Type": {"type": "dword", "value": type_id},
            "Value": {"type": gff_type, "value": value}}


def write(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh)


def read(path):
    with open(path) as fh:
        return json.load(fh)


class AreaVarsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_vars_")
        self._orig = (WEB.gff_load, WEB.gff_save)
        WEB.gff_load = read
        WEB.gff_save = write
        write(self.p("a.git"), {"VarTable": {"type": "list", "value": [
            var("nKeep", 1, "int", 1), var("sOld", 3, "cexostring", "x")]}})
        write(self.p("b.git"), {"AreaProperties": {}})  # no VarTable yet

    def tearDown(self):
        WEB.gff_load, WEB.gff_save = self._orig
        shutil.rmtree(self.tmp)

    def p(self, name):
        return os.path.join(self.tmp, name)

    def names(self, res):
        return {n: (t, v) for n, t, v in
                WEB.area_vars(read(self.p(res + ".git")))}

    def test_set_replace_delete_across_areas(self):
        form = {"res": ["a", "b"], "delvar": ["sOld"],
                "set_name_0": ["nKeep"], "set_type_0": ["int"], "set_value_0": ["5"],
                "set_name_1": ["fRate"], "set_type_1": ["float"], "set_value_1": ["1.5"]}
        diffs, errors = WEB.apply_vars(self.tmp, form, dry_run=True)
        self.assertEqual(errors, [])
        self.assertEqual(self.names("a")["nKeep"], (1, 1))  # dry run: untouched
        WEB.apply_vars(self.tmp, form)
        a, b = self.names("a"), self.names("b")
        self.assertEqual(a, {"nKeep": (1, 5), "fRate": (2, 1.5)})
        self.assertEqual(b, {"nKeep": (1, 5), "fRate": (2, 1.5)})
        self.assertEqual(len(diffs), 5)

    def test_bad_number_and_missing_git(self):
        form = {"res": ["a", "nope"], "set_name_0": ["nX"],
                "set_type_0": ["int"], "set_value_0": ["abc"]}
        diffs, errors = WEB.apply_vars(self.tmp, form, dry_run=True)
        self.assertEqual(diffs, [])
        self.assertEqual(len(errors), 2)

    def test_object_variable_untouched(self):
        write(self.p("c.git"), {"VarTable": {"type": "list", "value": [
            var("oThing", 4, "dword", 7)]}})
        form = {"res": ["c"], "delvar": ["oThing"], "set_name_0": ["oThing"],
                "set_type_0": ["int"], "set_value_0": ["1"]}
        diffs, errors = WEB.apply_vars(self.tmp, form, dry_run=True)
        self.assertEqual(diffs, [])
        self.assertEqual(len(errors), 1)

    def test_form_renders(self):
        html = WEB.render_vars_form(self.tmp, ["a", "b"])
        self.assertIn("nKeep", html)
        self.assertIn("1 of 2", html)


if __name__ == "__main__":
    unittest.main()
