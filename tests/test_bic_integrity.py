#!/usr/bin/env python3
"""Tests for .bic character editing in skills/nwn-web-editor/scripts/nwn_web_editor.py.

Two halves:

  * check_bic_integrity - cross-checks LvlStatList (the engine's own level-up
    audit trail) against the character's current classes, skills and feats. The
    important property is that it *reports* and never rewrites: silently
    "fixing" LvlStatList to match an edit is how you produce a character the
    client refuses to load.
  * apply_bic_edits - the safe editable subset (classes, alignment, text
    fields, carried items, quickbar clear).

Fixtures mirror the real .bic shape: a positional 28-entry SkillList of ranks,
per-level SkillList entries recording rank *gains*, and per-level FeatList
entries recording which feats each level granted.

Run all tests:
    python3 tests/test_bic_integrity.py

Run one case:
    python3 -m unittest tests.test_bic_integrity.IntegrityTests.test_clean_character_reports_nothing
"""
import copy
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB = SourceFileLoader(
    "nwn_web_editor_under_test__test_bic_integrity",
    str(REPO_ROOT / "skills" / "nwn-web-editor" / "scripts" / "nwn_web_editor.py")
).load_module()

NUM_SKILLS = 28


def _field(gff_type, value):
    return {"type": gff_type, "value": value}


def _skill_list(ranks):
    padded = list(ranks) + [0] * (NUM_SKILLS - len(ranks))
    return _field("list", [{"__struct_id": 0, "Rank": _field("byte", r)}
                           for r in padded])


def _feat_list(feats):
    return _field("list", [{"__struct_id": 0, "Feat": _field("word", n)}
                           for n in feats])


def make_level(class_id, hit_die=10, skill_gains=(), feats=()):
    return {
        "__struct_id": 0,
        "EpicLevel": _field("byte", 0),
        "LvlStatClass": _field("byte", class_id),
        "LvlStatHitDie": _field("byte", hit_die),
        "SkillPoints": _field("word", 0),
        "SkillList": _skill_list(skill_gains),
        "FeatList": _feat_list(feats),
    }


def make_bic():
    """A consistent 3rd-level fighter: three level-ups, ranks and feats that
    add up exactly to what the character carries."""
    return {
        "__data_type": "BIC ",
        "FirstName": _field("cexolocstring", {"0": "Test"}),
        "LastName": _field("cexolocstring", {"0": "Character"}),
        "Tag": _field("cexostring", ""),
        "Deity": _field("cexostring", "Tyr"),
        "Description": _field("cexolocstring", {"0": "a hero"}),
        "GoodEvil": _field("byte", 85),
        "LawfulChaotic": _field("byte", 50),
        "Experience": _field("dword", 3000),
        "Gold": _field("dword", 100),
        "ClassList": _field("list", [
            {"__struct_id": 2, "Class": _field("int", 4),
             "ClassLevel": _field("short", 3)}]),
        # totals: skill 1 -> 3 ranks, skill 3 -> 2 ranks; feats {2, 28, 45}
        "SkillList": _skill_list([0, 3, 0, 2]),
        "FeatList": _feat_list([2, 28, 45]),
        "LvlStatList": _field("list", [
            make_level(4, skill_gains=[0, 1, 0, 2], feats=[2, 28]),
            make_level(4, skill_gains=[0, 1], feats=[]),
            make_level(4, skill_gains=[0, 1], feats=[45]),
        ]),
        "ItemList": _field("list", [
            {"__struct_id": 0, "BaseItem": _field("int", 3),
             "LocalizedName": _field("cexolocstring", {"0": "Sword"})},
            {"__struct_id": 0, "BaseItem": _field("int", 5),
             "LocalizedName": _field("cexolocstring", {"0": "Shield"})},
        ]),
        "QBList": _field("list", [
            {"__struct_id": 0, "QBObjectType": _field("byte", 1),
             "QBItemInvSlot": _field("dword", 4)}
            for _ in range(36)]),
    }


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.d = make_bic()

    def _findings(self):
        return WEB.check_bic_integrity(self.d)

    def test_clean_character_reports_nothing(self):
        """The negative control - if this ever fails, every other case here is
        meaningless."""
        self.assertEqual(self._findings(), [])

    def test_class_level_mismatch_is_reported(self):
        self.d["ClassList"]["value"][0]["ClassLevel"]["value"] = 5
        findings = self._findings()
        self.assertTrue(any("LvlStatList records 3" in f for f in findings))
        self.assertTrue(any("Fighter" in f for f in findings))

    def test_skill_rank_mismatch_is_reported(self):
        self.d["SkillList"]["value"][1]["Rank"]["value"] = 9
        findings = self._findings()
        self.assertTrue(
            any("Concentration" in f and "9 rank(s)" in f for f in findings),
            findings)

    def test_orphan_top_level_feat_is_reported(self):
        self.d["FeatList"]["value"].append(
            {"__struct_id": 0, "Feat": _field("word", 411)})
        findings = self._findings()
        self.assertTrue(any("411" in f and "never granted" in f
                            for f in findings), findings)

    def test_feat_granted_but_missing_is_reported(self):
        self.d["FeatList"]["value"] = [
            e for e in self.d["FeatList"]["value"]
            if WEB.getv(e, "Feat") != 45]
        findings = self._findings()
        self.assertTrue(any("45" in f and "missing" in f for f in findings),
                        findings)

    def test_class_absent_from_class_list_is_reported(self):
        self.d["LvlStatList"]["value"][2]["LvlStatClass"]["value"] = 10
        findings = self._findings()
        self.assertTrue(any("isn't in ClassList" in f for f in findings),
                        findings)

    def test_multiclass_character_is_clean(self):
        self.d["ClassList"]["value"] = [
            {"__struct_id": 2, "Class": _field("int", 4),
             "ClassLevel": _field("short", 2)},
            {"__struct_id": 2, "Class": _field("int", 10),
             "ClassLevel": _field("short", 1)},
        ]
        self.d["LvlStatList"]["value"][2]["LvlStatClass"]["value"] = 10
        self.assertEqual(self._findings(), [])

    def test_check_never_mutates_the_character(self):
        self.d["ClassList"]["value"][0]["ClassLevel"]["value"] = 7
        before = copy.deepcopy(self.d)
        WEB.check_bic_integrity(self.d)
        self.assertEqual(self.d, before)

    def test_file_without_level_history_is_skipped(self):
        """A .utc blueprint has no LvlStatList; that's not an inconsistency."""
        del self.d["LvlStatList"]
        self.assertEqual(self._findings(), [])

    def test_findings_render_as_warnings(self):
        self.d["SkillList"]["value"][1]["Rank"]["value"] = 9
        html = WEB.render_integrity_html(self.d)
        self.assertIn("warn", html)
        self.assertIn("Concentration", html)

    def test_clean_character_renders_an_ok_message(self):
        html = WEB.render_integrity_html(self.d)
        self.assertIn("ok", html)
        self.assertIn("consistent", html)


class BicEditTests(unittest.TestCase):
    def setUp(self):
        self.d = make_bic()

    def test_class_id_and_level_are_written(self):
        self.assertTrue(WEB.apply_bic_edits(
            self.d, {"class_0_id": ["10"], "class_0_level": ["4"]}))
        entry = self.d["ClassList"]["value"][0]
        self.assertEqual(WEB.getv(entry, "Class"), 10)
        self.assertEqual(WEB.getv(entry, "ClassLevel"), 4)

    def test_class_known_spells_are_left_alone(self):
        self.d["ClassList"]["value"][0]["KnownList0"] = _field(
            "list", [{"__struct_id": 3, "Spell": _field("word", 37)}])
        WEB.apply_bic_edits(self.d, {"class_0_level": ["4"]})
        self.assertEqual(
            len(self.d["ClassList"]["value"][0]["KnownList0"]["value"]), 1)

    def test_blank_class_field_leaves_it_unchanged(self):
        self.assertFalse(WEB.apply_bic_edits(
            self.d, {"class_0_id": [""], "class_0_level": ["  "]}))
        self.assertEqual(
            WEB.getv(self.d["ClassList"]["value"][0], "ClassLevel"), 3)

    def test_alignment_is_written_through_apply_char_edits(self):
        self.assertTrue(WEB.apply_char_edits(
            self.d, {"GoodEvil": ["20"], "LawfulChaotic": ["100"]}, True))
        self.assertEqual(WEB.getv(self.d, "GoodEvil"), 20)
        self.assertEqual(WEB.getv(self.d, "LawfulChaotic"), 100)

    def test_alignment_is_not_offered_for_a_utc(self):
        self.assertFalse(WEB.apply_char_edits(self.d, {"GoodEvil": ["20"]}, False))
        self.assertEqual(WEB.getv(self.d, "GoodEvil"), 85)

    def test_deity_and_description_are_written(self):
        self.assertTrue(WEB.apply_bic_edits(
            self.d, {"Deity": ["Helm"], "Description": ["rewritten"]}))
        self.assertEqual(WEB.getv(self.d, "Deity"), "Helm")
        self.assertEqual(WEB.loc_get(self.d, "Description"), "rewritten")

    def test_absent_text_field_is_never_created(self):
        del self.d["Deity"]
        self.assertFalse(WEB.apply_bic_edits(self.d, {"Deity": ["Helm"]}))
        self.assertNotIn("Deity", self.d)

    def test_carried_items_are_removed_by_index(self):
        self.assertTrue(WEB.apply_bic_edits(self.d, {"delitem": ["0"]}))
        items = WEB.getv(self.d, "ItemList", [])
        self.assertEqual(len(items), 1)
        self.assertEqual(WEB.loc_get(items[0], "LocalizedName"), "Shield")

    def test_removing_several_items_uses_original_indices(self):
        self.d["ItemList"]["value"].append(
            {"__struct_id": 0, "BaseItem": _field("int", 7),
             "LocalizedName": _field("cexolocstring", {"0": "Potion"})})
        WEB.apply_bic_edits(self.d, {"delitem": ["0", "2"]})
        names = [WEB.loc_get(e, "LocalizedName")
                 for e in WEB.getv(self.d, "ItemList", [])]
        self.assertEqual(names, ["Shield"])

    def test_clear_quickbar_empties_slots_but_keeps_the_length(self):
        self.assertTrue(WEB.apply_bic_edits(self.d, {"clear_qb": ["on"]}))
        slots = WEB.getv(self.d, "QBList", [])
        self.assertEqual(len(slots), 36)
        self.assertTrue(all(s == WEB.EMPTY_QB_SLOT for s in slots))

    def test_clear_quickbar_is_idempotent(self):
        WEB.apply_bic_edits(self.d, {"clear_qb": ["on"]})
        self.assertFalse(WEB.apply_bic_edits(self.d, {"clear_qb": ["on"]}))

    def test_cleared_slots_are_independent_objects(self):
        """Shared dicts would make a later per-slot edit change every slot."""
        WEB.apply_bic_edits(self.d, {"clear_qb": ["on"]})
        slots = WEB.getv(self.d, "QBList", [])
        slots[0]["QBObjectType"]["value"] = 5
        self.assertEqual(WEB.getv(slots[1], "QBObjectType"), 0)

    def test_untouched_form_is_a_no_op(self):
        before = copy.deepcopy(self.d)
        self.assertFalse(WEB.apply_bic_edits(self.d, {}))
        self.assertEqual(self.d, before)

    def test_level_history_is_never_written(self):
        before = copy.deepcopy(self.d["LvlStatList"])
        WEB.apply_bic_edits(self.d, {"class_0_level": ["9"], "delitem": ["0"],
                                     "clear_qb": ["on"], "Deity": ["Helm"]})
        self.assertEqual(self.d["LvlStatList"], before)


class BicRenderingTests(unittest.TestCase):
    def setUp(self):
        self.d = make_bic()

    def test_level_table_is_read_only(self):
        html = WEB.render_levels_html(self.d)
        self.assertNotIn("<input", html)
        self.assertIn("Fighter", html)
        self.assertIn("Read-only", html)

    def test_level_table_names_skills_and_feats_gained(self):
        html = WEB.render_levels_html(self.d)
        self.assertIn("Concentration", html)
        self.assertIn("Power Attack", html)   # feat 28

    def test_bic_form_includes_the_bic_only_sections(self):
        html = WEB.render_char_form(self.d, "/bic/apply", "", True)
        for marker in ("Level history", "Quickbar", "Carried items",
                       "Classes", "name='clear_qb'", "name='delitem'",
                       "name='class_0_level'", "name='GoodEvil'"):
            self.assertIn(marker, html)

    def test_utc_form_omits_them(self):
        html = WEB.render_char_form(self.d, "/creature/apply", "", False)
        for marker in ("Level history", "Quickbar", "name='clear_qb'",
                       "name='class_0_level'"):
            self.assertNotIn(marker, html)
        self.assertIn("name='skill_1'", html)

    def test_classes_table_prefills_current_values(self):
        html = WEB.render_classes_html(self.d)
        self.assertIn("name='class_0_id' value='4'", html)
        self.assertIn("name='class_0_level' value='3'", html)
        self.assertIn("Fighter", html)

    def test_inventory_lists_carried_items_only(self):
        self.d["Equip_ItemList"] = _field("list", [
            {"__struct_id": 2,
             "LocalizedName": _field("cexolocstring", {"0": "Worn Armor"})}])
        html = WEB.render_inventory_html(self.d)
        self.assertIn("Sword", html)
        self.assertNotIn("Worn Armor", html)


if __name__ == "__main__":
    unittest.main()
