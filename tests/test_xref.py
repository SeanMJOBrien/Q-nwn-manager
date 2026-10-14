#!/usr/bin/env python3
"""Tests for the console's cross-reference report (find_references / /xref).

Run: python3 tests/test_xref.py
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrf_client import Client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader("nwn_area_editor_under_test__xref",
                           str(REPO_ROOT / "bin" / "nwn-area-editor")).load_module()


def f(t, v):
    return {"type": t, "value": v}


def write(path, doc):
    with open(path, "w") as fh:
        if isinstance(doc, str):
            fh.write(doc)
        else:
            json.dump(doc, fh)


class XrefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_xref_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.un = os.path.join(self.tmp, "unpacked")
        os.makedirs(self.un)
        open(os.path.join(self.tmp, "nasher.cfg"), "w").close()
        write(os.path.join(self.un, "vault.are.json"),
              {"Tag": f("cexostring", "AREA_VAULT"), "OnEnter": f("resref", "vault_enter")})
        write(os.path.join(self.un, "vault.git.json"),
              {"Creature List": f("list", [
                  {"Tag": f("cexostring", "GUARD"),
                   "TemplateResRef": f("resref", "Vault_Guard")}])})
        write(os.path.join(self.un, "vault_guard.utc.json"),
              {"Tag": f("cexostring", "GUARD")})
        write(os.path.join(self.un, "hos1palcus.itp.json"),
              {"MAIN": f("list", [{"RESREF": f("resref", "vault_guard")}])})
        write(os.path.join(self.un, "vault_enter.nss"),
              'void main(){ GetObjectByTag("AREA_VAULT"); }\n')
        write(os.path.join(self.un, "unrelated.are.json"),
              {"Tag": f("cexostring", "AREA_VAULTED")})

    def test_finds_values_paths_definition_and_scripts(self):
        r = CONSOLE.find_references([self.un], "area_vault")
        self.assertEqual([x[0] for x in r["files"]], ["vault.are.json"])
        self.assertEqual(r["files"][0][2], [("Tag", "AREA_VAULT")])
        self.assertEqual([x[0] for x in r["scripts"]], ["vault_enter.nss"])
        r = CONSOLE.find_references([self.un], "Vault_Guard")
        self.assertEqual(r["defined"], ["vault_guard.utc.json"])
        paths = {rel: hits[0][0] for rel, _, hits in r["files"]}
        self.assertEqual(paths["vault.git.json"], "Creature List[0].TemplateResRef")
        self.assertEqual(paths["hos1palcus.itp.json"], "MAIN[0].RESREF")

    def test_exact_match_only_and_short_needle_ignored(self):
        r = CONSOLE.find_references([self.un], "vault")
        self.assertEqual(r["files"], [])
        self.assertEqual(CONSOLE.find_references([self.un], "v")["files"], [])

    def test_same_root_not_scanned_twice(self):
        r = CONSOLE.find_references([self.un, self.un], "guard")
        self.assertEqual(len([x for x in r["files"] if x[0] == "vault.git.json"]), 1)

    def test_bad_json_is_skipped(self):
        write(os.path.join(self.un, "broken.are.json"), '{"Tag": "guard" oops')
        r = CONSOLE.find_references([self.un], "guard")
        self.assertNotIn("broken.are.json", [x[0] for x in r["files"]])

    def test_page_over_http(self):
        port = 18398
        CONSOLE.SINGLE_MODE = True
        CONSOLE.SINGLE_PROJECT = CONSOLE.Project(self.tmp)
        srv = CONSOLE.ThreadingHTTPServer(("127.0.0.1", port), CONSOLE.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        c = Client(port)
        page = c.get("/xref?q=area_vault")
        self.assertIn("vault.are.json", page)
        self.assertIn("vault_enter.nss:1", page)
        self.assertIn("<code>Tag</code> = AREA_VAULT", page)
        self.assertIn("Enter at least", c.get("/xref?q=v"))
        self.assertIn("Finds every place", c.get("/xref"))
        self.assertIn("&lt;script&gt;", c.get("/xref?q=%3Cscript%3E"))


if __name__ == "__main__":
    unittest.main()
