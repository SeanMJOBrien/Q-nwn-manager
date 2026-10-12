#!/usr/bin/env python3
"""Tests for the reference-aware rename helpers in the standalone web editor
(skills/nwn-web-editor/scripts/nwn_web_editor.py). nwn_gff isn't required:
gff_load/gff_save are swapped for plain JSON so the module.ifo logic and the
script scan run for real.

Run: python3 tests/test_area_rename_refs_webeditor.py
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
    "nwn_web_editor_under_test__renamerefs",
    str(REPO_ROOT / "skills" / "nwn-web-editor" / "scripts" /
        "nwn_web_editor.py")).load_module()


def f(t, v):
    return {"type": t, "value": v}


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh)


class WebEditorRenameRefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_webrename_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._orig = (WEB.gff_load, WEB.gff_save)
        WEB.gff_load, WEB.gff_save = _load, _save
        self.addCleanup(lambda: setattr(WEB, "gff_load", self._orig[0]))
        self.addCleanup(lambda: setattr(WEB, "gff_save", self._orig[1]))
        for res in ("old1", "other"):
            _save(os.path.join(self.tmp, res + ".are"),
                  {"ResRef": f("resref", res), "Tag": f("cexostring", "atag"),
                   "Name": f("cexolocstring", {"0": "n"})})
        _save(os.path.join(self.tmp, "module.ifo"), {
            "Mod_Entry_Area": f("resref", "old1"),
            "Mod_Area_list": f("list", [
                {"__struct_id": 6, "Area_Name": f("resref", a)}
                for a in ("old1", "other")])})

    def ifo(self):
        return _load(os.path.join(self.tmp, "module.ifo"))

    def test_rename_cascades_into_module_ifo(self):
        WEB.apply_tags(self.tmp, {"res": ["old1"], "ref_old1": ["new1"]})
        d = self.ifo()
        self.assertEqual(WEB.getv(d, "Mod_Entry_Area"), "new1")
        self.assertEqual([WEB.getv(i, "Area_Name")
                          for i in WEB.getv(d, "Mod_Area_list")],
                         ["new1", "other"])

    def test_preview_shows_rows_and_writes_nothing(self):
        before = json.dumps(self.ifo())
        diffs, errors = WEB.apply_tags(
            self.tmp, {"res": ["old1"], "ref_old1": ["new1"]}, dry_run=True)
        self.assertEqual(sorted(d[1] for d in diffs if "module.ifo" in d[1]),
                         ["module.ifo: Mod_Area_list[0]",
                          "module.ifo: Mod_Entry_Area"])
        self.assertEqual(json.dumps(self.ifo()), before)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "old1.are")))

    def test_missing_module_ifo_is_fine(self):
        os.remove(os.path.join(self.tmp, "module.ifo"))
        page = WEB.apply_tags(self.tmp, {"res": ["old1"], "ref_old1": ["new1"]})
        self.assertIn("Changed 1 of 1", page)

    def test_script_scan_reported_not_edited(self):
        src = 'void main(){ GetObjectByTag("atag"); }\n'
        with open(os.path.join(self.tmp, "s.nss"), "w") as fh:
            fh.write(src)
        page = WEB.apply_tags(self.tmp, {"res": ["old1"], "tag_old1": ["newtag"]})
        self.assertIn("s.nss:1", page)
        with open(os.path.join(self.tmp, "s.nss")) as fh:
            self.assertEqual(fh.read(), src)


if __name__ == "__main__":
    unittest.main()
