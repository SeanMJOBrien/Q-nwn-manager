#!/usr/bin/env python3
"""Tests for bin/nwn-common (CSRF guard, stale-edit check, edit history) and
for how the console uses them end to end.

Run: python3 tests/test_safety.py
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
COMMON = SourceFileLoader("nwn_common_under_test",
                          str(REPO_ROOT / "bin" / "nwn-common")).load_module()
CONSOLE = SourceFileLoader("nwn_area_editor_under_test__test_safety",
                           str(REPO_ROOT / "bin" / "nwn-area-editor")).load_module()


def f(t, v):
    return {"type": t, "value": v}


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_common_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hist = os.path.join(self.tmp, "h")
        self.file = os.path.join(self.tmp, "a.json")

    def write(self, text):
        with open(self.file, "w") as fh:
            fh.write(text)

    def test_token_is_bound_to_session_and_secret(self):
        g = COMMON.CsrfGuard()
        sid = g.new_sid()
        self.assertTrue(g.verify(sid, g.token(sid)))
        self.assertFalse(g.verify(sid, g.token(g.new_sid())))
        self.assertFalse(g.verify("", g.token(sid)))
        self.assertFalse(g.verify(sid, ""))
        self.assertFalse(COMMON.CsrfGuard().verify(sid, g.token(sid)))

    def test_cookie_parsing_rejects_junk(self):
        sid = "a" * 32
        self.assertEqual(COMMON.CsrfGuard.sid_from_cookie(
            "x=1; qnm_sid=%s; y=2" % sid), sid)
        self.assertEqual(COMMON.CsrfGuard.sid_from_cookie("qnm_sid=short"), "")
        self.assertEqual(COMMON.CsrfGuard.sid_from_cookie(None), "")

    def test_inject_adds_hidden_fields_to_post_forms_only(self):
        g = COMMON.CsrfGuard()
        out = g.inject("<form method='post' action='/x'><b>a</b></form>"
                       "<form method='get'></form>", "b" * 32)
        self.assertEqual(out.count("name='_csrf'"), 1)
        self.assertEqual(out.count("name='_rendered'"), 1)

    def test_rendered_takes_the_earliest_value(self):
        self.assertEqual(COMMON.rendered_from_form(
            {"_rendered": ["200.5", "100.25", "junk"]}), 100.25)
        self.assertIsNone(COMMON.rendered_from_form({}))

    def test_check_stale(self):
        self.write("{}")
        mtime = os.path.getmtime(self.file)
        COMMON.check_stale(self.file, None)                 # no render time
        COMMON.check_stale(self.file, mtime + 1)            # rendered after
        COMMON.check_stale(os.path.join(self.tmp, "nope"), 1.0)
        with self.assertRaises(COMMON.StaleEditError):
            COMMON.check_stale(self.file, mtime - 1)
        COMMON.check_stale(self.file, mtime - 1, {os.path.abspath(self.file)})

    def test_history_only_for_real_projects(self):
        self.assertIsNone(COMMON.history_dir(self.tmp))
        open(os.path.join(self.tmp, "nasher.cfg"), "w").close()
        self.assertTrue(COMMON.history_dir(self.tmp).endswith("history"))

    def test_snapshot_dedupes_prunes_and_restores(self):
        self.write("v0")
        for i in range(1, 15):
            self.assertTrue(COMMON.snapshot(self.file, self.hist, keep=5))
            self.assertIsNone(COMMON.snapshot(self.file, self.hist, keep=5))
            self.write("v%d" % i)
        entries = COMMON.list_history(self.hist)
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["name"], "a.json")
        newest = entries[0]
        COMMON.restore(self.hist, newest["key"], newest["stamp"])
        self.assertEqual(open(self.file).read(), "v13")
        # the restore snapshotted what it replaced, so it can be undone too
        self.assertEqual(open(COMMON.list_history(self.hist)[0]["snap"]).read(), "v14")

    def test_restore_rejects_path_tricks(self):
        for key, stamp in (("../../etc", "20200101T000000-000"),
                           ("0123456789-a", "../x"), ("0123456789-a", "nope")):
            with self.assertRaises(ValueError):
                COMMON.restore(self.hist, key, stamp)


class ConsoleSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj = tempfile.mkdtemp(prefix="qnm_safety_")
        open(os.path.join(cls.proj, "nasher.cfg"), "w").close()
        cls.unpacked = os.path.join(cls.proj, "unpacked")
        os.makedirs(cls.unpacked)
        cls.ifo = os.path.join(cls.unpacked, "module.ifo.json")
        with open(cls.ifo, "w") as fh:
            json.dump({"__data_type": "IFO ",
                       "Mod_Name": f("cexolocstring", {"0": "M"}),
                       "Mod_Description": f("cexolocstring", {"0": "d"}),
                       "Mod_XPScale": f("byte", 10)}, fh)
        cls.port = 18396
        cls._old_argv = sys.argv
        sys.argv = ["nwn-area-editor", "--dir", cls.unpacked,
                    "--host", "127.0.0.1", "--port", str(cls.port)]
        threading.Thread(target=CONSOLE.main, daemon=True).start()
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/module" % cls.port,
                                       timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("test console server did not start in time")

    @classmethod
    def tearDownClass(cls):
        sys.argv = cls._old_argv
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/shutdown" % cls.port,
                                   data=b"", timeout=2)
        except Exception:
            pass
        shutil.rmtree(cls.proj, ignore_errors=True)

    def setUp(self):
        self.c = Client(self.port, "/module")

    def xp(self):
        with open(self.ifo) as fh:
            return json.load(fh)["Mod_XPScale"]["value"]

    def set_xp(self, v):
        with open(self.ifo) as fh:
            d = json.load(fh)
        d["Mod_XPScale"]["value"] = v
        with open(self.ifo, "w") as fh:
            json.dump(d, fh)

    def post_status(self, **kw):
        try:
            self.c.post("/module/apply", {"Mod_XPScale": "25"}, **kw)
            return 200
        except urllib.error.HTTPError as e:
            return e.code

    def test_pages_carry_a_token_and_a_session_cookie(self):
        self.assertIn("name='_csrf'", self.c.get("/module"))

    def test_post_without_token_is_rejected_and_changes_nothing(self):
        self.set_xp(10)
        self.assertEqual(self.post_status(token=False), 403)
        self.assertEqual(self.xp(), 10)

    def test_post_with_a_wrong_token_is_rejected(self):
        self.c.get("/module")
        self.c.token = "0" * 64
        self.set_xp(10)
        self.assertEqual(self.post_status(), 403)
        self.assertEqual(self.xp(), 10)

    def test_valid_post_applies_and_is_recorded_in_history(self):
        self.set_xp(10)
        self.assertEqual(self.post_status(), 200)
        self.assertEqual(self.xp(), 25)
        page = self.c.get("/history")
        self.assertIn("module.ifo.json", page)
        hist = COMMON.history_dir(self.proj)
        entry = COMMON.list_history(hist)[0]
        self.c.post("/history/restore", {"key": entry["key"],
                                         "stamp": entry["stamp"]})
        self.assertEqual(self.xp(), 10)

    def test_stale_form_is_refused_and_changes_nothing(self):
        self.set_xp(10)
        self.c.get("/module")
        old = time.time() - 3600           # form "rendered" an hour ago
        self.assertEqual(self.post_status(rendered=old), 409)
        self.assertEqual(self.xp(), 10)

    def test_restore_of_a_changed_file_is_refused_when_stale(self):
        self.set_xp(10)
        self.post_status()
        entry = COMMON.list_history(COMMON.history_dir(self.proj))[0]
        self.c.get("/history")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.c.post("/history/restore", {"key": entry["key"],
                                             "stamp": entry["stamp"]},
                        rendered=time.time() - 3600)
        self.assertEqual(cm.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
