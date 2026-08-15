#!/usr/bin/env python3
"""Tests for module.ifo settings editing in bin/nwn-area-editor.

Exercises render_module_form / apply_module against synthetic module.ifo.json
fixtures, plus one live HTTP round-trip through the real console routes.

Two properties matter most here and are what most of these cases assert:
a field the module.ifo doesn't already carry is never created (.ifo field sets
vary by toolset build), and an untouched form is a byte-identical no-op.

Run all tests:
    python3 tests/test_module_settings.py

Run one case:
    python3 -m unittest tests.test_module_settings.ModuleSettingsTests.test_absent_fields_are_never_created
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
    "nwn_area_editor_under_test__test_module_settings",
    str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_ifo_json(**overrides):
    """A module.ifo.json carrying one field from each editable group, shaped
    like real nwn_gff output."""
    d = {
        "__data_type": "IFO ",
        "Mod_Name": _field("cexolocstring", {"0": "Test Module"}),
        "Mod_Description": _field("cexolocstring", {"0": "desc"}),
        "Mod_Entry_Area": _field("resref", "startarea"),
        "Mod_Entry_X": _field("float", 10.0),
        "Mod_Entry_Y": _field("float", 20.0),
        "Mod_Entry_Z": _field("float", 0.0),
        "Mod_Entry_Dir_X": _field("float", 0.0),
        "Mod_Entry_Dir_Y": _field("float", 1.0),
        "Mod_DawnHour": _field("byte", 6),
        "Mod_DuskHour": _field("byte", 18),
        "Mod_MinPerHour": _field("byte", 2),
        "Mod_StartHour": _field("byte", 13),
        "Mod_StartDay": _field("byte", 1),
        "Mod_StartMonth": _field("byte", 6),
        "Mod_StartYear": _field("dword", 1372),
        "Mod_XPScale": _field("byte", 10),
        "Mod_PartyControl": _field("int", 0),
        "Mod_Tag": _field("cexostring", "testmod"),
        "Mod_MinGameVer": _field("cexostring", "1.89"),
        "Mod_HakList": _field("list", [
            {"__struct_id": 8, "Mod_Hak": _field("cexostring", "myhak")}]),
        "Mod_CustomTlk": _field("cexostring", "mytlk"),
    }
    d.update(overrides)
    return d


class ModuleSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_modsettings_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "module.ifo.json")

    def _write(self, d=None):
        with open(self.path, "w") as fh:
            json.dump(d if d is not None else make_ifo_json(), fh)

    def _load(self):
        with open(self.path) as fh:
            return json.load(fh)

    def _write_area(self, res):
        with open(os.path.join(self.tmp, res + ".are.json"), "w") as fh:
            json.dump({"__data_type": "ARE ",
                       "ResRef": _field("resref", res)}, fh)

    # --- Writing --------------------------------------------------------

    def test_start_location_fields_are_written(self):
        self._write()
        self._write_area("startarea")
        touched, warnings = CONSOLE.apply_module(
            self.tmp, {"Mod_Entry_X": ["33.5"], "Mod_Entry_Dir_Y": ["-1.0"]})
        self.assertTrue(touched)
        self.assertEqual(warnings, [])
        d = self._load()
        self.assertEqual(CONSOLE.getv(d, "Mod_Entry_X"), 33.5)
        self.assertEqual(CONSOLE.getv(d, "Mod_Entry_Dir_Y"), -1.0)

    def test_calendar_and_rule_fields_are_written(self):
        self._write()
        self._write_area("startarea")
        CONSOLE.apply_module(self.tmp, {"Mod_StartYear": ["1400"],
                                        "Mod_DawnHour": ["5"],
                                        "Mod_XPScale": ["20"]})
        d = self._load()
        self.assertEqual(CONSOLE.getv(d, "Mod_StartYear"), 1400)
        self.assertEqual(CONSOLE.getv(d, "Mod_DawnHour"), 5)
        self.assertEqual(CONSOLE.getv(d, "Mod_XPScale"), 20)

    def test_declared_gff_types_are_preserved(self):
        self._write()
        self._write_area("startarea")
        CONSOLE.apply_module(self.tmp, {"Mod_StartYear": ["1400"],
                                        "Mod_Entry_X": ["1"],
                                        "Mod_Tag": ["newtag"]})
        d = self._load()
        self.assertEqual(d["Mod_StartYear"]["type"], "dword")
        self.assertEqual(d["Mod_Entry_X"]["type"], "float")
        self.assertIsInstance(CONSOLE.getv(d, "Mod_Entry_X"), float)
        self.assertEqual(d["Mod_Tag"]["type"], "cexostring")

    def test_resref_fields_are_lowercased(self):
        self._write()
        self._write_area("newstart")
        CONSOLE.apply_module(self.tmp, {"Mod_Entry_Area": ["NewStart"]})
        self.assertEqual(CONSOLE.getv(self._load(), "Mod_Entry_Area"), "newstart")

    def test_name_and_description_still_work(self):
        self._write()
        self._write_area("startarea")
        CONSOLE.apply_module(self.tmp, {"Mod_Name": ["Renamed"],
                                        "Mod_Description": ["new desc"]})
        d = self._load()
        self.assertEqual(CONSOLE.loc_get(d, "Mod_Name"), "Renamed")
        self.assertEqual(CONSOLE.loc_get(d, "Mod_Description"), "new desc")

    # --- Leaving things alone -------------------------------------------

    def test_blank_leaves_a_field_unchanged(self):
        self._write()
        self._write_area("startarea")
        CONSOLE.apply_module(self.tmp, {"Mod_XPScale": [""], "Mod_Tag": ["  "]})
        d = self._load()
        self.assertEqual(CONSOLE.getv(d, "Mod_XPScale"), 10)
        self.assertEqual(CONSOLE.getv(d, "Mod_Tag"), "testmod")

    def test_untouched_form_is_a_byte_identical_no_op(self):
        self._write()
        self._write_area("startarea")
        with open(self.path) as fh:
            before = fh.read()
        touched, _ = CONSOLE.apply_module(self.tmp, {})
        self.assertFalse(touched)
        with open(self.path) as fh:
            self.assertEqual(fh.read(), before)

    def test_absent_fields_are_never_created(self):
        """.ifo field sets vary by toolset build; adding one the module never
        had is a behaviour change, not an edit."""
        d = make_ifo_json()
        del d["Mod_XPScale"]
        del d["Mod_MinPerHour"]
        self._write(d)
        self._write_area("startarea")
        touched, _ = CONSOLE.apply_module(
            self.tmp, {"Mod_XPScale": ["50"], "Mod_MinPerHour": ["9"]})
        self.assertFalse(touched)
        out = self._load()
        self.assertNotIn("Mod_XPScale", out)
        self.assertNotIn("Mod_MinPerHour", out)

    def test_hak_list_and_custom_tlk_are_untouched(self):
        """Deferred by design - changing these needs a re-unpack to pick up the
        new content, so the form must not offer them."""
        self._write()
        self._write_area("startarea")
        CONSOLE.apply_module(self.tmp, {"Mod_CustomTlk": ["othertlk"],
                                        "Mod_HakList": ["otherhak"]})
        d = self._load()
        self.assertEqual(CONSOLE.getv(d, "Mod_CustomTlk"), "mytlk")
        self.assertEqual(len(CONSOLE.getv(d, "Mod_HakList")), 1)

    # --- Warnings -------------------------------------------------------

    def test_missing_start_area_warns_but_still_saves(self):
        self._write()
        touched, warnings = CONSOLE.apply_module(
            self.tmp, {"Mod_Entry_Area": ["nosucharea"]})
        self.assertTrue(touched)
        self.assertEqual(len(warnings), 1)
        self.assertIn("nosucharea", warnings[0])
        self.assertEqual(CONSOLE.getv(self._load(), "Mod_Entry_Area"), "nosucharea")

    def test_existing_start_area_produces_no_warning(self):
        self._write()
        self._write_area("startarea")
        _touched, warnings = CONSOLE.apply_module(self.tmp, {})
        self.assertEqual(warnings, [])

    # --- Rendering ------------------------------------------------------

    def test_form_renders_every_present_editable_field(self):
        html = CONSOLE.render_module_form(make_ifo_json())
        for field in ("Mod_Entry_Area", "Mod_Entry_X", "Mod_DawnHour",
                      "Mod_StartYear", "Mod_XPScale", "Mod_Tag"):
            self.assertIn("name='%s'" % field, html)

    def test_form_omits_absent_fields_and_hak_controls(self):
        d = make_ifo_json()
        del d["Mod_XPScale"]
        html = CONSOLE.render_module_form(d)
        self.assertNotIn("name='Mod_XPScale'", html)
        self.assertNotIn("name='Mod_HakList'", html)
        self.assertNotIn("name='Mod_CustomTlk'", html)

    def test_empty_group_renders_no_fieldset(self):
        d = {"__data_type": "IFO ",
             "Mod_Name": _field("cexolocstring", {"0": "Bare"}),
             "Mod_Description": _field("cexolocstring", {"0": ""})}
        html = CONSOLE.render_module_form(d)
        self.assertNotIn("Start location", html)
        self.assertNotIn("Rules", html)
        self.assertIn("name='Mod_Name'", html)

    def test_current_values_are_prefilled(self):
        html = CONSOLE.render_module_form(make_ifo_json())
        self.assertIn("name='Mod_Entry_Area' value='startarea'", html)
        self.assertIn("name='Mod_StartYear' value='1372'", html)


class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real GET /module -> POST /module/apply routes over a
    socket, which is what would catch a routing/dispatch typo."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_modsettings_http_")
        with open(os.path.join(cls.tmp, "module.ifo.json"), "w") as fh:
            json.dump(make_ifo_json(), fh)
        with open(os.path.join(cls.tmp, "startarea.are.json"), "w") as fh:
            json.dump({"__data_type": "ARE ",
                       "ResRef": _field("resref", "startarea"),
                       "Name": _field("cexolocstring", {"0": "Start"}),
                       "Tag": _field("cexostring", "start"),
                       "Tileset": _field("resref", "tst"),
                       "Flags": _field("dword", 1)}, fh)

        cls.port = 18394
        cls._old_argv = sys.argv
        sys.argv = ["nwn-area-editor", "--dir", cls.tmp, "--git-dir", cls.tmp,
                    "--gic-dir", cls.tmp, "--host", "127.0.0.1",
                    "--port", str(cls.port)]
        cls.server_thread = threading.Thread(target=CONSOLE.main, daemon=True)
        cls.server_thread.start()
        for _ in range(50):
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/areas" % cls.port, timeout=0.2)
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
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            timeout=5).read().decode()

    def test_full_http_round_trip(self):
        form_html = self._get("/module")
        self.assertIn("name='Mod_XPScale'", form_html)
        self.assertIn("name='Mod_Entry_Area'", form_html)

        result = self._post("/module/apply", {"Mod_XPScale": ["25"]})
        self.assertIn("Module info saved", result)

        with open(os.path.join(self.tmp, "module.ifo.json")) as fh:
            d = json.load(fh)
        self.assertEqual(CONSOLE.getv(d, "Mod_XPScale"), 25)

    def test_missing_start_area_warning_reaches_the_page(self):
        result = self._post("/module/apply", {"Mod_Entry_Area": ["ghostarea"]})
        self.assertIn("ghostarea", result)
        self.assertIn("warn", result)


if __name__ == "__main__":
    unittest.main()
