#!/usr/bin/env python3
"""Tests for editing one already-placed creature instance directly, in
bin/nwn-area-editor: the Areas page's "Edit placed creatures" action lists an
area's Creature List entries, and each one opens a form that edits that
instance's own struct in the area's .git.json - independent of its blueprint
and of any other placed copy of the same blueprint.

Run all tests:
    python3 tests/test_edit_placed_creature.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader(
    "nwn_area_editor_under_test__test_edit_placed_creature", str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_utc(tag, **byte_fields):
    d = {
        "__data_type": "UTC",
        "Tag": _field("cexostring", tag),
        "FirstName": _field("cexolocstring", {"0": tag}),
        "LastName": _field("cexolocstring", {"0": ""}),
    }
    for name, value in byte_fields.items():
        d[name] = _field("byte", value)
    return d


def make_git_json(creatures=()):
    return {"__data_type": "GIT", "Creature List": _field("list", list(creatures))}


def make_placed_creature(template, carried=None, equip=None, **byte_fields):
    d = {
        "__struct_id": 4,
        "Tag": _field("cexostring", template + "_inst"),
        "TemplateResRef": _field("resref", template),
        "FirstName": _field("cexolocstring", {"0": template}),
        "LastName": _field("cexolocstring", {"0": ""}),
    }
    for name, value in byte_fields.items():
        d[name] = _field("byte", value)
    if carried is not None:
        d["ItemList"] = _field("list", carried)
    if equip is not None:
        d["Equip_ItemList"] = _field("list", equip)
    return d


def make_carried(resref, dropable=None):
    d = {"__struct_id": 0, "InventoryRes": _field("resref", resref)}
    if dropable is not None:
        d["Dropable"] = _field("byte", dropable)
    return d


class DirectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_instance_edit_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_area(self, res, git_data):
        with open(os.path.join(self.tmp, res + ".are.json"), "w") as fh:
            json.dump({"__data_type": "ARE"}, fh)
        with open(os.path.join(self.tmp, res + ".git.json"), "w") as fh:
            json.dump(git_data, fh)

    def _load_git(self, res):
        with open(os.path.join(self.tmp, res + ".git.json")) as fh:
            return json.load(fh)

    def test_render_placed_creatures_form_lists_instances_with_edit_links(self):
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc", Lootable=1),
        ]))
        html = CONSOLE.render_placed_creatures_form(self.tmp, self.tmp, ["myarea"])
        self.assertIn("nw_orc", html)
        self.assertIn("/areas/creature?area=myarea&idx=0", html)

    def test_render_placed_creatures_form_empty_area_shows_note(self):
        self._write_area("emptyarea", make_git_json(creatures=[]))
        html = CONSOLE.render_placed_creatures_form(self.tmp, self.tmp, ["emptyarea"])
        self.assertIn("No creatures found", html)

    def test_render_instance_form_prefills_current_values(self):
        entry = make_placed_creature("nw_orc", Plot=1, Lootable=0)
        entry["ScriptDeath"] = _field("resref", "existing_death")
        entry["DecayTime"] = _field("dword", 12345)
        html = CONSOLE.render_instance_form(self.tmp, "myarea", 0, entry)
        self.assertIn("value='existing_death'", html)
        self.assertIn("value='12345'", html)
        self.assertIn("<option value='0' selected>No</option>", html)  # Lootable
        self.assertIn("<option value='1' selected>Yes</option>", html)  # Plot

    def test_apply_toggles_lootable_on_this_instance_only(self):
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc", Lootable=1),
            make_placed_creature("nw_orc", Lootable=1),
        ]))
        touched = CONSOLE.apply_instance_settings(
            self.tmp, "myarea", 0, {"Lootable": ["0"]})
        self.assertTrue(touched)
        entries = self._load_git("myarea")["Creature List"]["value"]
        self.assertEqual(entries[0]["Lootable"]["value"], 0)
        self.assertEqual(entries[1]["Lootable"]["value"], 1)  # untouched

    def test_apply_does_not_touch_blueprint_file(self):
        with open(os.path.join(self.tmp, "nw_orc.utc.json"), "w") as fh:
            json.dump(make_utc("orc", Lootable=1), fh)
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc", Lootable=1),
        ]))
        CONSOLE.apply_instance_settings(self.tmp, "myarea", 0, {"Lootable": ["0"]})
        with open(os.path.join(self.tmp, "nw_orc.utc.json")) as fh:
            blueprint = json.load(fh)
        self.assertEqual(blueprint["Lootable"]["value"], 1)  # unchanged

    def test_apply_sets_flags_and_decay_time(self):
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc", Plot=0, NoPermDeath=0, IsImmortal=0),
        ]))
        CONSOLE.apply_instance_settings(self.tmp, "myarea", 0, {
            "Plot": ["1"], "NoPermDeath": ["1"], "IsImmortal": ["1"],
            "DecayTime": ["30000"],
        })
        entry = self._load_git("myarea")["Creature List"]["value"][0]
        self.assertEqual(entry["Plot"]["value"], 1)
        self.assertEqual(entry["NoPermDeath"]["value"], 1)
        self.assertEqual(entry["IsImmortal"]["value"], 1)
        self.assertEqual(entry["DecayTime"]["value"], 30000)

    def test_apply_blank_decay_time_leaves_unchanged(self):
        entry = make_placed_creature("nw_orc")
        entry["DecayTime"] = _field("dword", 5000)
        self._write_area("myarea", make_git_json(creatures=[entry]))
        touched = CONSOLE.apply_instance_settings(
            self.tmp, "myarea", 0, {"DecayTime": [""]})
        self.assertFalse(touched)
        self.assertEqual(self._load_git("myarea")["Creature List"]["value"][0]
                          ["DecayTime"]["value"], 5000)

    def test_apply_sets_script_field_directly_including_blank(self):
        entry = make_placed_creature("nw_orc")
        entry["ScriptDeath"] = _field("resref", "old_death")
        self._write_area("myarea", make_git_json(creatures=[entry]))
        CONSOLE.apply_instance_settings(
            self.tmp, "myarea", 0, {"ScriptDeath": [""]})
        self.assertEqual(self._load_git("myarea")["Creature List"]["value"][0]
                          ["ScriptDeath"]["value"], "")

    def test_apply_toggles_carried_item_dropable_on_this_instance(self):
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc",
                                  carried=[make_carried("nw_it_gem001", dropable=1)]),
        ]))
        touched = CONSOLE.apply_instance_settings(
            self.tmp, "myarea", 0, {"dropable_carried_present": ["1"]})
        self.assertTrue(touched)
        entry = self._load_git("myarea")["Creature List"]["value"][0]
        self.assertEqual(entry["ItemList"]["value"][0]["Dropable"]["value"], 0)

    def test_apply_out_of_range_index_returns_false(self):
        self._write_area("myarea", make_git_json(creatures=[
            make_placed_creature("nw_orc"),
        ]))
        touched = CONSOLE.apply_instance_settings(
            self.tmp, "myarea", 5, {"Lootable": ["0"]})
        self.assertFalse(touched)


class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real edit_creatures -> instance form -> apply routes
    over a socket, matching the convention in test_remove_objects.py."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_instance_http_test_")
        with open(os.path.join(cls.tmp, "nw_orc.utc.json"), "w") as fh:
            json.dump(make_utc("orc", Lootable=1), fh)
        with open(os.path.join(cls.tmp, "httparea.are.json"), "w") as fh:
            json.dump({"__data_type": "ARE"}, fh)
        with open(os.path.join(cls.tmp, "httparea.git.json"), "w") as fh:
            json.dump(make_git_json(creatures=[
                make_placed_creature(
                    "nw_orc", Lootable=1,
                    carried=[make_carried("nw_it_gem001", dropable=1)]),
            ]), fh)

        cls.port = 18394
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
        return urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (self.port, path), timeout=5).read().decode()

    def _post(self, path, data):
        body = urllib.parse.urlencode(data, doseq=True).encode()
        return urllib.request.urlopen(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body, timeout=5).read().decode()

    def test_full_instance_edit_round_trip(self):
        listing = self._get("/areas/edit?action=edit_creatures&res=httparea")
        self.assertIn("idx=0", listing)

        form_html = self._get("/areas/creature?area=httparea&idx=0")
        self.assertIn("Editing placed creature", form_html)

        self._post("/areas/creature/apply", {
            "area": ["httparea"], "idx": ["0"],
            "Lootable": ["0"],
            "dropable_carried_present": ["1"],
        })

        with open(os.path.join(self.tmp, "httparea.git.json")) as fh:
            entry = json.load(fh)["Creature List"]["value"][0]
        self.assertEqual(entry["Lootable"]["value"], 0)
        self.assertEqual(entry["ItemList"]["value"][0]["Dropable"]["value"], 0)

        with open(os.path.join(self.tmp, "nw_orc.utc.json")) as fh:
            blueprint = json.load(fh)
        self.assertEqual(blueprint["Lootable"]["value"], 1)  # blueprint untouched

    def test_unknown_instance_returns_404(self):
        try:
            self._get("/areas/creature?area=httparea&idx=99")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
