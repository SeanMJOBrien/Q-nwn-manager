#!/usr/bin/env python3
"""Tests for the "Lootable" Yes/No toggle in bin/nwn-area-editor's creature
blueprint editor and listing page.

Exercises apply_char_edits / render_char_form / render_creatures directly
(loaded via SourceFileLoader, since nwn-area-editor has no .py extension)
against synthetic .utc.json fixtures built in-process.

Run all tests:
    python3 tests/test_creature_lootable.py
"""
import json
import os
import shutil
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader(
    "nwn_area_editor_under_test__test_creature_lootable", str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_utc(tag, first="Guard", last="", lootable=None):
    d = {
        "__data_type": "UTC",
        "Tag": _field("cexostring", tag),
        "FirstName": _field("cexolocstring", {"0": first}),
        "LastName": _field("cexolocstring", {"0": last}),
    }
    if lootable is not None:
        d["Lootable"] = _field("byte", lootable)
    return d


class LootableEditTests(unittest.TestCase):
    def test_toggle_off_sets_byte_field(self):
        d = make_utc("guard1", lootable=1)
        touched = CONSOLE.apply_char_edits(d, {"Lootable": ["0"]})
        self.assertTrue(touched)
        self.assertEqual(d["Lootable"]["value"], 0)
        self.assertEqual(d["Lootable"]["type"], "byte")

    def test_toggle_on_from_off(self):
        d = make_utc("guard2", lootable=0)
        touched = CONSOLE.apply_char_edits(d, {"Lootable": ["1"]})
        self.assertTrue(touched)
        self.assertEqual(d["Lootable"]["value"], 1)

    def test_toggle_to_same_value_is_a_no_op(self):
        d = make_utc("guard3", lootable=1)
        touched = CONSOLE.apply_char_edits(d, {"Lootable": ["1"]})
        self.assertFalse(touched)

    def test_missing_field_defaults_to_lootable_yes(self):
        d = make_utc("guard4")  # no Lootable field at all
        touched = CONSOLE.apply_char_edits(d, {"Lootable": ["1"]})
        self.assertFalse(touched)  # setting to the implied default is a no-op
        touched = CONSOLE.apply_char_edits(d, {"Lootable": ["0"]})
        self.assertTrue(touched)
        self.assertEqual(d["Lootable"]["value"], 0)

    def test_unspecified_form_field_leaves_lootable_unchanged(self):
        d = make_utc("guard5", lootable=0)
        touched = CONSOLE.apply_char_edits(d, {})
        self.assertFalse(touched)
        self.assertEqual(d["Lootable"]["value"], 0)

    def test_render_char_form_selects_yes_when_lootable(self):
        d = make_utc("guard6", lootable=1)
        html = CONSOLE.render_char_form(d, "/creature/apply", "", ".")
        self.assertIn("<option value='1' selected>Yes</option>", html)
        self.assertIn("<option value='0'>No</option>", html)

    def test_render_char_form_selects_no_when_not_lootable(self):
        d = make_utc("guard7", lootable=0)
        html = CONSOLE.render_char_form(d, "/creature/apply", "", ".")
        self.assertIn("<option value='0' selected>No</option>", html)
        self.assertIn("<option value='1'>Yes</option>", html)

    def test_render_char_form_defaults_to_yes_when_field_absent(self):
        d = make_utc("guard8")
        html = CONSOLE.render_char_form(d, "/creature/apply", "", ".")
        self.assertIn("<option value='1' selected>Yes</option>", html)


class CreaturesListLootableColumnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_lootable_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_utc(self, res, data):
        with open(os.path.join(self.tmp, res + ".utc.json"), "w") as fh:
            json.dump(data, fh)

    def test_list_shows_yes_and_no(self):
        self._write_utc("nw_guard", make_utc("guard1", lootable=1))
        self._write_utc("nw_ghost", make_utc("ghost1", lootable=0))
        html = CONSOLE.render_creatures(self.tmp, {})
        self.assertIn("Lootable", html)
        rows = html.split("<tr>")
        guard_row = next(r for r in rows if "nw_guard" in r)
        ghost_row = next(r for r in rows if "nw_ghost" in r)
        self.assertIn("<td>Yes</td>", guard_row)
        self.assertIn("<td>No</td>", ghost_row)

    def test_list_defaults_to_yes_when_field_absent(self):
        self._write_utc("nw_villager", make_utc("villager1"))
        html = CONSOLE.render_creatures(self.tmp, {})
        rows = html.split("<tr>")
        row = next(r for r in rows if "nw_villager" in r)
        self.assertIn("<td>Yes</td>", row)


if __name__ == "__main__":
    unittest.main()
