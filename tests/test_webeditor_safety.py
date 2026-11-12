#!/usr/bin/env python3
"""CSRF + stale-edit checks in the standalone web editor
(skills/nwn-web-editor/scripts/nwn_web_editor.py). gff_load/gff_save's nwn_gff
subprocess is swapped for plain JSON so a real server round trip runs without
the neverwinter tools.

Run: python3 tests/test_webeditor_safety.py
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
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrf_client import Client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = SourceFileLoader(
    "nwn_web_editor_under_test__safety",
    str(REPO_ROOT / "skills" / "nwn-web-editor" / "scripts" /
        "nwn_web_editor.py")).load_module()


def f(t, v):
    return {"type": t, "value": v}


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _save_json(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh)


class WebEditorSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="qnm_websafety_")
        cls.ifo = os.path.join(cls.tmp, "module.ifo")
        _save_json(cls.ifo, {"Mod_Name": f("cexolocstring", {"0": "Old"}),
                             "Mod_Description": f("cexolocstring", {"0": "d"})})
        cls._orig = (WEB.gff_load, WEB.NWN_GFF)
        WEB.gff_load = _load
        # gff_save with the nwn_gff step replaced by a JSON write, keeping the
        # real stale check and written-file bookkeeping
        cls._orig_save = WEB.gff_save

        def save(path, data):
            WEB.check_stale(path)
            WEB._req.written.add(os.path.abspath(path))
            _save_json(path, data)
        WEB.gff_save = save
        cls.port = 18397
        cls._old_argv = sys.argv
        sys.argv = ["nwn_web_editor.py", "--dir", cls.tmp, "--port",
                    str(cls.port), "--nwn-gff", sys.executable]
        threading.Thread(target=WEB.main, daemon=True).start()
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/module" % cls.port,
                                       timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("test web editor did not start in time")

    @classmethod
    def tearDownClass(cls):
        sys.argv = cls._old_argv
        WEB.gff_load = cls._orig[0]
        WEB.gff_save = cls._orig_save
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.c = Client(self.port, "/module")
        _save_json(self.ifo, {"Mod_Name": f("cexolocstring", {"0": "Old"}),
                              "Mod_Description": f("cexolocstring", {"0": "d"})})

    def name(self):
        return _load(self.ifo)["Mod_Name"]["value"]["0"]

    def post(self, **kw):
        try:
            self.c.post("/module/apply", {"Mod_Name": "New",
                                          "Mod_Description": "d"}, **kw)
            return 200
        except urllib.error.HTTPError as e:
            return e.code

    def test_forms_carry_token(self):
        self.assertIn("name='_csrf'", self.c.get("/module"))

    def test_post_without_token_rejected(self):
        self.assertEqual(self.post(token=False), 403)
        self.assertEqual(self.name(), "Old")

    def test_valid_post_applies(self):
        self.assertEqual(self.post(), 200)
        self.assertEqual(self.name(), "New")

    def test_stale_form_refused(self):
        self.c.get("/module")
        self.assertEqual(self.post(rendered=time.time() - 3600), 409)
        self.assertEqual(self.name(), "Old")


if __name__ == "__main__":
    unittest.main()
