#!/usr/bin/env python3
"""Tests for area Name / Flags editing in bin/nwn-area-editor.

Exercises render_tags_form / apply_tags directly (loaded via SourceFileLoader,
since nwn-area-editor has no .py extension) against synthetic .are.json
fixtures, plus one live HTTP round-trip through the real console routes.

The load-bearing cases here are the two ways flag editing can go wrong:
unchecked checkboxes silently clearing every bit, and a save dropping flag bits
whose meaning isn't in AREA_FLAG_FIELDS.

Run all tests:
    python3 tests/test_area_name_flags.py

Run one case:
    python3 -m unittest tests.test_area_name_flags.AreaNameFlagsTests.test_unknown_flag_bits_survive_a_save
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
    "nwn_area_editor_under_test__test_area_name_flags",
    str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def make_are_json(res, name="An Area", tag="atag", flags=0):
    return {
        "__data_type": "ARE ",
        "ResRef": _field("resref", res),
        "Name": _field("cexolocstring", {"0": name}),
        "Tag": _field("cexostring", tag),
        "Tileset": _field("resref", "tst"),
        "Flags": _field("dword", flags),
    }


class AreaNameFlagsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_areaflags_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write(self, res, **kw):
        path = os.path.join(self.tmp, res + ".are.json")
        with open(path, "w") as fh:
            json.dump(make_are_json(res, **kw), fh)
        return path

    def _load(self, res):
        with open(os.path.join(self.tmp, res + ".are.json")) as fh:
            return json.load(fh)

    def _apply(self, form):
        return CONSOLE.apply_tags(self.tmp, self.tmp, self.tmp, form)

    # --- Name -----------------------------------------------------------

    def test_name_is_written(self):
        self._write("a1", name="Old Name")
        self._apply({"res": ["a1"], "name_a1": ["New Name"]})
        self.assertEqual(CONSOLE.loc_get(self._load("a1"), "Name"), "New Name")

    def test_blank_name_leaves_it_unchanged(self):
        self._write("a1", name="Keep Me")
        self._apply({"res": ["a1"], "name_a1": [""], "tag_a1": ["newtag"]})
        d = self._load("a1")
        self.assertEqual(CONSOLE.loc_get(d, "Name"), "Keep Me")
        self.assertEqual(CONSOLE.getv(d, "Tag"), "newtag")

    def test_name_edit_alone_still_marks_the_area_changed(self):
        self._write("a1", name="Old")
        page = self._apply({"res": ["a1"], "name_a1": ["New"]})
        self.assertIn("Changed 1 of 1 selected", page)

    # --- Flags ----------------------------------------------------------

    def test_flag_bits_set_from_checkboxes(self):
        self._write("a1", flags=0)
        self._apply({"res": ["a1"], "flags_present_a1": ["1"],
                     "flag_a1_interior": ["on"], "flag_a1_underground": ["on"]})
        self.assertEqual(
            CONSOLE.getv(self._load("a1"), "Flags"),
            CONSOLE.AREA_FLAG_INTERIOR | CONSOLE.AREA_FLAG_UNDERGROUND)

    def test_unticked_boxes_clear_their_bits_when_the_marker_is_present(self):
        self._write("a1", flags=CONSOLE.AREA_FLAG_NATURAL)
        self._apply({"res": ["a1"], "flags_present_a1": ["1"]})
        self.assertEqual(CONSOLE.getv(self._load("a1"), "Flags"), 0)

    def test_missing_marker_leaves_flags_completely_alone(self):
        """A form without flag controls (or a stale bookmarked POST) must not
        be read as 'the user unticked everything'."""
        self._write("a1", flags=CONSOLE.AREA_FLAG_NATURAL)
        self._apply({"res": ["a1"], "name_a1": ["Renamed"]})
        d = self._load("a1")
        self.assertEqual(CONSOLE.getv(d, "Flags"), CONSOLE.AREA_FLAG_NATURAL)
        self.assertEqual(CONSOLE.loc_get(d, "Name"), "Renamed")

    def test_unknown_flag_bits_survive_a_save(self):
        """Only the three documented bits are ours to rewrite; anything else a
        toolset build set has to round-trip untouched."""
        unknown = 0x100
        self._write("a1", flags=unknown | CONSOLE.AREA_FLAG_NATURAL)
        self._apply({"res": ["a1"], "flags_present_a1": ["1"],
                     "flag_a1_interior": ["on"]})
        self.assertEqual(CONSOLE.getv(self._load("a1"), "Flags"),
                         unknown | CONSOLE.AREA_FLAG_INTERIOR)

    def test_no_change_form_is_a_no_op(self):
        self._write("a1", name="Same", tag="same", flags=CONSOLE.AREA_FLAG_INTERIOR)
        path = os.path.join(self.tmp, "a1.are.json")
        with open(path) as fh:
            before = fh.read()
        page = self._apply({"res": ["a1"], "name_a1": ["Same"],
                            "tag_a1": ["same"], "flags_present_a1": ["1"],
                            "flag_a1_interior": ["on"]})
        with open(path) as fh:
            self.assertEqual(fh.read(), before)
        self.assertIn("Changed 0 of 1 selected", page)

    def test_each_area_gets_its_own_flags(self):
        self._write("a1", flags=0)
        self._write("a2", flags=0)
        self._apply({"res": ["a1", "a2"],
                     "flags_present_a1": ["1"], "flag_a1_interior": ["on"],
                     "flags_present_a2": ["1"], "flag_a2_natural": ["on"]})
        self.assertEqual(CONSOLE.getv(self._load("a1"), "Flags"),
                         CONSOLE.AREA_FLAG_INTERIOR)
        self.assertEqual(CONSOLE.getv(self._load("a2"), "Flags"),
                         CONSOLE.AREA_FLAG_NATURAL)

    def test_flag_edit_survives_a_resref_rename(self):
        self._write("a1", flags=0)
        self._apply({"res": ["a1"], "ref_a1": ["a1new"],
                     "flags_present_a1": ["1"], "flag_a1_interior": ["on"]})
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "a1new.are.json")))
        with open(os.path.join(self.tmp, "a1new.are.json")) as fh:
            d = json.load(fh)
        self.assertEqual(CONSOLE.getv(d, "Flags"), CONSOLE.AREA_FLAG_INTERIOR)
        self.assertEqual(CONSOLE.getv(d, "ResRef"), "a1new")

    # --- Form rendering -------------------------------------------------

    def test_form_prefills_name_and_checks_current_flags(self):
        self._write("a1", name="Prefilled", flags=CONSOLE.AREA_FLAG_UNDERGROUND)
        html = CONSOLE.render_tags_form(self.tmp, ["a1"])
        self.assertIn("name='name_a1'", html)
        self.assertIn("value='Prefilled'", html)
        self.assertIn("name='flags_present_a1'", html)
        self.assertIn("name='flag_a1_underground' checked", html)
        self.assertIn("name='flag_a1_interior'>", html)


class HttpRoundTripTest(unittest.TestCase):
    """Exercises the real GET form -> POST apply routes over an actual socket,
    which is what would catch a routing/dispatch typo."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_areaflags_http_")
        with open(os.path.join(cls.tmp, "httparea.are.json"), "w") as fh:
            json.dump(make_are_json("httparea", name="Before", flags=0), fh)

        cls.port = 18393
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
        form_html = self._get("/areas/edit?action=tags&res=httparea")
        self.assertIn("name='name_httparea'", form_html)
        self.assertIn("name='flags_present_httparea'", form_html)

        result = self._post("/areas/tags/apply",
                            {"res": ["httparea"], "name_httparea": ["After"],
                             "flags_present_httparea": ["1"],
                             "flag_httparea_interior": ["on"]})
        self.assertIn("Changed 1 of 1 selected", result)

        with open(os.path.join(self.tmp, "httparea.are.json")) as fh:
            d = json.load(fh)
        self.assertEqual(CONSOLE.loc_get(d, "Name"), "After")
        self.assertEqual(CONSOLE.getv(d, "Flags"), CONSOLE.AREA_FLAG_INTERIOR)


if __name__ == "__main__":
    unittest.main()
