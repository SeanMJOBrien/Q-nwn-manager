#!/usr/bin/env python3
"""Tests for the creature editor's Equipment & Inventory section in
bin/nwn-area-editor: resolving an equipped/carried item's display name from
its .uti blueprint, and the per-item Dropable Yes/No toggle.

Run all tests:
    python3 tests/test_creature_equipment.py
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
    "nwn_area_editor_under_test", str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_utc(tag, equip=None, carried=None):
    d = {
        "__data_type": "UTC",
        "Tag": _field("cexostring", tag),
        "FirstName": _field("cexolocstring", {"0": tag}),
        "LastName": _field("cexolocstring", {"0": ""}),
    }
    if equip is not None:
        d["Equip_ItemList"] = _field("list", equip)
    if carried is not None:
        d["ItemList"] = _field("list", carried)
    return d


def make_equipped(slot_id, resref, name=None, dropable=None):
    d = {"__struct_id": slot_id, "EquippedRes": _field("resref", resref)}
    if name is not None:
        d["LocalizedName"] = _field("cexolocstring", {"0": name})
    if dropable is not None:
        d["Dropable"] = _field("byte", dropable)
    return d


def make_carried(resref, name=None, dropable=None):
    d = {"__struct_id": 0, "InventoryRes": _field("resref", resref)}
    if name is not None:
        d["LocalizedName"] = _field("cexolocstring", {"0": name})
    if dropable is not None:
        d["Dropable"] = _field("byte", dropable)
    return d


def make_uti(name):
    return {
        "__data_type": "UTI",
        "LocalizedName": _field("cexolocstring", {"0": name}),
    }


class ItemNameResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_equip_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_uti(self, res, data):
        with open(os.path.join(self.tmp, res + ".uti.json"), "w") as fh:
            json.dump(data, fh)

    def test_carried_item_name_resolved_from_blueprint_when_entry_has_none(self):
        self._write_uti("nw_it_gem001", make_uti("Ruby"))
        item = make_carried("nw_it_gem001")
        self.assertEqual(
            CONSOLE.resolved_item_name(self.tmp, item, "nw_it_gem001"), "Ruby")

    def test_inline_name_on_entry_wins_over_blueprint(self):
        self._write_uti("nw_it_gem001", make_uti("Ruby"))
        item = make_carried("nw_it_gem001", name="Cursed Ruby")
        self.assertEqual(
            CONSOLE.resolved_item_name(self.tmp, item, "nw_it_gem001"),
            "Cursed Ruby")

    def test_missing_blueprint_falls_back_to_empty_name(self):
        item = make_carried("nw_it_nonexistent")
        self.assertEqual(
            CONSOLE.resolved_item_name(self.tmp, item, "nw_it_nonexistent"), "")

    def test_render_equipment_shows_resolved_names(self):
        self._write_uti("nw_wswls001", make_uti("Longsword"))
        self._write_uti("nw_it_mpotion001", make_uti("Potion of Healing"))
        d = make_utc("guard1",
                     equip=[make_equipped(16, "nw_wswls001")],
                     carried=[make_carried("nw_it_mpotion001")])
        html = CONSOLE.render_equipment(self.tmp, d)
        self.assertIn("Longsword", html)
        self.assertIn("Potion of Healing", html)


class DropableToggleTests(unittest.TestCase):
    def test_render_marks_dropable_checked_by_default(self):
        d = make_utc("guard1", carried=[make_carried("nw_it_gem001")])
        html = CONSOLE.render_equipment(".", d)
        self.assertIn("name='dropable_carried' value='0' checked", html)

    def test_render_marks_not_dropable_unchecked(self):
        d = make_utc("guard2", carried=[make_carried("nw_it_gem001", dropable=0)])
        html = CONSOLE.render_equipment(".", d)
        self.assertIn("name='dropable_carried' value='0'>", html)
        self.assertNotIn("name='dropable_carried' value='0' checked", html)

    def test_render_equip_checkbox_uses_original_index_not_sorted_position(self):
        # Equip_ItemList isn't sorted by slot on disk; render_equipment sorts
        # for display but the checkbox value must stay tied to the original
        # (unsorted) index, since apply_char_edits re-reads the file fresh.
        d = make_utc("guard3", equip=[
            make_equipped(32, "left_hand_item"),   # index 0, sorts second
            make_equipped(16, "right_hand_item"),  # index 1, sorts first
        ])
        html = CONSOLE.render_equipment(".", d)
        self.assertIn("name='dropable_equip' value='0'", html)
        self.assertIn("name='dropable_equip' value='1'", html)

    def test_apply_unchecking_carried_item_sets_dropable_zero(self):
        d = make_utc("guard4", carried=[
            make_carried("nw_it_gem001", dropable=1),
            make_carried("nw_it_gem002", dropable=1),
        ])
        # Only index 1 stayed checked - index 0 was unchecked (absent).
        form = {"dropable_carried_present": ["1"], "dropable_carried": ["1"]}
        touched = CONSOLE.apply_char_edits(d, form)
        self.assertTrue(touched)
        self.assertEqual(d["ItemList"]["value"][0]["Dropable"]["value"], 0)
        self.assertEqual(d["ItemList"]["value"][1]["Dropable"]["value"], 1)

    def test_apply_checking_equip_item_sets_dropable_one(self):
        d = make_utc("guard5", equip=[make_equipped(16, "sword1", dropable=0)])
        form = {"dropable_equip_present": ["1"], "dropable_equip": ["0"]}
        touched = CONSOLE.apply_char_edits(d, form)
        self.assertTrue(touched)
        self.assertEqual(d["Equip_ItemList"]["value"][0]["Dropable"]["value"], 1)

    def test_apply_without_marker_leaves_items_untouched(self):
        # Simulates a form submission that never rendered/touched the
        # Equipment section (e.g. a caller only editing other fields) - the
        # absence of the hidden marker must NOT be read as "uncheck everything".
        d = make_utc("guard6", carried=[make_carried("nw_it_gem001", dropable=1)])
        touched = CONSOLE.apply_char_edits(d, {"Tag": ["guard6"]})
        self.assertFalse(touched)
        self.assertEqual(d["ItemList"]["value"][0]["Dropable"]["value"], 1)

    def test_apply_with_no_items_and_marker_absent_is_a_no_op(self):
        d = make_utc("guard7")  # no Equip_ItemList/ItemList at all
        touched = CONSOLE.apply_char_edits(d, {})
        self.assertFalse(touched)
        self.assertNotIn("Equip_ItemList", d)
        self.assertNotIn("ItemList", d)


if __name__ == "__main__":
    unittest.main()
