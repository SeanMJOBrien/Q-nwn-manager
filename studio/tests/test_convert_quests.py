"""Converting older (slot-numbered) quest dialogs to parameterized scripts."""

from __future__ import annotations

import unittest

from tests.fixture import MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import convert_quests as CQ
from tfnstudio import dialogs as D
from tfnstudio import gffjson as G
from tfnstudio.changeset import ChangeSet


def old_style_dialog(extra_params: bool = False) -> str:
    b = D.DialogBuilder()
    offer = b.add_entry("Help me?", comment="t")
    yes = b.add_reply("Yes.")
    done = b.add_entry("Thanks.", script="dlg_q_adv3", comment="t")
    b.entry_to_reply(offer, yes)
    b.reply_to_entry(yes, done, active="dlg_q_chk_eli3")
    b.add_start(done, active="dlg_q_chk_atc2")
    b.add_start(offer, active="dlg_q_chk_eli1", params={"npc_tag": "x"} if extra_params else None)
    return G.dumps(b.finish())


class ConvertTests(MiniTfnCase):
    def setUp(self):
        self.p = self.project()
        self.dlg = self.root / "src" / "dlg"
        self.dlg.mkdir(parents=True, exist_ok=True)

    def put(self, name: str, text: str) -> None:
        (self.dlg / f"{name}.dlg.json").write_text(text, encoding="utf-8")

    def run_convert(self, only):
        cs = ChangeSet(self.p, "convert", "misc")
        return cs, CQ.convert_project(self.p, cs, only)

    def test_real_scripts_are_verified(self):
        v = CQ.verify_scripts(self.p)
        for fam in CQ.FAMILIES:
            self.assertTrue(v[fam]["ok"], (fam, v[fam]))

    def test_converts_and_preserves_meaning(self):
        self.put("t_old", old_style_dialog())
        cs, rep = self.run_convert(["t_old"])
        self.assertEqual((rep["dialogs_changed"], rep["calls_converted"]), (1, 4))
        new = cs.load("dlg", "t_old")
        outline = D.flatten(new)
        self.assertIn("{runs: dlg_q_adv(target=3)}", outline)
        self.assertIn("[if: dlg_q_chk_eli(target=3)]", outline)
        self.assertIn("[if: dlg_q_chk_at(target=2)]", outline)
        self.assertIn("[if: dlg_q_chk_eli(target=1)]", outline)
        self.assertNotRegex(G.dumps(new), r"dlg_q_(adv|chk_eli|chk_atc|chk_atp|chk_advb)[1-9]")
        old = G.loads(old_style_dialog())
        self.assertEqual(CQ.effective_calls(old), CQ.effective_calls(new))
        self.assertIsNotNone(cs.pending_text(cs.rel_nss("dlg_q_chk_at")))   # shipped for the atc nodes

    def test_node_with_existing_params_is_left_alone(self):
        self.put("t_params", old_style_dialog(extra_params=True))
        cs, rep = self.run_convert(["t_params"])
        d = rep["dialogs"][0]
        self.assertEqual(d["skipped_with_params"], ["dlg_q_chk_eli1"])
        self.assertEqual(d["converted"], 3)
        self.assertIn("dlg_q_chk_eli1", G.dumps(cs.load("dlg", "t_params")))

    def test_dialog_that_does_not_round_trip_is_refused(self):
        self.put("t_odd", old_style_dialog().replace("\n  ", "\n    ", 1))
        cs, rep = self.run_convert(["t_odd"])
        self.assertIn("round-trip", rep["dialogs"][0]["refused"])
        self.assertEqual(rep["dialogs_changed"], 0)
        self.assertEqual(cs.changed_files(), [])

    def test_untouched_dialogs_are_not_in_the_change_set(self):
        self.put("t_plain", G.dumps(D.new_dialog()))
        cs, rep = self.run_convert(["t_plain"])
        self.assertEqual(rep["dialogs"], [])
        self.assertEqual(cs.changed_files(), [])

    def test_unverified_family_is_not_converted(self):
        # a numbered script that is NOT the generic one with the slot filled in must be left alone
        nss = self.root / "src" / "nss" / "dlg_q_adv3.nss"
        original = nss.read_text()
        try:
            nss.write_text(original.replace("AdvanceQuest(OBJECT_SELF, oPC, 3);", "AdvanceQuest(OBJECT_SELF, oPC, 4);"))
            self.put("t_old", old_style_dialog())
            cs, rep = self.run_convert(["t_old"])
            self.assertFalse(rep["scripts"]["dlg_q_adv"]["ok"])
            self.assertIn("dlg_q_adv3", rep["dialogs"][0]["skipped_unverified_family"])
            self.assertIn("dlg_q_adv3", G.dumps(cs.load("dlg", "t_old")))
        finally:
            nss.write_text(original)


if __name__ == "__main__":
    unittest.main()
