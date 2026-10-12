#!/usr/bin/env python3
"""Tests for reference-aware area rename in bin/nwn-area-editor (item 8).

A ResRef rename must carry through to module.ifo's Mod_Entry_Area and
Mod_Area_list (the only GFF data that names an area by resref), show those
rows in the preview before anything is written, and never fail the rename
itself. Tag/resref use in .nss source is reported, never rewritten.

Run: python3 tests/test_area_rename_refs.py
"""
import json
import os
import shutil
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader(
    "nwn_area_editor_under_test__test_area_rename_refs",
    str(REPO_ROOT / "bin" / "nwn-area-editor")).load_module()


def f(t, v):
    return {"type": t, "value": v}


def are(res, tag="atag"):
    return {"__data_type": "ARE ", "ResRef": f("resref", res),
            "Name": f("cexolocstring", {"0": "n"}), "Tag": f("cexostring", tag),
            "Flags": f("dword", 0)}


class RenameRefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_renamerefs_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.write_are("old1")
        self.write_are("other")
        self.write_ifo(entry="old1", areas=["old1", "other"])

    def write_are(self, res, tag="atag"):
        with open(os.path.join(self.tmp, res + ".are.json"), "w") as fh:
            json.dump(are(res, tag), fh)

    def write_ifo(self, entry, areas):
        d = {"__data_type": "IFO ", "Mod_Entry_Area": f("resref", entry),
             "Mod_Area_list": f("list", [
                 {"__struct_id": 6, "Area_Name": f("resref", a)} for a in areas])}
        with open(os.path.join(self.tmp, "module.ifo.json"), "w") as fh:
            json.dump(d, fh)

    def ifo(self):
        with open(os.path.join(self.tmp, "module.ifo.json")) as fh:
            return json.load(fh)

    def apply(self, form, dry_run=False):
        return CONSOLE.apply_tags(self.tmp, self.tmp, self.tmp, form,
                                  dry_run=dry_run)

    RENAME = {"res": ["old1"], "ref_old1": ["new1"]}

    def test_rename_rewrites_entry_area_and_area_list(self):
        self.apply(self.RENAME)
        d = self.ifo()
        self.assertEqual(CONSOLE.getv(d, "Mod_Entry_Area"), "new1")
        self.assertEqual([CONSOLE.getv(i, "Area_Name")
                          for i in CONSOLE.getv(d, "Mod_Area_list")],
                         ["new1", "other"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new1.are.json")))

    def test_preview_lists_module_rows_and_writes_nothing(self):
        before = open(os.path.join(self.tmp, "module.ifo.json")).read()
        diffs, errors = self.apply(self.RENAME, dry_run=True)
        fields = [d[1] for d in diffs]
        self.assertIn("module.ifo: Mod_Entry_Area", fields)
        self.assertIn("module.ifo: Mod_Area_list[0]", fields)
        self.assertNotIn("module.ifo: Mod_Area_list[1]", fields)
        self.assertEqual(errors, [])
        self.assertEqual(open(os.path.join(self.tmp, "module.ifo.json")).read(),
                         before)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "old1.are.json")))

    def test_unreferenced_area_adds_no_module_rows_or_write(self):
        self.write_are("solo")
        path = os.path.join(self.tmp, "module.ifo.json")
        before = os.path.getmtime(path)
        diffs, _ = self.apply({"res": ["solo"], "ref_solo": ["solo2"]},
                              dry_run=True)
        self.assertEqual([d[1] for d in diffs if d[1].startswith("module.ifo")], [])
        self.apply({"res": ["solo"], "ref_solo": ["solo2"]})
        self.assertEqual(os.path.getmtime(path), before)
        self.assertFalse(os.path.exists(path + ".bak"))

    def test_no_module_ifo_is_not_an_error(self):
        os.remove(os.path.join(self.tmp, "module.ifo.json"))
        page = self.apply(self.RENAME)
        self.assertIn("Changed 1 of 1", page)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new1.are.json")))

    def test_unreadable_module_ifo_warns_but_rename_succeeds(self):
        with open(os.path.join(self.tmp, "module.ifo.json"), "w") as fh:
            fh.write("{not json")
        page = self.apply(self.RENAME)
        self.assertIn("module.ifo could not be updated", page)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new1.are.json")))

    def test_two_areas_cannot_claim_the_same_new_resref(self):
        diffs, errors = self.apply({"res": ["old1", "other"],
                                    "ref_old1": ["same"], "ref_other": ["same"]},
                                   dry_run=True)
        self.assertEqual(len(errors), 1)
        self.assertIn("already exists", errors[0])

    def test_swap_style_batch_maps_each_old_value_once(self):
        # a->b with b->c in the same batch must not chain a->c
        self.write_ifo(entry="old1", areas=["old1", "other"])
        self.apply({"res": ["old1", "other"], "ref_old1": ["x1"],
                    "ref_other": ["old1x"]})
        d = self.ifo()
        self.assertEqual(CONSOLE.getv(d, "Mod_Entry_Area"), "x1")
        self.assertEqual([CONSOLE.getv(i, "Area_Name")
                          for i in CONSOLE.getv(d, "Mod_Area_list")],
                         ["x1", "old1x"])

    # --- script scan ----------------------------------------------------

    def write_nss(self, name, text):
        with open(os.path.join(self.tmp, name), "w") as fh:
            fh.write(text)

    def test_scan_finds_quoted_old_tag_and_resref(self):
        self.write_nss("s1.nss", 'void main(){ GetObjectByTag("atag");\n'
                                 'GetArea(GetObjectByTag("old1")); }\n')
        self.write_nss("s2.nss", '// "atag" in a comment\nint x = 3;\n')
        hits = CONSOLE.scan_script_references(self.tmp, ["atag", "old1"])
        self.assertEqual({(r, n) for r, n, _ in hits["atag"]},
                         {("s1.nss", 1), ("s2.nss", 1)})
        self.assertEqual([(r, n) for r, n, _ in hits["old1"]], [("s1.nss", 2)])

    def test_scan_ignores_unquoted_substrings(self):
        self.write_nss("s.nss", "int atag_count = 1; // atag\n")
        self.assertEqual(CONSOLE.scan_script_references(self.tmp, ["atag"])["atag"], [])

    def test_result_page_reports_scripts_and_leaves_them_untouched(self):
        src = 'void main(){ GetObjectByTag("atag"); }\n'
        self.write_nss("s1.nss", src)
        page = self.apply({"res": ["old1"], "tag_old1": ["newtag"]})
        self.assertIn("s1.nss:1", page)
        self.assertEqual(open(os.path.join(self.tmp, "s1.nss")).read(), src)

    def test_scan_report_is_capped(self):
        self.write_nss("many.nss", '"atag"\n' * (CONSOLE.SCRIPT_SCAN_CAP + 5))
        html = CONSOLE.render_script_scan(
            CONSOLE.scan_script_references(self.tmp, ["atag"]))
        self.assertIn("+5 more", html)

    def test_no_scripts_reports_clean(self):
        html = CONSOLE.render_script_scan(
            CONSOLE.scan_script_references(self.tmp, ["atag"]))
        self.assertIn("No script", html)

    # --- tags that embed the old area tag/resref ------------------------

    def write_git(self, res, **lists):
        d = {"__data_type": "GIT "}
        for field, tags in lists.items():
            d[field] = f("list", [{"__struct_id": 1, "Tag": f("cexostring", t)}
                                  for t in tags])
        with open(os.path.join(self.tmp, res + ".git.json"), "w") as fh:
            json.dump(d, fh)

    def test_embedded_tag_scan_matches_whole_words_only(self):
        self.write_git("other", WaypointList=["ATAG_VAULT", "downatag",
                                              "atagonist", "ATAG", "x_atag_y"],
                       TriggerList=["Door_ATAG"])
        hits = CONSOLE.scan_embedded_tags(self.tmp, ["atag"])["atag"]
        self.assertEqual(sorted(t for _a, _c, t in hits),
                         ["ATAG", "ATAG_VAULT", "Door_ATAG", "x_atag_y"])
        self.assertEqual({c for _a, c, _t in hits}, {"waypoint", "trigger"})

    def test_embedded_tag_scan_skips_very_short_needles(self):
        self.write_git("other", WaypointList=["go", "GO_HOME"])
        self.assertEqual(CONSOLE.scan_embedded_tags(self.tmp, ["go"]), {})

    def test_rename_result_reports_embedded_tags_without_editing(self):
        self.write_git("other", WaypointList=["ATAG_VAULT"])
        before = open(os.path.join(self.tmp, "other.git.json")).read()
        page = self.apply({"res": ["old1"], "tag_old1": ["newtag"]})
        self.assertIn("ATAG_VAULT", page)
        self.assertEqual(open(os.path.join(self.tmp, "other.git.json")).read(),
                         before)


if __name__ == "__main__":
    unittest.main()
