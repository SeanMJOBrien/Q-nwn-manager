"""Quest generation end to end on a mini TFN."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.fixture import MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import dialogs as D
from tfnstudio import gffjson as G
from tfnstudio import instances as I
from tfnstudio import quests as Q
from tfnstudio import validate as V
from tfnstudio.changeset import ChangeSet, apply_changeset, undo_applied

TAG = "q_unit_hunt"

SPEC = {
    "tag": TAG,
    "name": "The Unit Hunt",
    "priority": 2,
    "giver": {"mode": "new", "resref": "marek", "name": "Hunter Marek", "clone_from": "jolie",
              "greeting": "Well met.", "place": {"area": "bandit_cave", "x": 30.0, "y": 30.0, "facing": 90}},
    "stages": [
        {"n": 1, "via": "talk", "journal": "Marek wants the alpha goblin dead.",
         "offer": "A goblin alpha raids my traps. Kill it.", "accept_reply": "Consider it done.",
         "accept": "Good luck.", "decline_reply": "Not today.", "decline": "Pity.",
         "reminder": "Is it dead yet?"},
        {"n": 2, "via": "kill", "journal": "You slew the alpha. Take its pelt.",
         "target": {"mode": "new", "resref": "marek_alpha", "name": "Goblin Alpha", "clone_from": "goblin_chieftain",
                    "place": {"area": "goblin2", "x": 10.0, "y": 10.0, "facing": 0}}},
        {"n": 3, "via": "pickup", "journal": "You hold the pelt. Check the cave entrance.",
         "item": {"resref": "q_alphapelt", "name": "Alpha Pelt", "description": "A mangy pelt.",
                  "dropped_by": "marek_alpha"}},
        {"n": 4, "via": "explore", "journal": "You scouted the cave. Return to Marek.", "area": "bandit_cave"},
        {"n": 5, "via": "talk", "journal": "Marek paid you. The hunt is over.",
         "text": "Splendid! Here is your pay.", "reply": "Thanks.", "done": "Thanks again.",
         "reward": {"xp_tier": 2, "xp_level": 3, "gold": 150, "item": "q_brain"}},
    ],
}


def spec():
    return G.clone(SPEC)


class NormalizeTests(unittest.TestCase):
    def test_rejects_bad_specs(self):
        for mut, msg in (
            (lambda s: s.update(tag="wolves"), "tag"),
            (lambda s: s.update(tag="q_" + "x" * 30), "tag"),
            (lambda s: s["stages"].__setitem__(1, {**s["stages"][1], "n": 3}), "consecutive"),
            (lambda s: s["stages"][0].update(via="kill"), "stage 1"),
            (lambda s: s["stages"][4].__setitem__("reward", {"xp_tier": 2}), "xp_level"),
            (lambda s: s["stages"][4].__setitem__("reward", {"xp_tier": 9, "xp_level": 1}), "xp_tier"),
            (lambda s: s["stages"][0].update(journal=""), "journal"),
            (lambda s: s.update(priority=9), "priority"),
            (lambda s: s["giver"].update(mode="maybe"), "mode"),
        ):
            s = spec()
            mut(s)
            with self.assertRaises(Q.QuestError, msg=msg):
                Q.normalize(s)

    def test_script_style_defaults_to_legacy(self):
        self.assertEqual(Q.normalize(spec())["script_style"], "legacy")
        self.assertEqual(Q.normalize({**spec(), "script_style": "modern"})["script_style"], "modern")
        with self.assertRaises(Q.QuestError):
            Q.normalize({**spec(), "script_style": "newest"})

    def test_describe(self):
        d = Q.describe(spec())
        self.assertEqual([x["stage"] for x in d], [1, 2, 3, 4, 5])
        self.assertIn("kill marek_alpha", d[1]["how"])
        self.assertTrue(d[-1]["end"])


class QuestBuildTests(MiniTfnCase):
    def build(self, s=None):
        p = self.project()
        return p, *Q.QuestBuilder(p).build(s or spec())

    def test_journal_category(self):
        p, cs, _ = self.build()
        jrl = cs.load("jrl", "module")
        cat = next(c for c in jrl["Categories"]["value"] if G.get(c, "Tag") == TAG)
        self.assertEqual(G.get_text(cat, "Name"), "The Unit Hunt")
        self.assertEqual(G.get(cat, "Comment"), Q.MARK)
        ents = cat["EntryList"]["value"]
        self.assertEqual([G.get(e, "ID") for e in ents], [1, 2, 3, 4, 5])
        self.assertEqual([G.get(e, "End") for e in ents], [0, 0, 0, 0, 1])
        self.assertEqual(cat["__struct_id"], len(jrl["Categories"]["value"]) - 1)

    def test_giver_blueprint_and_dialog(self):
        p, cs, report = self.build()
        npc = cs.load("utc", "marek")
        self.assertEqual(G.get(npc, "Conversation"), "marek")
        self.assertEqual(G.get(npc, "Plot"), 1)
        self.assertEqual(G.get_text(npc, "FirstName"), "Hunter Marek")
        v = G.vars_of(npc)
        self.assertEqual(v["quest1"], f"01_{TAG}")
        self.assertEqual(v["quest2"], f"05_{TAG}")
        self.assertEqual((v["quest2_reward_xp_tier"], v["quest2_reward_xp_level"], v["quest2_reward_gold"]), (2, 3, 150))
        self.assertEqual(v["quest2_reward_item"], "q_brain")
        self.assertNotIn("quest3", v)
        dlg = cs.load("dlg", "marek")
        starts = [(G.get(s, "Active"), [(G.get(p_, "Key"), G.get(p_, "Value")) for p_ in s["ConditionParams"]["value"]])
                  for s in dlg["StartingList"]["value"]]
        self.assertEqual(starts[0], ("dlg_q_chk_eli", [("target", "2")]))     # turn-in first
        self.assertEqual(starts[-1], ("", []))                               # greeting fallback last
        actives = [a for a, _ in starts]
        self.assertIn("dlg_q_chk_atc1", actives)                              # reminder after accepting
        self.assertIn("dlg_q_chk_atc2", actives)                              # farewell after completing
        offer_idx = actives.index("dlg_q_chk_eli", 1)
        self.assertEqual(starts[offer_idx][1], [("target", "1")])
        outline = D.flatten(dlg)
        self.assertIn("{runs: dlg_q_adv(target=1)}", outline)
        self.assertIn("{runs: dlg_q_adv(target=2)}", outline)
        self.assertEqual(report["participants"][0]["slots"], {"1": 1, "5": 2})

    def test_modern_style_uses_parameterized_current_stage_check(self):
        p, cs, _ = self.build({**spec(), "script_style": "modern"})
        dlg = cs.load("dlg", "marek")
        starts = [(G.get(s, "Active"), [(G.get(q, "Key"), G.get(q, "Value")) for q in s["ConditionParams"]["value"]])
                  for s in dlg["StartingList"]["value"]]
        self.assertIn(("dlg_q_chk_at", [("target", "1")]), starts)       # reminder after accepting
        self.assertIn(("dlg_q_chk_at", [("target", "2")]), starts)       # farewell after completing
        self.assertFalse([a for a, _ in starts if a.startswith("dlg_q_chk_atc")])
        self.assertIn("dlg_q_chk_at", {Path(f.rel).stem for f in cs.changed_files() if f.rel.endswith(".nss")})
        src = cs.pending_text(cs.rel_nss("dlg_q_chk_at"))
        self.assertIn('GetScriptParam("target")', src)
        self.assertIn("GetIsCurrentlyAtQuestStage", src)

    def test_modern_style_has_no_slot_limit_below_the_game_limit(self):
        p = self.project()
        qb = Q.QuestBuilder(p)
        cs = ChangeSet(p, "t", "quest")
        self.assertEqual(qb._cond_current(cs, {"script_style": "modern"}, 15, TAG, 3), ("dlg_q_chk_at", {"target": "15"}))
        self.assertEqual(qb._cond_current(cs, {"script_style": "legacy"}, 15, TAG, 3)[0], "dlg_q_chk_multi")

    def test_legacy_style_is_unchanged(self):
        p, cs, _ = self.build({**spec(), "script_style": "legacy"})
        actives = [G.get(s, "Active") for s in cs.load("dlg", "marek")["StartingList"]["value"]]
        self.assertIn("dlg_q_chk_atc1", actives)
        self.assertNotIn("dlg_q_chk_at", actives)
        self.assertIsNone(cs.pending_text(cs.rel_nss("dlg_q_chk_at")))

    def test_kill_pickup_explore_wiring(self):
        p, cs, report = self.build()
        boss = cs.load("utc", "marek_alpha")
        v = G.vars_of(boss)
        self.assertEqual((v["quest1"], v["quest_kill"], v["boss"]), (f"02_{TAG}", 1, 1))
        carried = [G.get(i, "InventoryRes") for i in boss["ItemList"]["value"]]
        self.assertEqual(carried[-1], "q_alphapelt")          # appended after the clone's inherited loot
        self.assertEqual(carried.count("q_alphapelt"), 1)
        self.assertNotIn("quest2", v)                         # inherited quest wiring was stripped
        item = cs.load("uti", "q_alphapelt")
        self.assertEqual(G.get(item, "Tag"), "quest")
        self.assertEqual(G.get_var(item, "quest1"), f"03_{TAG}")
        self.assertEqual(G.get_text(item, "LocalizedName"), "Alpha Pelt")
        git = cs.load("git", "bandit_cave")
        gv = G.vars_of(git)
        self.assertEqual(gv["enter_script"], Q.GENERIC_ENTER)
        explore_slot = [k for k, val in gv.items() if val == f"04_{TAG}"]
        self.assertEqual(len(explore_slot), 1)
        self.assertIn("src/nss/enter_quest_adv.nss", cs.files)
        self.assertEqual(report["explore"][0]["stage"], 4)

    def test_placed_instances_carry_vars(self):
        p, cs, _ = self.build()
        plan = f"quest_{TAG}"
        cave = cs.load("git", "bandit_cave")
        mine = [i for k, i in I.plan_instances(cave, plan)]
        self.assertEqual([G.get(i, "TemplateResRef") for i in mine], ["marek"])
        self.assertEqual(G.get_var(mine[0], "quest1"), f"01_{TAG}")  # snapshot of blueprint vars
        gob = cs.load("git", "goblin2")
        boss = [i for k, i in I.plan_instances(gob, plan)]
        self.assertEqual([G.get(i, "TemplateResRef") for i in boss], ["marek_alpha"])
        self.assertEqual(G.get_var(boss[0], "quest_kill"), 1)

    def test_everything_validates(self):
        p, cs, _ = self.build()
        issues = V.validate_changeset(p, cs)
        errors = [i for i in issues if i.level == "error"]
        self.assertEqual(errors, [], [(e.rel, e.message) for e in errors])

    def test_rebuild_is_idempotent_and_undo_restores(self):
        p, cs, _ = self.build()
        originals = {fc.rel: fc.old_text for fc in cs.changed_files()}
        res = apply_changeset(p, cs)
        self.assertTrue(res.ok, res.problems)
        try:
            p2, cs2, _ = self.build()
            jrl = cs2.load("jrl", "module")
            self.assertEqual(sum(1 for c in jrl["Categories"]["value"] if G.get(c, "Tag") == TAG), 1)
            dlg_a = cs.load("dlg", "marek")
            dlg_b = cs2.load("dlg", "marek")
            self.assertEqual(G.dumps(dlg_a), G.dumps(dlg_b))
            for area in ("bandit_cave", "goblin2"):
                self.assertEqual(len(list(I.plan_instances(cs2.load("git", area), f"quest_{TAG}"))),
                                 len(list(I.plan_instances(cs.load("git", area), f"quest_{TAG}"))))
            # the second build must be a no-op relative to what was applied
            self.assertEqual([fc.rel for fc in cs2.changed_files()], [], [fc.rel for fc in cs2.changed_files()])
        finally:
            undone = undo_applied(p, cs.id)
            self.assertTrue(undone.ok, undone.problems)
        for rel, old in originals.items():
            path = self.root / rel
            if old is None:
                self.assertFalse(path.exists(), rel)
            else:
                self.assertEqual(path.read_text(), old, rel)

    def test_existing_giver_merges_dialog_and_patches_instances(self):
        p = self.project()
        s = {"tag": "q_unit_merge", "name": "Merge Quest",
             "giver": {"mode": "existing", "resref": "jolie"},
             "stages": [{"n": 1, "via": "talk", "journal": "Jolie asks a favour.", "offer": "Help me?"},
                        {"n": 2, "via": "talk", "journal": "Done.", "text": "Thank you!",
                         "reward": {"xp_tier": 1, "xp_level": 2}}]}
        cs, report = Q.QuestBuilder(p).build(s)
        npc = cs.load("utc", "jolie")
        v = G.vars_of(npc)
        self.assertEqual(v["quest1"], "02_q_kidnapped")            # untouched legacy slot
        self.assertEqual(v["quest2"], "01_q_unit_merge")           # next free slots
        self.assertEqual(v["quest3"], "02_q_unit_merge")
        dlg = cs.load("dlg", "jolie")
        self.assertTrue(any(G.get(n, "Comment", "").startswith("studio:q_unit_merge:") for n in dlg["EntryList"]["value"]))
        # placed jolie in goblin2 got the same slot vars
        gob = cs.load("git", "goblin2")
        jolies = [i for i in I.instances(gob, "creature") if G.get(i, "TemplateResRef") == "jolie"]
        self.assertTrue(jolies)
        for inst in jolies:
            self.assertEqual(G.get_var(inst, "quest2"), "01_q_unit_merge")
            self.assertEqual(G.get_var(inst, "quest1"), "02_q_kidnapped")
        self.assertEqual(report["participants"][0]["slots"], {"1": 2, "2": 3})
        errors = [i for i in V.validate_changeset(p, cs, compile_scripts=False) if i.level == "error"]
        self.assertEqual(errors, [], [(e.rel, e.message) for e in errors])
        # rebuild into the already-merged dialog: still exactly one generated block
        cs.persist()
        res = apply_changeset(p, cs, allow_dirty=True)
        self.assertTrue(res.ok, res.problems)
        try:
            cs2, _ = Q.QuestBuilder(p).build(s)
            self.assertEqual(G.dumps(cs2.load("dlg", "jolie")), G.dumps(cs.load("dlg", "jolie")))
            self.assertEqual([fc.rel for fc in cs2.changed_files()], [])
        finally:
            self.assertTrue(undo_applied(p, cs.id).ok)

    def test_conflicts_are_errors(self):
        p = self.project()
        s = spec()
        s["tag"] = "q_dryad"  # exists in the journal and was not generated by us
        with self.assertRaises(Q.QuestError):
            Q.QuestBuilder(p).build(s)
        s = spec()
        s["giver"]["resref"] = "bandit"  # existing blueprint, mode new
        s["giver"]["clone_from"] = "jolie"
        with self.assertRaises(Q.QuestError):
            Q.QuestBuilder(p).build(s)
        s = spec()
        s["stages"][3]["area"] = "no_such_area"
        with self.assertRaises(Q.QuestError):
            Q.QuestBuilder(p).build(s)
        s = spec()
        s["giver"]["place"]["x"] = 99999
        with self.assertRaises(Q.QuestError):
            Q.QuestBuilder(p).build(s)

    def test_kill_target_existing_with_other_quest_kill_conflicts(self):
        p = self.project()
        s = spec()
        s["stages"][1]["target"] = {"mode": "existing", "resref": "kurth"}  # kurth already has quest_kill
        with self.assertRaises(Q.QuestError):
            Q.QuestBuilder(p).build(s)


if __name__ == "__main__":
    unittest.main()


class BlankFieldTests(MiniTfnCase):
    def test_blank_dialog_fields_fall_back_to_defaults(self):
        """The web form sends "" for untouched optional fields; they must not become empty NPC lines."""
        p = self.project()
        s = spec()
        for st in s["stages"]:
            for key in ("offer", "accept_reply", "accept", "decline_reply", "decline", "reminder", "text", "reply", "done"):
                if key in st:
                    st[key] = ""
        s["stages"][0]["offer"] = "   "            # whitespace counts as blank too
        s["stages"][4]["reply"] = ""
        cs, _ = Q.QuestBuilder(p).build(s)
        dlg = cs.load("dlg", "marek")
        for node in dlg["EntryList"]["value"] + dlg["ReplyList"]["value"]:
            self.assertTrue(G.get_text(node, "Text").strip(), G.get(node, "Comment"))
        issues = V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)
        self.assertFalse([i for i in issues if "empty text" in i.message], [i.message for i in issues])
        self.assertIn("I could use some help.", D.flatten(dlg))
