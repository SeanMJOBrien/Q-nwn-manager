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
    "nwn_area_editor_under_test", str(REPO_ROOT / "bin" / "nwn-area-editor")
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
        CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertEqual(self._load("nw_a")["ScriptDeath"]["value"], "nw_c2_default7")
        self.assertEqual(self._load("nw_b")["ScriptDeath"]["value"], "nw_c2_default7")

    def test_apply_script_dash_clears_field(self):
        d = make_utc("c")
        d["ScriptSpawn"] = _field("resref", "some_spawn_script")
        self._write("nw_c", d)
        form = {"res": ["nw_c"], "ScriptSpawn": ["-"]}
        CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertEqual(self._load("nw_c")["ScriptSpawn"]["value"], "")

    def test_apply_flags_across_selection(self):
        self._write("nw_d", make_utc("d", Plot=0, Lootable=1, NoPermDeath=0, IsImmortal=0))
        self._write("nw_e", make_utc("e", Plot=0, Lootable=0, NoPermDeath=1, IsImmortal=0))
        form = {"res": ["nw_d", "nw_e"], "Plot": ["1"], "IsImmortal": ["1"]}
        changed_html = CONSOLE.apply_creature_settings(self.tmp, form)
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
        touched_html = CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertIn("Changed 0 of 1 selected", touched_html)
        self.assertEqual(self._load("nw_f")["NoPermDeath"]["value"], 1)

    def test_apply_decay_time(self):
        self._write("nw_g", make_utc("g"))
        form = {"res": ["nw_g"], "DecayTime": ["30000"]}
        CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertEqual(self._load("nw_g")["DecayTime"]["value"], 30000)
        self.assertEqual(self._load("nw_g")["DecayTime"]["type"], "dword")

    def test_apply_blank_decay_time_leaves_unchanged(self):
        d = make_utc("h")
        d["DecayTime"] = _field("dword", 5000)
        self._write("nw_h", d)
        form = {"res": ["nw_h"], "DecayTime": [""]}
        touched_html = CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertIn("Changed 0 of 1 selected", touched_html)
        self.assertEqual(self._load("nw_h")["DecayTime"]["value"], 5000)

    def test_apply_skips_unknown_resref_without_crashing(self):
        self._write("nw_i", make_utc("i"))
        form = {"res": ["nw_i", "nw_does_not_exist"], "Plot": ["1"]}
        result_html = CONSOLE.apply_creature_settings(self.tmp, form)
        self.assertIn("Changed 1 of 1 selected", result_html)

    def test_render_settings_form_shows_current_value_summary(self):
        self._write("nw_j", make_utc("j", Lootable=1))
        self._write("nw_k", make_utc("k", Lootable=0))
        html = CONSOLE.render_creature_settings_form(self.tmp, ["nw_j", "nw_k"])
        self.assertIn("Leaves lootable corpse", html)
        self.assertIn("No, Yes", html)  # sorted distinct current values


class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real select -> settings-form -> apply routes over a
    socket, matching the convention in test_remove_objects.py."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_bulk_http_test_")
        for res in ("httpcreature1", "httpcreature2"):
            d = make_utc(res, Plot=0)
            with open(os.path.join(cls.tmp, res + ".utc.json"), "w") as fh:
                json.dump(d, fh)

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


if __name__ == "__main__":
    unittest.main()
