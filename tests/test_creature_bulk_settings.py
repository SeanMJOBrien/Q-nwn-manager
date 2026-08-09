#!/usr/bin/env python3
"""Tests for the Creatures page's multi-select bulk editor in
bin/nwn-area-editor: selecting more than one creature and applying scripts,
Plot, Lootable, NoPermDeath, IsImmortal, and DecayTime across all of them at
once.

Run all tests:
    python3 tests/test_creature_bulk_settings.py
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
    "nwn_area_editor_under_test__test_creature_bulk_settings", str(REPO_ROOT / "bin" / "nwn-area-editor")
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


def make_placed_creature(template, carried=None, **byte_fields):
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
    return d


def make_carried(resref, dropable=None):
    d = {"__struct_id": 0, "InventoryRes": _field("resref", resref)}
    if dropable is not None:
        d["Dropable"] = _field("byte", dropable)
    return d


class BulkSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_bulk_creature_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, res, data):
        with open(os.path.join(self.tmp, res + ".utc.json"), "w") as fh:
            json.dump(data, fh)

    def _load(self, res):
        with open(os.path.join(self.tmp, res + ".utc.json")) as fh:
            return json.load(fh)

    def _write_area(self, res, git_data):
        with open(os.path.join(self.tmp, res + ".are.json"), "w") as fh:
            json.dump({"__data_type": "ARE"}, fh)
        with open(os.path.join(self.tmp, res + ".git.json"), "w") as fh:
            json.dump(git_data, fh)

    def _load_git(self, res):
        with open(os.path.join(self.tmp, res + ".git.json")) as fh:
            return json.load(fh)

    def test_render_lists_creatures_page_selects_route_and_columns(self):
        self._write("nw_guard", make_utc("guard1"))
        html = CONSOLE.render_creatures(self.tmp, {})
        self.assertIn("/creatures/select", html)
        self.assertIn("name='res' value='nw_guard'", html)

    def test_apply_scripts_across_selection_blank_leaves_unchanged(self):
        self._write("nw_a", make_utc("a"))
        self._write("nw_b", make_utc("b"))
        d = self._load("nw_a")
        d["ScriptDeath"] = _field("resref", "old_death")
        self._write("nw_a", d)

        form = {"res": ["nw_a", "nw_b"], "ScriptDeath": ["nw_c2_default7"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertEqual(self._load("nw_a")["ScriptDeath"]["value"], "nw_c2_default7")
        self.assertEqual(self._load("nw_b")["ScriptDeath"]["value"], "nw_c2_default7")

    def test_apply_script_dash_clears_field(self):
        d = make_utc("c")
        d["ScriptSpawn"] = _field("resref", "some_spawn_script")
        self._write("nw_c", d)
        form = {"res": ["nw_c"], "ScriptSpawn": ["-"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertEqual(self._load("nw_c")["ScriptSpawn"]["value"], "")

    def test_apply_flags_across_selection(self):
        self._write("nw_d", make_utc("d", Plot=0, Lootable=1, NoPermDeath=0, IsImmortal=0))
        self._write("nw_e", make_utc("e", Plot=0, Lootable=0, NoPermDeath=1, IsImmortal=0))
        form = {"res": ["nw_d", "nw_e"], "Plot": ["1"], "IsImmortal": ["1"]}
        changed_html = CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertIn("Changed 2 of 2 selected", changed_html)
        for res in ("nw_d", "nw_e"):
            g = self._load(res)
            self.assertEqual(g["Plot"]["value"], 1)
            self.assertEqual(g["IsImmortal"]["value"], 1)
        # Fields not touched in the form must be left exactly as they were.
        self.assertEqual(self._load("nw_d")["Lootable"]["value"], 1)
        self.assertEqual(self._load("nw_e")["Lootable"]["value"], 0)
        self.assertEqual(self._load("nw_e")["NoPermDeath"]["value"], 1)

    def test_apply_flag_unchanged_option_leaves_field_alone(self):
        self._write("nw_f", make_utc("f", NoPermDeath=1))
        # An empty string is what the "(leave unchanged)" <option value=''>
        # submits - must not be coerced to int(0).
        form = {"res": ["nw_f"], "NoPermDeath": [""]}
        touched_html = CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertIn("Changed 0 of 1 selected", touched_html)
        self.assertEqual(self._load("nw_f")["NoPermDeath"]["value"], 1)

    def test_apply_decay_time(self):
        self._write("nw_g", make_utc("g"))
        form = {"res": ["nw_g"], "DecayTime": ["30000"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertEqual(self._load("nw_g")["DecayTime"]["value"], 30000)
        self.assertEqual(self._load("nw_g")["DecayTime"]["type"], "dword")

    def test_apply_blank_decay_time_leaves_unchanged(self):
        d = make_utc("h")
        d["DecayTime"] = _field("dword", 5000)
        self._write("nw_h", d)
        form = {"res": ["nw_h"], "DecayTime": [""]}
        touched_html = CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertIn("Changed 0 of 1 selected", touched_html)
        self.assertEqual(self._load("nw_h")["DecayTime"]["value"], 5000)

    def test_apply_skips_unknown_resref_without_crashing(self):
        self._write("nw_i", make_utc("i"))
        form = {"res": ["nw_i", "nw_does_not_exist"], "Plot": ["1"]}
        result_html = CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertIn("Changed 1 of 1 selected", result_html)

    def test_render_settings_form_shows_current_value_summary(self):
        self._write("nw_j", make_utc("j", Lootable=1))
        self._write("nw_k", make_utc("k", Lootable=0))
        html = CONSOLE.render_creature_settings_form(self.tmp, ["nw_j", "nw_k"])
        self.assertIn("Leaves lootable corpse", html)
        self.assertIn("No, Yes", html)  # sorted distinct current values

    def test_apply_flags_also_updates_placed_instance_of_same_blueprint(self):
        # NWN bakes a full copy of the blueprint into an instance at
        # placement time - editing the blueprint alone never reaches a
        # creature already placed in an area. This is the actual bug report:
        # bulk-editing Lootable/DecayTime/etc had no in-game effect.
        self._write("nw_orc", make_utc("orc", Lootable=1))
        self._write_area("testarea", make_git_json(
            creatures=[make_placed_creature("nw_orc", Lootable=1)]))
        form = {"res": ["nw_orc"], "Lootable": ["0"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        inst = self._load_git("testarea")["Creature List"]["value"][0]
        self.assertEqual(inst["Lootable"]["value"], 0)

    def test_apply_skips_placed_instance_with_different_template_resref(self):
        self._write("nw_orc2", make_utc("orc2", Lootable=1))
        self._write_area("testarea2", make_git_json(
            creatures=[make_placed_creature("nw_goblin", Lootable=1)]))
        form = {"res": ["nw_orc2"], "Lootable": ["0"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        inst = self._load_git("testarea2")["Creature List"]["value"][0]
        self.assertEqual(inst["Lootable"]["value"], 1)  # untouched

    def test_apply_syncs_decaytime_and_script_to_placed_instance(self):
        self._write("nw_bandit", make_utc("bandit"))
        self._write_area("testarea3", make_git_json(
            creatures=[make_placed_creature("nw_bandit")]))
        form = {"res": ["nw_bandit"], "DecayTime": ["30000"],
                "ScriptDeath": ["nw_c2_default7"]}
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        inst = self._load_git("testarea3")["Creature List"]["value"][0]
        self.assertEqual(inst["DecayTime"]["value"], 30000)
        self.assertEqual(inst["ScriptDeath"]["value"], "nw_c2_default7")

    def test_apply_with_no_submitted_fields_does_not_touch_area_file(self):
        self._write("nw_still", make_utc("still", Lootable=1))
        self._write_area("testarea4", make_git_json(
            creatures=[make_placed_creature("nw_still", Lootable=1)]))
        area_path = os.path.join(self.tmp, "testarea4.git.json")
        before = os.path.getmtime(area_path)
        form = {"res": ["nw_still"]}  # nothing submitted
        CONSOLE.apply_creature_settings(self.tmp, self.tmp, form)
        self.assertEqual(os.path.getmtime(area_path), before)

    def test_sync_placed_instances_updates_item_dropable_by_matching_resref(self):
        self._write("nw_merchant", make_utc("merchant"))
        d = self._load("nw_merchant")
        d["ItemList"] = _field("list", [
            {"__struct_id": 0, "InventoryRes": _field("resref", "nw_it_gem001"),
             "Dropable": _field("byte", 0)},
        ])
        self._write("nw_merchant", d)
        self._write_area("testarea5", make_git_json(creatures=[
            make_placed_creature("nw_merchant",
                                  carried=[make_carried("nw_it_gem001", dropable=1)]),
        ]))
        CONSOLE.sync_placed_instances(
            self.tmp, self.tmp, "creature", "nw_merchant", d,
            item_subfields=["ItemList"])
        inst = self._load_git("testarea5")["Creature List"]["value"][0]
        self.assertEqual(inst["ItemList"]["value"][0]["Dropable"]["value"], 0)

    def test_sync_placed_instances_skips_item_when_resref_has_drifted(self):
        self._write("nw_merchant2", make_utc("merchant2"))
        d = self._load("nw_merchant2")
        d["ItemList"] = _field("list", [
            {"__struct_id": 0, "InventoryRes": _field("resref", "nw_it_gem001"),
             "Dropable": _field("byte", 0)},
        ])
        self._write("nw_merchant2", d)
        # The placed instance's item at index 0 is a *different* item than
        # the blueprint's (inventory drifted after placement, e.g. a DM
        # swapped loot) - must not blindly overwrite Dropable by index alone.
        self._write_area("testarea6", make_git_json(creatures=[
            make_placed_creature("nw_merchant2",
                                  carried=[make_carried("nw_it_sword001", dropable=1)]),
        ]))
        CONSOLE.sync_placed_instances(
            self.tmp, self.tmp, "creature", "nw_merchant2", d,
            item_subfields=["ItemList"])
        inst = self._load_git("testarea6")["Creature List"]["value"][0]
        self.assertEqual(inst["ItemList"]["value"][0]["Dropable"]["value"], 1)


class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real select -> settings-form -> apply routes over a
    socket, matching the convention in test_remove_objects.py."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_bulk_http_test_")
        for res in ("httpcreature1", "httpcreature2"):
            d = make_utc(res, Plot=0, Lootable=1)
            if res == "httpcreature1":
                d["ItemList"] = _field("list", [
                    {"__struct_id": 0,
                     "InventoryRes": _field("resref", "nw_it_gem001"),
                     "Dropable": _field("byte", 1)},
                ])
            with open(os.path.join(cls.tmp, res + ".utc.json"), "w") as fh:
                json.dump(d, fh)

        # A placed instance of httpcreature1 in an area - proves the fix:
        # a blueprint-only edit never reaches an instance already placed
        # (NWN bakes a full struct copy into it at placement time).
        with open(os.path.join(cls.tmp, "httparea.are.json"), "w") as fh:
            json.dump({"__data_type": "ARE"}, fh)
        with open(os.path.join(cls.tmp, "httparea.git.json"), "w") as fh:
            json.dump(make_git_json(creatures=[
                make_placed_creature(
                    "httpcreature1", Plot=0, Lootable=1,
                    carried=[make_carried("nw_it_gem001", dropable=1)]),
            ]), fh)

        cls.port = 18392
        cls._old_argv = sys.argv
        sys.argv = ["nwn-area-editor", "--dir", cls.tmp, "--git-dir", cls.tmp,
                    "--gic-dir", cls.tmp, "--host", "127.0.0.1", "--port", str(cls.port)]
        cls.server_thread = threading.Thread(target=CONSOLE.main, daemon=True)
        cls.server_thread.start()

        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/creatures" % cls.port, timeout=0.2)
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

    def test_full_bulk_edit_round_trip(self):
        listing = self._get("/creatures")
        self.assertIn("Edit settings for selected", listing)

        form_html = self._post(
            "/creatures/select",
            {"res": ["httpcreature1", "httpcreature2"]})
        self.assertIn("Editing <b>2</b> creature(s)", form_html)

        result_html = self._post(
            "/creatures/settings/apply",
            {"res": ["httpcreature1", "httpcreature2"], "Plot": ["1"]})
        self.assertIn("Changed 2 of 2 selected", result_html)

        for res in ("httpcreature1", "httpcreature2"):
            with open(os.path.join(self.tmp, res + ".utc.json")) as fh:
                self.assertEqual(json.load(fh)["Plot"]["value"], 1)

        # And the placed instance of httpcreature1 must be patched too -
        # this is what was actually broken (blueprint-only writes never
        # reached anything already placed in an area).
        with open(os.path.join(self.tmp, "httparea.git.json")) as fh:
            inst = json.load(fh)["Creature List"]["value"][0]
        self.assertEqual(inst["Plot"]["value"], 1)

    def test_single_creature_apply_syncs_lootable_and_dropable_to_placed_instance(self):
        self._post("/creature/apply", {
            "res": ["httpcreature1"],
            "Lootable": ["0"],
            "dropable_carried_present": ["1"],
            # index 0 left unchecked -> Dropable becomes 0.
        })
        with open(os.path.join(self.tmp, "httparea.git.json")) as fh:
            inst = json.load(fh)["Creature List"]["value"][0]
        self.assertEqual(inst["Lootable"]["value"], 0)
        self.assertEqual(inst["ItemList"]["value"][0]["Dropable"]["value"], 0)


if __name__ == "__main__":
    unittest.main()
