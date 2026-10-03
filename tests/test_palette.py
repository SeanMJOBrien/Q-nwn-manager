#!/usr/bin/env python3
"""Tests for bin/nwn-palette and the console's Palettes pages.

Synthetic *palcus.itp.json fixtures shaped like real nwn_gff output. The
properties that matter: edits keep every struct named (NAME or STRREF), folder
IDs stay unique, PaletteID-255 blueprints are never filed, and an edit that
would introduce a structural problem is refused rather than saved.

Run: python3 tests/test_palette.py
"""
import json
import os
import shutil
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAL = SourceFileLoader("nwn_palette_under_test",
                       str(REPO_ROOT / "bin" / "nwn-palette")).load_module()
CONSOLE = SourceFileLoader("nwn_area_editor_under_test__test_palette",
                           str(REPO_ROOT / "bin" / "nwn-area-editor")).load_module()


def f(t, v):
    return {"type": t, "value": v}


def leaf(resref, name=None, strref=None):
    d = {"__struct_id": 0, "RESREF": f("resref", resref)}
    if name:
        d["NAME"] = f("cexostring", name)
    if strref is not None:
        d["STRREF"] = f("dword", strref)
    return d


def folder(pid, name, kids=None, strref=None):
    d = {"__struct_id": 0}
    if pid is not None:
        d["ID"] = f("byte", pid)
    if name:
        d["NAME"] = f("cexostring", name)
    if strref is not None:
        d["STRREF"] = f("dword", strref)
    if kids is not None:
        d["LIST"] = f("list", kids)
    return d


def palette(*top):
    return {"__data_type": "ITP ", "MAIN": f("list", list(top))}


def blueprint(name, **extra):
    d = {"LocalizedName": f("cexolocstring", {"0": name})}
    d.update(extra)
    return d


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.write("itempalcus.itp.json", palette(
            folder(None, None, [
                folder(1, "Armor", [leaf("helm1", "Helm"), leaf("shield1", None, 55)]),
                folder(2, "Empty")], strref=100),
            folder(3, None, strref=200)))
        self.write("helm1.uti.json", blueprint("Helm"))
        self.write("sword1.uti.json", blueprint("Sword"))
        self.write("secret.uti.json", blueprint("Secret", PaletteID=f("byte", 255)))

    def write(self, name, doc):
        with open(os.path.join(self.root, name), "w") as fh:
            json.dump(doc, fh)

    def doc(self):
        return PAL.load(self.root, "item")

    def test_unlisted_skips_listed_and_excluded(self):
        self.assertEqual([r for r, _ in PAL.unlisted(self.root, "item", self.doc())],
                         ["sword1"])

    def test_sync_creates_custom_folder_with_unique_id(self):
        d = self.doc()
        PAL.sync(d, "item", self.root)
        custom = PAL.custom_folder(d)
        self.assertEqual(PAL.node_name(custom), "Custom")
        self.assertEqual(PAL.children(custom)[0]["RESREF"]["value"], "sword1")
        self.assertEqual(PAL.validate(d), [])
        self.assertEqual(PAL.unlisted(self.root, "item", d), [])

    def test_excluded_blueprint_refused(self):
        d = self.doc()
        with self.assertRaises(PAL.PaletteError):
            PAL.add_blueprint(d, "item", self.root,
                              PAL.find_folder(d, "Armor"), "secret")

    def test_rename_strref_node_replaces_strref(self):
        d = self.doc()
        node = PAL.find_node(d, "shield1")
        PAL.rename(d, node, "Shield")
        self.assertNotIn("STRREF", node)
        self.assertEqual(PAL.node_name(node), "Shield")

    def test_delete_empties_list_on_id_folder(self):
        d = self.doc()
        PAL.delete(d, [PAL.find_node(d, "helm1"), PAL.find_node(d, "shield1")])
        self.assertNotIn("LIST", PAL.find_node(d, "Armor"))

    def test_move_rules(self):
        d = self.doc()
        armor = PAL.find_node(d, "Armor")
        with self.assertRaises(PAL.PaletteError):
            PAL.move_into(d, [armor], armor)
        with self.assertRaises(PAL.PaletteError):
            PAL.move_into(d, [PAL.find_node(d, "helm1")], None)
        PAL.move_into(d, [PAL.find_node(d, "helm1")], PAL.find_folder(d, "Empty"))
        self.assertEqual(PAL.node_name(PAL.children(PAL.find_node(d, "Empty"))[0]), "Helm")

    def test_next_id_and_move_by(self):
        d = self.doc()
        PAL.add_folder(d, None, "New")
        self.assertEqual(PAL.find_node(d, "New")["ID"]["value"], 4)
        PAL.move_by(d, PAL.find_node(d, "New"), -1)
        self.assertEqual(PAL.node_name(PAL.top(d)[1]), "New")

    def test_validate_flags_duplicate_id_and_unnamed(self):
        d = self.doc()
        PAL.top(d)[1]["ID"]["value"] = 1
        del PAL.find_node(d, "Empty")["NAME"]
        issues = " ".join(PAL.validate(d))
        self.assertIn("already used", issues)
        self.assertIn("no NAME or STRREF", issues)

    def test_creature_leaf_gets_cr_and_faction(self):
        self.write("creaturepalcus.itp.json", palette(
            folder(None, None, [folder(1, "Mobs", [
                {"__struct_id": 0, "NAME": f("cexostring", "Rat"),
                 "RESREF": f("resref", "rat"), "CR": f("float", 1.0),
                 "FACTION": f("cexostring", "Defender")}])])))
        self.write("wolf.utc.json", {"FirstName": f("cexolocstring", {"0": "Wolf"}),
                                     "ChallengeRating": f("float", 3.0)})
        d = PAL.load(self.root, "creature")
        PAL.sync(d, "creature", self.root, PAL.find_folder(d, "Mobs"))
        wolf = PAL.find_node(d, "wolf")
        self.assertEqual(wolf["CR"]["value"], 3.0)
        self.assertEqual(wolf["FACTION"]["value"], "Defender")

    def test_cli_refuses_only_introduced_issues_and_dry_run(self):
        # pre-existing duplicate ID must not block an unrelated edit
        d = self.doc()
        PAL.top(d)[1]["ID"]["value"] = 1
        PAL.save(self.root, "item", d)
        self.assertEqual(PAL.main(["--dir", self.root, "mkdir", "item", "/", "X"]), 0)
        before = open(PAL.palette_path(self.root, "item")).read()
        self.assertEqual(PAL.main(["--dir", self.root, "rm", "item", "Armor",
                                   "--dry-run"]), 0)
        self.assertEqual(open(PAL.palette_path(self.root, "item")).read(), before)
        self.assertEqual(PAL.main(["--dir", self.root, "rm", "item", "nope"]), 1)

    def test_console_apply_and_render(self):
        page = CONSOLE.render_palette(self.root, "item")
        self.assertIn("Armor", page)
        self.assertIn("sword1", page)  # listed as missing
        msg = CONSOLE.apply_palette(self.root, {
            "p": ["item"], "op": ["rename"], "sel": ["0.0"], "name": ["Gear"]})
        self.assertIn("Gear", msg)
        self.assertEqual(PAL.node_name(PAL.top(self.doc())[0]["LIST"]["value"][0]), "Gear")
        with self.assertRaises(CONSOLE.palette_lib().PaletteError):
            CONSOLE.apply_palette(self.root, {
                "p": ["item"], "op": ["rename"], "sel": ["0.0", "0.1"], "name": ["x"]})
        CONSOLE.apply_palette(self.root, {"p": ["item"], "op": ["sync"],
                                          "pick": ["sword1"], "target": [""]})
        self.assertEqual(PAL.unlisted(self.root, "item", self.doc()), [])


if __name__ == "__main__":
    unittest.main()
