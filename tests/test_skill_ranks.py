#!/usr/bin/env python3
"""Tests for creature/character skill-rank editing.

Covers both editors, since SkillList handling is duplicated between them:
bin/nwn-area-editor (the console, working on .utc.json) and
skills/nwn-web-editor/scripts/nwn_web_editor.py (the standalone .bic editor).

SkillList is POSITIONAL - entry N is row N of skills.2da and carries nothing
but its Rank, so the index *is* the skill identity. Every test here is
ultimately about that invariant: ranks are written in place, and the list is
never appended to, shortened, or reordered.

Run all tests:
    python3 tests/test_skill_ranks.py

Run one case:
    python3 -m unittest tests.test_skill_ranks.SkillRankTests.test_out_of_range_index_never_grows_the_list
"""
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSOLE = SourceFileLoader(
    "nwn_area_editor_under_test__test_skill_ranks",
    str(REPO_ROOT / "bin" / "nwn-area-editor")
).load_module()
WEB = SourceFileLoader(
    "nwn_web_editor_under_test__test_skill_ranks",
    str(REPO_ROOT / "skills" / "nwn-web-editor" / "scripts" / "nwn_web_editor.py")
).load_module()

# skills.2da rows that the bundled stock table is expected to name.
KNOWN_SKILL_ROWS = {0: "Animal Empathy", 1: "Concentration", 3: "Discipline"}


def make_creature(ranks):
    return {
        "__data_type": "UTC ",
        "FirstName": {"type": "cexolocstring", "value": {"0": "Test"}},
        "LastName": {"type": "cexolocstring", "value": {"0": ""}},
        "Tag": {"type": "cexostring", "value": "test"},
        "SkillList": {"type": "list", "value": [
            {"__struct_id": 0, "Rank": {"type": "byte", "value": r}}
            for r in ranks]},
    }


def ranks_of(d):
    return [CONSOLE.getv(e, "Rank") for e in CONSOLE.getv(d, "SkillList", [])]


class SkillRankTests(unittest.TestCase):
    """Direct tests against the console's apply_char_edits."""

    def _apply(self, d, form):
        return CONSOLE.apply_char_edits(d, form)

    def test_rank_written_at_the_right_index(self):
        d = make_creature([0] * 28)
        self.assertTrue(self._apply(d, {"skill_3": ["7"]}))
        got = ranks_of(d)
        self.assertEqual(got[3], 7)
        self.assertEqual(sum(got), 7, "only one index should have changed")

    def test_blank_leaves_a_rank_unchanged(self):
        d = make_creature([0, 0, 0, 5] + [0] * 24)
        self._apply(d, {"skill_3": [""], "skill_0": ["2"]})
        got = ranks_of(d)
        self.assertEqual(got[3], 5)
        self.assertEqual(got[0], 2)

    def test_rank_can_be_zeroed(self):
        d = make_creature([9] + [0] * 27)
        self.assertTrue(self._apply(d, {"skill_0": ["0"]}))
        self.assertEqual(ranks_of(d)[0], 0)

    def test_unchanged_value_does_not_report_a_change(self):
        d = make_creature([4] + [0] * 27)
        self.assertFalse(self._apply(d, {"skill_0": ["4"]}))

    def test_list_length_and_order_are_preserved(self):
        d = make_creature(list(range(28)))
        self._apply(d, {"skill_10": ["99"]})
        got = ranks_of(d)
        self.assertEqual(len(got), 28)
        expected = list(range(28))
        expected[10] = 99
        self.assertEqual(got, expected)

    def test_out_of_range_index_never_grows_the_list(self):
        """A hak-extended skills.2da on the rendering side must not be able to
        append entries the creature's own list doesn't have."""
        d = make_creature([0] * 28)
        self.assertFalse(self._apply(d, {"skill_99": ["5"]}))
        self.assertEqual(len(ranks_of(d)), 28)

    def test_short_skill_list_is_not_extended(self):
        d = make_creature([0] * 4)
        self._apply(d, {"skill_0": ["1"], "skill_9": ["5"]})
        got = ranks_of(d)
        self.assertEqual(len(got), 4)
        self.assertEqual(got[0], 1)

    def test_missing_skill_list_is_left_absent(self):
        d = make_creature([])
        del d["SkillList"]
        self.assertFalse(self._apply(d, {"skill_0": ["3"]}))
        self.assertNotIn("SkillList", d)

    def test_struct_id_is_preserved(self):
        d = make_creature([0] * 28)
        self._apply(d, {"skill_2": ["6"]})
        self.assertEqual(d["SkillList"]["value"][2]["__struct_id"], 0)


class SkillNameLookupTests(unittest.TestCase):
    def test_stock_rows_resolve_to_names_in_both_editors(self):
        for row, name in KNOWN_SKILL_ROWS.items():
            self.assertEqual(CONSOLE.skill_name(row), name)
            self.assertEqual(WEB.skill_name(row), name)

    def test_unknown_row_falls_back_to_the_raw_index(self):
        self.assertEqual(CONSOLE.skill_name(999), "skill 999")
        self.assertEqual(WEB.skill_name(999), "skill 999")


class SkillFormRenderingTests(unittest.TestCase):
    def test_console_renders_one_input_per_entry_in_file_order(self):
        html = CONSOLE.render_skills_html(make_creature([0] * 28))
        self.assertEqual(html.count("<input"), 28)
        for row, name in KNOWN_SKILL_ROWS.items():
            self.assertIn("name='skill_%d'" % row, html)
            self.assertIn(name, html)
        # file order, not alphabetical
        self.assertLess(html.index("name='skill_0'"), html.index("name='skill_3'"))

    def test_web_editor_renders_the_same_field_names(self):
        html = WEB.render_skills_html(make_creature([0] * 28))
        self.assertEqual(html.count("<input"), 28)
        self.assertIn("name='skill_3'", html)

    def test_absent_skill_list_renders_an_explanation_not_inputs(self):
        d = make_creature([])
        del d["SkillList"]
        for mod in (CONSOLE, WEB):
            html = mod.render_skills_html(d)
            self.assertNotIn("<input", html)
            self.assertIn("No SkillList", html)

    def test_current_ranks_are_prefilled(self):
        html = CONSOLE.render_skills_html(make_creature([0, 0, 0, 12] + [0] * 24))
        self.assertIn("name='skill_3' value='12'", html)


class WebEditorSkillApplyTests(unittest.TestCase):
    """The .bic editor duplicates the apply logic, so it needs its own coverage
    rather than relying on the console's."""

    def test_ranks_apply_in_place(self):
        d = make_creature([0] * 28)
        self.assertTrue(WEB.apply_char_edits(d, {"skill_5": ["8"]}, False))
        got = [WEB.getv(e, "Rank") for e in WEB.getv(d, "SkillList", [])]
        self.assertEqual(got[5], 8)
        self.assertEqual(len(got), 28)

    def test_out_of_range_index_ignored(self):
        d = make_creature([0] * 28)
        self.assertFalse(WEB.apply_char_edits(d, {"skill_99": ["8"]}, False))
        self.assertEqual(len(WEB.getv(d, "SkillList", [])), 28)


if __name__ == "__main__":
    unittest.main()
