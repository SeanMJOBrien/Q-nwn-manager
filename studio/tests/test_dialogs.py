"""Dialog builder tests (including add-then-remove on real TFN dialogs)."""

from __future__ import annotations

import glob
import random
import unittest

from tests.fixture import HAVE_TFN, REAL_TFN, MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import dialogs as D
from tfnstudio import gffjson as G
from tfnstudio import validate as V
from tfnstudio.changeset import ChangeSet


def build_sample(b: D.DialogBuilder, tag: str = "q_t") -> None:
    """Offer / accept / decline / reminder flow with quest scripts, tagged for removal."""
    c = f"studio:{tag}:"
    offer = b.add_entry("I need help.", comment=c + "offer")
    yes = b.add_reply("I'll do it.", comment=c + "yes")
    no = b.add_reply(D.LEAVE, comment=c + "no")
    done = b.add_entry("Thank you.", script="dlg_q_adv", params={"target": "1"}, comment=c + "accepted")
    b.entry_to_reply(offer, yes)
    b.entry_to_reply(offer, no)
    b.reply_to_entry(yes, done)
    rem = b.add_entry("Any news?", comment=c + "reminder")
    leave = b.add_reply(D.LEAVE, comment=c + "leave")
    b.entry_to_reply(rem, leave)
    b.add_start(rem, active="dlg_q_chk_atc1")
    b.add_start(offer, active="dlg_q_chk_eli", params={"target": "1"})


class BuilderShapeTests(unittest.TestCase):
    def test_new_dialog_structure(self):
        b = D.DialogBuilder()
        build_sample(b)
        d = b.finish()
        self.assertEqual(list(d)[0], "__data_type")
        self.assertEqual(len(d["EntryList"]["value"]), 3)
        self.assertEqual(len(d["ReplyList"]["value"]), 3)
        for i, e in enumerate(d["EntryList"]["value"]):
            self.assertEqual(e["__struct_id"], i)
            keys = [k for k in e if k != "__struct_id"]
            self.assertEqual(keys, sorted(keys, key=str.lower))
        starts = d["StartingList"]["value"]
        self.assertEqual([G.get(s, "Active") for s in starts], ["dlg_q_chk_eli", "dlg_q_chk_atc1"])  # front insert
        self.assertEqual([s["__struct_id"] for s in starts], [0, 1])
        p = starts[0]["ConditionParams"]["value"][0]
        self.assertEqual((G.get(p, "Key"), G.get(p, "Value")), ("target", "1"))
        self.assertGreater(G.get(d, "NumWords"), 5)
        self.assertEqual(G.dumps(G.loads(G.dumps(d))), G.dumps(d))

    def test_flatten(self):
        b = D.DialogBuilder()
        build_sample(b)
        out = D.flatten(b.finish())
        self.assertIn("[if: dlg_q_chk_eli(target=1)]", out)
        self.assertIn('{runs: dlg_q_adv(target=1)}', out)
        self.assertIn("[END]", out)

    def test_remove_generated_cleans_links_and_starts(self):
        b = D.DialogBuilder()
        keep = b.add_entry("hand written", comment="")
        kr = b.add_reply("hello", comment="")
        b.entry_to_reply(keep, kr)
        b.add_start(keep)
        build_sample(b)
        # a hand-written reply that points at a generated entry must lose that link only
        b.reply_to_entry(kr, 1)  # entry 1 is generated ("Thank you" is idx 2... but 1 is valid generated node)
        before_removal = len(b.entries)
        self.assertGreater(before_removal, 1)
        n = b.remove_generated("studio:q_t:")
        self.assertGreater(n, 0)
        d = b.finish()
        self.assertEqual(len(d["EntryList"]["value"]), 1)
        self.assertEqual(len(d["ReplyList"]["value"]), 1)
        self.assertEqual(d["ReplyList"]["value"][0]["EntriesList"]["value"], [])
        self.assertEqual(len(d["StartingList"]["value"]), 1)


@unittest.skipUnless(HAVE_TFN, "real TFN checkout not found")
class RealDialogTests(unittest.TestCase):
    def test_wrap_without_changes_is_identity(self):
        files = sorted(glob.glob(str(REAL_TFN / "src" / "dlg" / "*.dlg.json")))
        random.Random(5).shuffle(files)
        for f in files[:25]:
            d = G.read(f)
            before = G.dumps(d)
            self.assertEqual(G.dumps(D.DialogBuilder(d).finish()), before, f)

    def test_add_then_remove_restores_original(self):
        files = sorted(glob.glob(str(REAL_TFN / "src" / "dlg" / "*.dlg.json")))
        random.Random(9).shuffle(files)
        checked = 0
        for f in files[:40]:
            d = G.read(f)
            if not d["EntryList"]["value"]:
                continue
            original = G.dumps(d)
            b = D.DialogBuilder(d)
            build_sample(b)
            self.assertNotEqual(G.dumps(b.finish()), original)
            b.remove_generated("studio:q_t:")
            restored = b.d
            # NumWords is recomputed on finish(); compare everything else exactly
            restored["NumWords"] = G.loads(original)["NumWords"]
            self.assertEqual(G.dumps(restored), original, f)
            checked += 1
        self.assertGreater(checked, 20)


class DialogLintTests(MiniTfnCase):
    def test_generated_dialog_lints_clean(self):
        p = self.project()
        b = D.DialogBuilder()
        build_sample(b)
        cs = ChangeSet(p, "dlg", "quest")
        cs.save("dlg", "zz_test_dlg", b.finish())
        issues = V.validate_changeset(p, cs, compile_scripts=False)
        self.assertEqual([i for i in issues if i.level == "error"], [], [i.message for i in issues])

    def test_lint_catches_problems(self):
        p = self.project()
        b = D.DialogBuilder()
        e = b.add_entry("Hi", script="no_such_script_zz")
        b.add_start(e, active="dlg_q_chk_eli")  # missing target param
        b.add_entry("unreachable")
        cs = ChangeSet(p, "dlg", "quest")
        cs.save("dlg", "zz_bad_dlg", b.finish())
        msgs = [i.message for i in V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)]
        self.assertTrue(any("no_such_script_zz" in m for m in msgs), msgs)
        self.assertTrue(any("needs param target" in m for m in msgs), msgs)
        self.assertTrue(any("unreachable" in m for m in msgs), msgs)

    def test_merge_into_real_npc_dialog(self):
        p = self.project()
        d = p.read("dlg", "jolie")
        original_entries = len(d["EntryList"]["value"])
        b = D.DialogBuilder(d)
        build_sample(b, "q_merge")
        merged = b.finish()
        self.assertEqual(len(merged["EntryList"]["value"]), original_entries + 3)
        # existing starting entries still present, after ours
        self.assertEqual(G.get(merged["StartingList"]["value"][0], "Active"), "dlg_q_chk_eli")
        cs = ChangeSet(p, "merge", "quest")
        cs.save("dlg", "jolie", merged)
        errors = [i for i in V.validate_changeset(p, cs, compile_scripts=False) if i.level == "error"]
        self.assertEqual(errors, [], [e.message for e in errors])


if __name__ == "__main__":
    unittest.main()
