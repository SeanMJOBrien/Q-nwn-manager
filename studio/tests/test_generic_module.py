"""Generic mode: a module that is not The Frozen North (flat nwn-manager layout, no TFN scripts)."""

from __future__ import annotations

import unittest

from tests.generic_fixture import GenericCase  # noqa: F401  (sets sys.path)

from tfnstudio import dialogs as D
from tfnstudio import gffjson as G
from tfnstudio import project as P
from tfnstudio import runtime as RT
from tfnstudio.changeset import apply_changeset, undo_applied
from tfnstudio.project import ProjectError

SPEC = {
    "tag": "q_unit_hunt", "name": "The Unit Hunt", "priority": 2,
    "giver": {"mode": "new", "resref": "marek", "name": "Hunter Marek", "clone_from": "qs_npc", "greeting": "Well met.",
              "place": {"area": "start", "x": 5.0, "y": 5.0, "facing": 90}},
    "stages": [
        {"n": 1, "via": "talk", "journal": "Marek wants the alpha dead.", "offer": "A goblin alpha raids my traps.",
         "accept_reply": "Consider it done.", "accept": "Good luck.", "decline_reply": "Not today.", "decline": "Pity.",
         "reminder": "Is it dead yet?"},
        {"n": 2, "via": "kill", "journal": "You slew it. Take its pelt.",
         "target": {"mode": "new", "resref": "marek_alpha", "name": "Goblin Alpha", "clone_from": "qs_npc",
                    "place": {"area": "cave", "x": 4.0, "y": 4.0, "facing": 0}}},
        {"n": 3, "via": "pickup", "journal": "You hold the pelt.",
         "item": {"resref": "q_alphapelt", "name": "Alpha Pelt", "description": "A mangy pelt.", "dropped_by": "marek_alpha"}},
        {"n": 4, "via": "explore", "journal": "You scouted the cave. Return to Marek.", "area": "cave"},
        {"n": 5, "via": "talk", "journal": "Marek paid you.", "text": "Splendid!", "reply": "Thanks.", "done": "Thanks again.",
         "reward": {"xp_tier": 2, "xp_level": 3, "gold": 150}},
    ],
}


def spec():
    return G.clone(SPEC)


class DetectionTests(GenericCase):
    def test_flat_layout_and_generic_profile(self):
        p = self.studio().project
        self.assertEqual((p.layout, p.profile), ("flat", "generic"))
        self.assertEqual(p.src.name, "unpacked")
        self.assertEqual(p.json_path("are", "start").name, "start.are.json")
        self.assertEqual(p.nss_path("x").parent, p.src)
        self.assertEqual(p.parse_rel("unpacked/start.are.json"), ("are", "start"))
        self.assertEqual(sorted(p.list_resrefs("are")), ["cave", "start"])
        self.assertEqual(p.studio_dir, self.root / ".studio")

    def test_specs_live_in_the_module(self):
        self.assertEqual(self.studio().spec_root, self.root / "studio-specs")

    def test_a_non_project_folder_is_refused(self):
        with self.assertRaises(ProjectError):
            P.TfnProject(self.root / "unpacked")

    def test_nearest_nasher_cfg_is_found_from_a_subfolder(self):
        self.assertEqual(P.find_project_above(self.root / "unpacked"), self.root)


class RuntimeTests(GenericCase):
    def test_status_before_and_stage(self):
        st = self.studio()
        before = st.runtime_status()
        self.assertFalse(before["installed"])
        self.assertIn("inc_quest", before["missing"])
        res = st.stage_runtime(persist=False)
        self.assertTrue(res.ok, [(i.rel, i.message) for i in res.issues])
        rels = {f.rel for f in res.change.changed_files()}
        for name in ("inc_quest", "dlg_q_adv", "dlg_q_chk_eli", "dlg_q_chk_atp", "dlg_q_chk_at", "enter_quest_adv",
                     "qs_ondeath", "qs_acquire"):
            self.assertIn(f"unpacked/{name}.nss", rels)
        self.assertIn("unpacked/qs_npc.utc.json", rels)
        ifo = G.loads(res.change.pending_text("unpacked/module.ifo.json"))
        self.assertEqual(G.get(ifo, "Mod_OnAcquirItem"), "qs_acquire")

    def test_tfn_scripts_are_never_mistaken_for_ours(self):
        # an inc_quest without our marker is a module's own (that is how The Frozen North is told apart)
        self.assertNotIn(RT.MARK, "// plain inc_quest of some other module")


class QuestTests(GenericCase):
    def test_full_quest_on_a_fresh_module(self):
        st = self.studio()
        res = st.stage_quest(spec(), persist=False)
        self.assertTrue(res.ok, [(i.rel, i.message) for i in res.issues])
        cs = res.change
        # the first quest installs the runtime and creates the journal
        self.assertIsNotNone(cs.pending_text("unpacked/inc_quest.nss"))
        jrl = G.loads(cs.pending_text("unpacked/module.jrl.json"))
        cat = jrl["Categories"]["value"][0]
        self.assertEqual(G.get(cat, "Tag"), "q_unit_hunt")
        self.assertEqual([G.get(e, "ID") for e in cat["EntryList"]["value"]], [1, 2, 3, 4, 5])
        # dialog: parameterized scripts only, modern style forced
        dlg = G.loads(cs.pending_text("unpacked/marek.dlg.json"))
        actives = D.scripts_used(dlg)
        self.assertTrue({"dlg_q_chk_eli", "dlg_q_adv", "dlg_q_chk_at"} <= actives, actives)
        self.assertFalse([a for a in actives if a.startswith("dlg_q_chk_atc")])
        # kill target credits through the runtime's OnDeath; explore uses the area's OnEnter; pickup item is tagged quest
        boss = G.loads(cs.pending_text("unpacked/marek_alpha.utc.json"))
        self.assertEqual(G.get(boss, "ScriptDeath"), "qs_ondeath")
        self.assertEqual(G.vars_of(boss)["quest_kill"], 1)
        are = G.loads(cs.pending_text("unpacked/cave.are.json"))
        self.assertEqual(G.get(are, "OnEnter"), "enter_quest_adv")
        item = G.loads(cs.pending_text("unpacked/q_alphapelt.uti.json"))
        self.assertEqual(G.get(item, "Tag"), "quest")

    def test_older_style_request_is_ignored_in_generic_modules(self):
        res = self.studio().stage_quest({**spec(), "script_style": "legacy"}, persist=False)
        self.assertTrue(res.ok)
        dlg = G.loads(res.change.pending_text("unpacked/marek.dlg.json"))
        self.assertIn("dlg_q_chk_at", D.scripts_used(dlg))

    def test_explore_refuses_an_area_that_already_has_an_enter_script(self):
        st = self.studio()
        are_path = self.root / "unpacked" / "cave.are.json"
        original = are_path.read_text()
        try:
            are = G.loads(original)
            are["OnEnter"] = G.resref("my_own_enter")
            are_path.write_text(G.dumps(are))
            st.refresh()
            with self.assertRaises(Exception) as cm:
                st.stage_quest(spec(), persist=False)
            self.assertIn("OnEnter", str(cm.exception))
        finally:
            are_path.write_text(original)
            st.refresh()

    def test_apply_and_undo(self):
        st = self.studio()
        res = st.stage_quest(spec())
        self.assertTrue(res.ok)
        out = apply_changeset(st.project, res.change)
        self.assertTrue(out.ok, out.problems)
        self.assertTrue((self.root / "unpacked" / "marek.dlg.json").is_file())
        self.assertTrue((self.root / "unpacked" / "module.jrl.json").is_file())
        # a second quest does not reinstall the runtime
        st2 = self.studio()
        second = {"tag": "q_second", "name": "Second", "giver": {"mode": "new", "resref": "tomas", "name": "Tomas",
                                                              "clone_from": "qs_npc"},
                  "stages": [SPEC["stages"][0], {**SPEC["stages"][4], "n": 2}]}
        again = st2.stage_quest(second, persist=False)
        self.assertTrue(again.ok, [(i.rel, i.message) for i in again.issues])
        self.assertFalse([f for f in again.change.changed_files() if f.rel.endswith("inc_quest.nss")])
        undone = undo_applied(st.project, res.change.id)
        self.assertTrue(undone.ok, undone.problems)
        self.assertFalse((self.root / "unpacked" / "marek.dlg.json").exists())
        self.assertFalse((self.root / "unpacked" / "module.jrl.json").exists())


class EngineGuardTests(GenericCase):
    def test_spawn_features_are_refused(self):
        st = self.studio()
        with self.assertRaises(ProjectError):
            st.stage_camp({"id": "c1", "area": "start", "objects": [], "groups": [{"n": 1, "ute": "x", "spawns": 1}]})
        with self.assertRaises(ProjectError):
            st.stage_ute({"resref": "enc1"})


if __name__ == "__main__":
    unittest.main()
