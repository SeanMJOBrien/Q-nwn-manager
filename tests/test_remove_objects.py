#!/usr/bin/env python3
"""Tests for the "Remove objects" area bulk-editor in bin/nwn-area-editor.

Exercises render_remove_objects_form / apply_remove_objects directly (loaded
via SourceFileLoader, since nwn-area-editor has no .py extension) against
synthetic .git.json fixtures built in-process - no external module/repo
required - plus one live HTTP round-trip through the real console routes to
catch routing/dispatch mistakes the direct-call tests can't see.

Run all tests:
    python3 tests/test_remove_objects.py

Run one case:
    python3 -m unittest tests.test_remove_objects.RemoveObjectsTests.test_nested_inventory_removal_leaves_parent_intact
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader(
    "nwn_area_editor_under_test__test_remove_objects", str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


# --- Fixture builders (mirror the real GFF-JSON shape nwn_gff produces) -----

def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_git_json(placeables=(), creatures=(), items=()):
    return {
        "__data_type": "GIT",
        "Creature List": _field("list", list(creatures)),
        "Placeable List": _field("list", list(placeables)),
        "List": _field("list", list(items)),
        "Door List": _field("list", []),
        "TriggerList": _field("list", []),
        "WaypointList": _field("list", []),
        "SoundList": _field("list", []),
        "StoreList": _field("list", []),
        "Encounter List": _field("list", []),
    }


def make_placeable(tag, resref, x=0.0, y=0.0, item_list=None):
    d = {
        "__struct_id": 9,
        "Tag": _field("cexostring", tag),
        "TemplateResRef": _field("resref", resref),
        "X": _field("float", x),
        "Y": _field("float", y),
        "Z": _field("float", 0.0),
        "HasInventory": _field("byte", 1 if item_list else 0),
    }
    if item_list is not None:
        d["ItemList"] = _field("list", item_list)
    return d


def make_creature(tag, resref, x=0.0, y=0.0, equip=None, carried=None):
    d = {
        "__struct_id": 4,
        "Tag": _field("cexostring", tag),
        "TemplateResRef": _field("resref", resref),
        "FirstName": _field("cexolocstring", {"0": tag}),
        "LastName": _field("cexolocstring", {"0": ""}),
        "XPosition": _field("float", x),
        "YPosition": _field("float", y),
        "ZPosition": _field("float", 0.0),
    }
    if equip is not None:
        d["Equip_ItemList"] = _field("list", equip)
    if carried is not None:
        d["ItemList"] = _field("list", carried)
    return d


def make_item(tag, resref, x=0.0, y=0.0, item_list=None):
    d = {
        "__struct_id": 0,
        "Tag": _field("cexostring", tag),
        "TemplateResRef": _field("resref", resref),
        "XPosition": _field("float", x),
        "YPosition": _field("float", y),
        "HasInventory": _field("byte", 1 if item_list else 0),
    }
    if item_list is not None:
        d["ItemList"] = _field("list", item_list)
    return d


def make_equipped(slot_id, resref):
    return {"__struct_id": slot_id, "EquippedRes": _field("resref", resref)}


def make_carried(resref):
    return {"__struct_id": 0, "InventoryRes": _field("resref", resref)}


# --- Direct function-level tests --------------------------------------------

class RemoveObjectsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_git(self, res, data):
        path = os.path.join(self.tmp, res + ".git.json")
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def _load_git(self, res):
        with open(os.path.join(self.tmp, res + ".git.json")) as fh:
            return json.load(fh)

    def _load_json(self, path):
        with open(path) as fh:
            return json.load(fh)

    def test_top_level_removal_placeable_creature_item(self):
        self._write_git("area_a", make_git_json(
            placeables=[make_placeable("torch1", "plc_torch"),
                        make_placeable("torch2", "plc_torch")],
            creatures=[make_creature("guard1", "nw_guard")],
            items=[make_item("potion1", "nw_it_mpotion001")],
        ))
        form = {"res": ["area_a"],
                "del": ["area_a|placeable|0", "area_a|creature|0", "area_a|item|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form)
        g = self._load_git("area_a")
        self.assertEqual(len(g["Placeable List"]["value"]), 1)
        self.assertEqual(g["Placeable List"]["value"][0]["Tag"]["value"], "torch2")
        self.assertEqual(len(g["Creature List"]["value"]), 0)
        self.assertEqual(len(g["List"]["value"]), 0)

    def test_nested_inventory_removal_leaves_parent_intact(self):
        self._write_git("area_b", make_git_json(
            placeables=[make_placeable("chest1", "plc_chest",
                                        item_list=[make_carried("nw_it_gem001"),
                                                   make_carried("nw_it_gem002")])],
            creatures=[make_creature("wiz1", "nw_wizard",
                                      equip=[make_equipped(2, "chestarmor")],
                                      carried=[make_carried("nw_it_mpotion001")])],
        ))
        form = {"res": ["area_b"],
                "del": ["area_b|placeable|0|ItemList|0",
                        "area_b|creature|0|Equip_ItemList|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form)
        g = self._load_git("area_b")
        # parent objects must still exist
        self.assertEqual(len(g["Placeable List"]["value"]), 1)
        self.assertEqual(len(g["Creature List"]["value"]), 1)
        # only the targeted nested entries are gone
        remaining_gems = g["Placeable List"]["value"][0]["ItemList"]["value"]
        self.assertEqual(len(remaining_gems), 1)
        self.assertEqual(remaining_gems[0]["InventoryRes"]["value"], "nw_it_gem002")
        self.assertEqual(len(g["Creature List"]["value"][0]["Equip_ItemList"]["value"]), 0)
        self.assertEqual(len(g["Creature List"]["value"][0]["ItemList"]["value"]), 1)

    def test_nested_inventory_removal_on_loose_item_leaves_item_intact(self):
        self._write_git("area_bag", make_git_json(
            items=[make_item("bag1", "plc_bagofholding",
                              item_list=[make_carried("nw_it_gem001"),
                                         make_carried("nw_it_gem002")])],
        ))
        form = {"res": ["area_bag"], "del": ["area_bag|item|0|ItemList|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form)
        g = self._load_git("area_bag")
        # the loose item itself must still exist
        self.assertEqual(len(g["List"]["value"]), 1)
        remaining_gems = g["List"]["value"][0]["ItemList"]["value"]
        self.assertEqual(len(remaining_gems), 1)
        self.assertEqual(remaining_gems[0]["InventoryRes"]["value"], "nw_it_gem002")

    def test_render_shows_loose_item_nested_inventory_row(self):
        self._write_git("area_bag2", make_git_json(
            items=[make_item("bag1", "plc_bagofholding",
                              item_list=[make_carried("nw_it_gem001")])],
        ))
        html = CONSOLE.render_remove_objects_form(self.tmp, self.tmp, ["area_bag2"])
        self.assertIn("area_bag2|item|0", html)
        self.assertIn("area_bag2|item|0|ItemList|0", html)

    def test_render_includes_filter_box_and_script(self):
        self._write_git("area_i", make_git_json(
            placeables=[make_placeable("t1", "plc_torch")]))
        html = CONSOLE.render_remove_objects_form(self.tmp, self.tmp, ["area_i"])
        self.assertIn("qnmFilterObjects", html)
        self.assertIn("type='search'", html)
        self.assertIn("table class='remove-objects'", html)

    def test_backup_created_once_and_not_clobbered(self):
        path = self._write_git("area_c", make_git_json(
            placeables=[make_placeable("t1", "plc_torch")]))
        form1 = {"res": ["area_c"], "del": ["area_c|placeable|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form1)
        bak_path = path + ".bak"
        self.assertTrue(os.path.isfile(bak_path))
        bak_first = self._load_json(bak_path)
        self.assertEqual(len(bak_first["Placeable List"]["value"]), 1)  # pre-edit state

        # A second edit round on the same resref must not overwrite the
        # original backup with this newer state.
        self._write_git("area_c", make_git_json(
            placeables=[make_placeable("t2", "plc_torch"),
                        make_placeable("t3", "plc_torch")]))
        form2 = {"res": ["area_c"], "del": ["area_c|placeable|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form2)
        bak_second = self._load_json(bak_path)
        self.assertEqual(len(bak_second["Placeable List"]["value"]), 1)  # unchanged

    def test_no_selection_is_a_no_op(self):
        self._write_git("area_d", make_git_json(
            placeables=[make_placeable("t1", "plc_torch")]))
        form = {"res": ["area_d"], "del": []}
        result_html = CONSOLE.apply_remove_objects(self.tmp, self.tmp, form)
        self.assertIn("Changed 0 of 1 selected", result_html)
        self.assertEqual(len(self._load_git("area_d")["Placeable List"]["value"]), 1)

    def test_multi_area_independence(self):
        self._write_git("area_e", make_git_json(placeables=[make_placeable("t1", "plc_torch")]))
        self._write_git("area_f", make_git_json(placeables=[make_placeable("t2", "plc_torch")]))
        form = {"res": ["area_e", "area_f"], "del": ["area_e|placeable|0"]}
        CONSOLE.apply_remove_objects(self.tmp, self.tmp, form)
        self.assertEqual(len(self._load_git("area_e")["Placeable List"]["value"]), 0)
        self.assertEqual(len(self._load_git("area_f")["Placeable List"]["value"]), 1)  # untouched

    def test_render_lists_all_categories_and_nested_rows(self):
        self._write_git("area_g", make_git_json(
            placeables=[make_placeable("chest1", "plc_chest",
                                        item_list=[make_carried("nw_it_gem001")])],
            creatures=[make_creature("guard1", "nw_guard")],
            items=[make_item("potion1", "nw_it_mpotion001")],
        ))
        html = CONSOLE.render_remove_objects_form(self.tmp, self.tmp, ["area_g"])
        self.assertIn("area_g|placeable|0", html)
        self.assertIn("area_g|creature|0", html)
        self.assertIn("area_g|item|0", html)
        self.assertIn("area_g|placeable|0|ItemList|0", html)

    def test_render_with_no_objects_shows_empty_message(self):
        self._write_git("area_h", make_git_json())
        html = CONSOLE.render_remove_objects_form(self.tmp, self.tmp, ["area_h"])
        self.assertIn("No placeables, creatures, or loose items found", html)


# --- One live end-to-end HTTP pass -------------------------------------------

class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real button -> GET form -> POST apply routes over an
    actual socket, not just the underlying functions - this is what would
    catch a routing/dispatch typo the direct tests above can't see."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_http_test_")
        res = "httparea"
        git = make_git_json(placeables=[make_placeable("t1", "plc_torch")])
        with open(os.path.join(cls.tmp, res + ".git.json"), "w") as fh:
            json.dump(git, fh)
        are = {"__data_type": "ARE", "Tag": _field("cexostring", res),
               "Name": _field("cexolocstring", {"0": "Test Area"}),
               "Tileset": _field("resref", "tst"), "Flags": _field("dword", 1)}
        with open(os.path.join(cls.tmp, res + ".are.json"), "w") as fh:
            json.dump(are, fh)

        cls.port = 18391
        cls._old_argv = sys.argv
        sys.argv = ["nwn-area-editor", "--dir", cls.tmp, "--git-dir", cls.tmp,
                    "--gic-dir", cls.tmp, "--host", "127.0.0.1", "--port", str(cls.port)]
        cls.server_thread = threading.Thread(target=CONSOLE.main, daemon=True)
        cls.server_thread.start()

        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/areas" % cls.port, timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("test console server did not start in time")

    @classmethod
    def tearDownClass(cls):
        sys.argv = cls._old_argv
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:%d/shutdown" % cls.port, data=b"", timeout=2)
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _get(self, path):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        return urllib.request.urlopen(url, timeout=5).read().decode()

    def _post(self, path, data):
        url = "http://127.0.0.1:%d%s" % (self.port, path)
        body = urllib.parse.urlencode(data, doseq=True).encode()
        return urllib.request.urlopen(url, data=body, timeout=5).read().decode()

    def test_full_http_round_trip(self):
        listing = self._get("/areas")
        self.assertIn("Remove objects", listing)

        form_html = self._get("/areas/edit?action=remove_objects&res=httparea")
        self.assertIn("httparea|placeable|0", form_html)

        result_html = self._post(
            "/areas/objects/apply",
            {"res": ["httparea"], "del": ["httparea|placeable|0"]})
        self.assertIn("Changed 1 of 1 selected", result_html)

        with open(os.path.join(self.tmp, "httparea.git.json")) as fh:
            g = json.load(fh)
        self.assertEqual(len(g["Placeable List"]["value"]), 0)


if __name__ == "__main__":
    unittest.main()
