#!/usr/bin/env python3
"""Tests for bin/nwn-quests (the bridge to Q-nwn-mcp's quest builder) and the
console's Quests routes. The builder itself is replaced by a small fake CLI
(tests need neither node nor Q-nwn-mcp): it answers `schema`, plans, and for a
build writes staged files into --out the way the real one does.

Run: python3 tests/test_quests.py
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
QUESTS = SourceFileLoader("nwn_quests_under_test",
                          str(REPO_ROOT / "bin" / "nwn-quests")).load_module()
CONSOLE = SourceFileLoader("nwn_area_editor_under_test__test_quests",
                           str(REPO_ROOT / "bin" / "nwn-area-editor")).load_module()

# Stands in for `node dist/cli/quest.js`: same arguments, same JSON on stdout.
FAKE_CLI = r'''
import json, os, sys
args = sys.argv[1:]
def out(ok, payload):
    print(json.dumps({"ok": True, "result": payload} if ok else {"ok": False, "error": payload}))
    sys.exit(0 if ok else 1)
def opt(name):
    return args[args.index(name) + 1] if name in args else None
cmd = args[0]
if cmd == "version":
    marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hash.txt")
    h = open(marker).read().strip() if os.path.exists(marker) else "aaaaaaaaaaaa"
    out(True, {"version": "1.0", "schemaHash": h, "bundled": False})
if cmd == "schema":
    out(True, {"definitions": {"QuestInput": {"properties": {"name": {"type": "string"}}},
                               "StageInput": {"properties": {"do": {"enum": ["talk"]}}}}})
project, dest = opt("--project"), opt("--out")
if cmd == "verify":
    if os.environ.get("FAKE_QUEST_UNCOMPLETABLE"):
        out(True, {"tag": args[1], "completable": False,
                   "gaps": ["Quest-giver NPC is in unreachable area 'cellar'"],
                   "journal": {"errors": [], "warnings": []}})
    out(True, {"tag": args[1], "completable": True, "gaps": [], "journal": {"errors": [], "warnings": []}})
if os.environ.get("FAKE_QUEST_FAIL"):
    where = {}
    if os.environ.get("FAKE_QUEST_STAGE"):
        where = {"stage": int(os.environ["FAKE_QUEST_STAGE"]), "field": os.environ["FAKE_QUEST_FIELD"]}
    sys.stdout.write(json.dumps(dict({"ok": False, "error": os.environ["FAKE_QUEST_FAIL"]}, **where)))
    sys.exit(1)
if cmd == "remove":
    with open(os.path.join(project, "module.jrl.json")) as fh:
        jrl = json.load(fh)
    jrl["Categories"]["value"] = [c for c in jrl["Categories"]["value"] if c["Tag"]["value"] != args[1]]
    with open(os.path.join(dest, "module.jrl.json"), "w") as fh:
        json.dump(jrl, fh)
    out(True, {"tag": args[1], "variablesRemoved": 2,
               "source": {"files": ["module.jrl.json"],
                          "removed": ["dq_ned.dlg.json"] if os.path.exists(os.path.join(project, "dq_ned.dlg.json")) else []}})
with open(args[1]) as fh:
    spec = json.load(fh)
tag = spec.get("tag") or "q_" + spec["name"].lower().replace(" ", "_")
report = {"success": True, "tag": tag, "name": spec["name"], "dryRun": "--dry-run" in args,
          "stages": [{"n": 1, "do": "talk", "by": spec.get("giver"), "journal": "j", "end": True}]}
if "--dry-run" in args:
    out(True, report)
if "--no-compile" not in args:
    out(False, "expected --no-compile")
with open(os.path.join(project, "ned.utc.json")) as fh:
    ned = json.load(fh)
ned["Conversation"] = {"type": "resref", "value": "dq_ned"}
ned["Speed"] = {"type": "float", "value": 1}
with open(os.path.join(dest, "ned.utc.json"), "w") as fh:
    json.dump(ned, fh)
with open(os.path.join(project, "module.ifo.json")) as fh:
    untouched = fh.read()
with open(os.path.join(dest, "module.ifo.json"), "w") as fh:
    fh.write(untouched)
jrl = {"__data_type": "JRL ", "Categories": {"type": "list", "value": [
    {"__struct_id": 0, "Tag": {"type": "cexostring", "value": tag},
     "Name": {"type": "cexolocstring", "value": {"0": spec["name"]}},
     "EntryList": {"type": "list", "value": [{"__struct_id": 0}]}}]}}
with open(os.path.join(dest, "module.jrl.json"), "w") as fh:
    json.dump(jrl, fh)
with open(os.path.join(dest, "q_act.nss"), "w") as fh:
    fh.write(os.environ.get("FAKE_QUEST_SCRIPT", "void main() {}\n"))
if os.environ.get("FAKE_QUEST_TOUCH"):
    with open(os.path.join(project, "ned.utc.json"), "a") as fh:
        fh.write("\n")
out(True, dict(report, source={"files": ["module.ifo.json", "module.jrl.json", "ned.utc.json", "q_act.nss"],
                               "removed": []}))
'''


def f(t, v):
    return {"type": t, "value": v}


def make_project():
    proj = tempfile.mkdtemp(prefix="qnm_quests_")
    open(os.path.join(proj, "nasher.cfg"), "w").close()
    unpacked = os.path.join(proj, "unpacked")
    os.makedirs(unpacked)

    def write(name, doc):
        with open(os.path.join(unpacked, name), "w") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
    write("module.ifo.json", {"__data_type": "IFO ", "Mod_Name": f("cexolocstring", {"0": "M"})})
    write("ned.utc.json", {"__data_type": "UTC ", "Tag": f("cexostring", "farmer_ned"),
                           "FirstName": f("cexolocstring", {"0": "Ned"}),
                           "LastName": f("cexolocstring", {"0": "Fold"}),
                           "Conversation": f("resref", ""), "Speed": f("float", 1.0)})
    write("wolf.utc.json", {"__data_type": "UTC ", "Tag": f("cexostring", "wolf_alpha"),
                            "FirstName": f("cexolocstring", {"id": 5})})
    write("ledger.uti.json", {"__data_type": "UTI ", "Tag": f("cexostring", "ledger"),
                              "LocalizedName": f("cexolocstring", {"0": "Ledger"})})
    write("farm.are.json", {"__data_type": "ARE ", "Tag": f("cexostring", "FoldFarm"),
                            "Name": f("cexolocstring", {"0": "Fold Farm"})})
    write("farm.git.json", {"__data_type": "GIT ", "Creature List": f("list", [
        {"__struct_id": 4, "Tag": f("cexostring", "farmer_ned"),
         "FirstName": f("cexolocstring", {"0": "Ned"})}]),
        "Placeable List": f("list", [{"__struct_id": 9, "Tag": f("cexostring", "old_chest"),
                                      "LocName": f("cexolocstring", {"0": "Old Chest"})}]),
        "WaypointList": f("list", [{"__struct_id": 5, "Tag": f("cexostring", "wp_gate")}])})
    return proj, unpacked


class FakeCliMixin:
    """Points the bridge at the fake builder for the life of the test class."""

    @classmethod
    def install_fake_cli(cls):
        cls.cli_dir = tempfile.mkdtemp(prefix="qnm_fakecli_")
        cli = os.path.join(cls.cli_dir, "dist", "cli", "quest.js")
        os.makedirs(os.path.dirname(cli))
        with open(cli, "w") as fh:
            fh.write(FAKE_CLI)
        cls._env = {k: os.environ.get(k) for k in
                    ("NWN_QUEST_CLI", "NODE", "NIM_FOLDER_NWTOOLS", "FAKE_QUEST_FAIL",
                     "FAKE_QUEST_TOUCH", "FAKE_QUEST_SCRIPT", "FAKE_QUEST_UNCOMPLETABLE",
                     "FAKE_QUEST_STAGE", "FAKE_QUEST_FIELD")}
        os.environ.update({"NWN_QUEST_CLI": cli, "NODE": sys.executable,
                           "NIM_FOLDER_NWTOOLS": cls.cli_dir})

    @classmethod
    def remove_fake_cli(cls):
        for key, value in cls._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(cls.cli_dir, ignore_errors=True)


class BridgeTests(FakeCliMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_fake_cli()

    @classmethod
    def tearDownClass(cls):
        cls.remove_fake_cli()

    def setUp(self):
        self.proj, self.unpacked = make_project()
        self.addCleanup(shutil.rmtree, self.proj, ignore_errors=True)
        for key in ("FAKE_QUEST_FAIL", "FAKE_QUEST_TOUCH", "FAKE_QUEST_SCRIPT", "FAKE_QUEST_UNCOMPLETABLE",
                    "FAKE_QUEST_STAGE", "FAKE_QUEST_FIELD"):
            os.environ.pop(key, None)

    def test_builder_lookup_prefers_the_vendored_bundle_over_a_checkout(self):
        lib = CONSOLE.quests_lib()
        vendored = os.path.join(lib._REPO, "nwn-tools", "quest-cli.mjs")
        self.assertTrue(os.path.isfile(vendored), "nwn-tools/quest-cli.mjs is vendored")
        self.assertEqual(lib.cli_path({}), vendored)
        given = os.path.join(self.cli_dir, "dist", "cli", "quest.js")
        self.assertEqual(lib.cli_path({"NWN_QUEST_CLI": given}), given)     # the variable wins
        self.assertTrue(lib._cli_cwd(vendored).endswith("nwn-tools"))
        self.assertEqual(lib._cli_cwd(given), self.cli_dir)

    def test_a_stale_builder_is_noted_against_the_checkout_beside_the_repo(self):
        lib = CONSOLE.quests_lib()
        fake = os.path.join(self.cli_dir, "dist", "cli", "quest.js")
        old_dir = tempfile.mkdtemp(prefix="qnm_oldcli_")
        old = os.path.join(old_dir, "quest-cli.mjs")
        shutil.copy(fake, old)
        original = lib.checkout_cli
        lib.checkout_cli = lambda: fake                      # pretend the fake is the checkout's builder
        lib._version_cache.clear()
        try:
            self.assertEqual(lib.builder_version(fake)["schemaHash"], "aaaaaaaaaaaa")
            self.assertIsNone(lib.version_note(fake))        # the same file: nothing to compare
            self.assertIsNone(lib.version_note(old))         # same schema hash: current
            with open(os.path.join(old_dir, "hash.txt"), "w") as fh:
                fh.write("bbbbbbbbbbbb")
            lib._version_cache.clear()
            note = lib.version_note(old)
            self.assertIn("bbbbbbbbbbbb", note)
            self.assertIn("npm run quest:bundle", note)
            lib.checkout_cli = lambda: None
            self.assertIsNone(lib.version_note(old))         # no checkout to compare with
        finally:
            lib.checkout_cli = original
            lib._version_cache.clear()
            shutil.rmtree(old_dir, ignore_errors=True)

    def test_tag_follows_the_builders_rule(self):
        self.assertEqual(QUESTS.tag_from_name("Wolves at the Fold"), "q_wolves_at_the_fold")
        self.assertEqual(QUESTS.tag_from_name("Garnes and the Missing Ledger"),
                         "q_garnes_and_the_missing_le")
        self.assertEqual(QUESTS.tag_from_name("  --Ünïcode & Co!  "), "q_n_code_co")
        self.assertEqual(QUESTS.spec_tag({"name": "Rat Bounty", "template": "bounty"}), "b_rat_bounty")
        self.assertEqual(QUESTS.spec_tag({"name": "x", "tag": "My_Tag"}), "my_tag")
        for bad in ({"name": ""}, {"name": "x", "tag": "../evil"}, {"name": "x", "tag": "9lives"}, []):
            with self.assertRaises(QUESTS.QuestError):
                QUESTS.spec_tag(bad)

    def test_specs_are_saved_listed_and_deleted(self):
        tag = QUESTS.save_spec(self.proj, {"name": "Wolves at the Fold", "giver": "farmer_ned"})
        self.assertEqual(tag, "q_wolves_at_the_fold")
        self.assertEqual(QUESTS.load_spec(self.proj, tag)["giver"], "farmer_ned")
        with open(os.path.join(self.unpacked, "module.jrl.json"), "w") as fh:
            json.dump({"Categories": f("list", [
                {"Tag": f("cexostring", "old_quest"), "Name": f("cexolocstring", {"0": "Old"}),
                 "EntryList": f("list", [{}, {}])}])}, fh)
        listed = QUESTS.list_quests(self.proj, self.unpacked)
        self.assertEqual(listed, [
            {"tag": tag, "name": "Wolves at the Fold", "saved": True, "built": False, "entries": 0},
            {"tag": "old_quest", "name": "Old", "saved": False, "built": True, "entries": 2}])
        QUESTS.delete_spec(self.proj, tag)
        with self.assertRaises(QUESTS.QuestError):
            QUESTS.load_spec(self.proj, tag)
        with self.assertRaises(QUESTS.QuestError):
            QUESTS.spec_path(self.proj, "../../etc/passwd")

    def test_contents_lists_what_a_quest_can_name(self):
        c = QUESTS.contents(self.unpacked)
        self.assertEqual(c["areas"], [{"value": "farm", "label": "Fold Farm"}])
        self.assertEqual(c["creatures"], [
            {"value": "farmer_ned", "label": "Ned", "area": "Fold Farm"},
            {"value": "wolf_alpha", "label": "wolf_alpha", "area": "", "note": "blueprint, not placed"}])
        self.assertEqual(c["items"], [{"value": "ledger", "label": "Ledger"}])
        self.assertEqual(c["placeables"], [{"value": "old_chest", "label": "Old Chest", "area": "Fold Farm"}])
        self.assertEqual(c["waypoints"], [{"value": "wp_gate", "label": "wp_gate", "area": "Fold Farm"}])
        self.assertIs(QUESTS.contents(self.unpacked), c)          # cached
        with open(os.path.join(self.unpacked, "extra.uti.json"), "w") as fh:
            json.dump({"Tag": f("cexostring", "extra")}, fh)
        self.assertEqual(len(QUESTS.contents(self.unpacked)["items"]), 2)

    def test_plan_stage_and_errors_go_through_the_cli(self):
        spec = {"name": "Wolves", "giver": "farmer_ned"}
        self.assertTrue(QUESTS.info()["ready"])
        self.assertIn("QuestInput", QUESTS.schema()["definitions"])
        plan = QUESTS.plan(self.unpacked, spec)
        self.assertTrue(plan["dryRun"])
        out = tempfile.mkdtemp(prefix="qnm_out_")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        built = QUESTS.stage_build(self.unpacked, spec, out)
        self.assertEqual(sorted(os.listdir(out)), sorted(built["source"]["files"]))
        os.environ["FAKE_QUEST_FAIL"] = "stage 2 (kill) needs a target"
        with self.assertRaisesRegex(QUESTS.QuestError, "needs a target"):
            QUESTS.plan(self.unpacked, spec)
        with self.assertRaisesRegex(QUESTS.QuestError, "needs a name"):
            QUESTS.plan(self.unpacked, {"giver": "farmer_ned"})

    def test_missing_builder_is_reported_not_raised(self):
        os.environ["NWN_QUEST_CLI"] = os.path.join(self.proj, "nope.js")
        try:
            info = QUESTS.info()
            self.assertFalse(info["ready"])
            self.assertIn("quest builder was not found", " ".join(info["problems"]))
            with self.assertRaises(QUESTS.QuestError):
                QUESTS.run_cli(["schema"])
        finally:
            os.environ["NWN_QUEST_CLI"] = os.path.join(self.cli_dir, "dist", "cli", "quest.js")

    def test_staged_changes_skip_unchanged_files_and_restore_floats(self):
        out = tempfile.mkdtemp(prefix="qnm_out_")
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        built = QUESTS.stage_build(self.unpacked, {"name": "Wolves", "giver": "farmer_ned"}, out)
        changes = QUESTS.staged_changes(out, built["source"]["files"],
                                        lambda name: os.path.join(self.unpacked, name))
        by_name = {c["name"]: c for c in changes}
        self.assertEqual(sorted(by_name), ["module.jrl.json", "ned.utc.json", "q_act.nss"])
        self.assertTrue(by_name["module.jrl.json"]["new"])
        self.assertFalse(by_name["ned.utc.json"]["new"])
        speed = by_name["ned.utc.json"]["data"]["Speed"]["value"]
        self.assertIsInstance(speed, float)                       # 1 from JavaScript -> 1.0
        self.assertEqual(by_name["q_act.nss"]["kind"], "text")
        with self.assertRaises(QUESTS.QuestError):
            QUESTS.staged_changes(out, ["../escape.json"], lambda name: name)

    def test_fix_floats_only_touches_float_fields(self):
        doc = {"A": f("float", 2), "B": f("int", 2), "C": f("double", -0.0), "D": f("byte", True),
               "L": f("list", [{"X": f("float", 0)}])}
        QUESTS.fix_floats(doc)
        self.assertEqual(repr(doc["A"]["value"]), "2.0")
        self.assertEqual(repr(doc["B"]["value"]), "2")
        self.assertEqual(repr(doc["C"]["value"]), "-0.0")
        self.assertEqual(repr(doc["L"]["value"][0]["X"]["value"]), "0.0")


class ConsoleQuestTests(FakeCliMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install_fake_cli()
        cls.proj, cls.unpacked = make_project()
        cls.port = 18397
        cls._old_argv = sys.argv
        sys.argv = ["nwn-area-editor", "--dir", cls.unpacked,
                    "--host", "127.0.0.1", "--port", str(cls.port)]
        threading.Thread(target=CONSOLE.main, daemon=True).start()
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/module" % cls.port, timeout=0.2)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("test console server did not start in time")

    @classmethod
    def tearDownClass(cls):
        sys.argv = cls._old_argv
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/shutdown" % cls.port, data=b"", timeout=2)
        except Exception:
            pass
        shutil.rmtree(cls.proj, ignore_errors=True)
        cls.remove_fake_cli()

    def setUp(self):
        self.c = Client(self.port, "/quests")
        for key in ("FAKE_QUEST_FAIL", "FAKE_QUEST_TOUCH", "FAKE_QUEST_SCRIPT", "FAKE_QUEST_UNCOMPLETABLE",
                    "FAKE_QUEST_STAGE", "FAKE_QUEST_FIELD"):
            os.environ.pop(key, None)

    def read(self, name):
        with open(os.path.join(self.unpacked, name)) as fh:
            return fh.read()

    def post(self, path, **fields):
        return json.loads(self.c.post("/quests" + path, fields, timeout=60))

    def test_1_page_and_data(self):
        page = self.c.get("/quests")
        self.assertIn("id='quests-app'", page)
        self.assertIn("name='_csrf'", page)
        self.assertIn(">Quests</a>", page)
        data = json.loads(self.c.get("/quests/data"))
        self.assertTrue(data["ok"] and data["info"]["ready"])
        self.assertIn("StageInput", data["schema"]["definitions"])
        contents = json.loads(self.c.get("/quests/contents"))["contents"]
        self.assertEqual(contents["creatures"][0]["value"], "farmer_ned")

    def test_2_post_without_token_is_rejected(self):
        self.c.get("/quests")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.c.post("/quests/build", {"spec": "{}"}, token=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_3_plan_changes_nothing(self):
        before = self.read("ned.utc.json")
        out = self.post("/plan", spec=json.dumps({"name": "Wolves", "giver": "farmer_ned"}), new="1")
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["result"]["dryRun"])
        self.assertEqual(self.read("ned.utc.json"), before)
        self.assertFalse(os.path.exists(os.path.join(self.proj, "quests")))
        bad = self.post("/plan", spec="{not json")
        self.assertFalse(bad["ok"])

    def test_4_conflict_writes_nothing(self):
        os.environ["FAKE_QUEST_TOUCH"] = "1"       # the project changes while the builder runs
        time.sleep(0.05)
        out = self.post("/build", spec=json.dumps({"name": "Wolves", "giver": "farmer_ned"}), new="1")
        self.assertFalse(out["ok"])
        self.assertIn("changed on disk", out["error"])
        self.assertFalse(os.path.exists(os.path.join(self.unpacked, "module.jrl.json")))
        self.assertFalse(os.path.exists(os.path.join(self.unpacked, "q_act.nss")))

    def test_5_build_applies_through_history_and_saves_the_spec(self):
        before = self.read("ned.utc.json")
        out = self.post("/build", spec=json.dumps({"name": "Wolves", "giver": "farmer_ned"}), new="1")
        self.assertTrue(out["ok"], out)
        written = {w["name"]: w["new"] for w in out["applied"]["written"]}
        self.assertEqual(written, {"module.jrl.json": True, "ned.utc.json": False, "q_act.nss": True})
        self.assertEqual(out["applied"]["unchanged"], 1)            # module.ifo.json was identical
        self.assertTrue(out["applied"]["verify"]["checked"])        # completion check runs after the write
        self.assertTrue(out["applied"]["verify"]["completable"])
        ned = json.loads(self.read("ned.utc.json"))
        self.assertEqual(ned["Conversation"]["value"], "dq_ned")
        self.assertIn('"value": 1.0', self.read("ned.utc.json"))    # float kept as nasher writes it
        self.assertEqual(self.read("q_act.nss"), "void main() {}\n")
        with open(os.path.join(self.proj, "quests", "q_wolves.json")) as fh:
            self.assertEqual(json.load(fh)["tag"], "q_wolves")
        self.assertEqual(out["quests"][0], {"tag": "q_wolves", "name": "Wolves", "saved": True,
                                            "built": True, "entries": 1})
        hist = CONSOLE.common().list_history(CONSOLE.common().history_dir(self.proj))
        self.assertEqual([h["name"] for h in hist], ["ned.utc.json"])
        with open(hist[0]["snap"]) as fh:
            self.assertEqual(fh.read(), before)                      # undo point = the file before the quest
        spec = json.loads(self.c.get("/quests/spec?tag=q_wolves"))["spec"]
        self.assertEqual(spec["giver"], "farmer_ned")

    def test_9_an_uncompletable_build_is_written_and_the_gap_is_reported(self):
        os.environ["FAKE_QUEST_UNCOMPLETABLE"] = "1"
        out = self.post("/build", spec=json.dumps({"name": "Cellar", "giver": "farmer_ned"}), new="1")
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["applied"]["verify"]["completable"])
        self.assertIn("unreachable area", out["applied"]["verify"]["gaps"][0])

    def test_6_a_new_quest_cannot_replace_an_existing_one(self):
        out = self.post("/build", spec=json.dumps({"name": "Wolves", "giver": "farmer_ned"}), new="1")
        self.assertFalse(out["ok"])
        self.assertIn("already here", out["error"])
        again = self.post("/build", spec=json.dumps({"name": "Wolves", "giver": "farmer_ned", "tag": "q_wolves"}))
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["applied"]["written"], [])            # same result: nothing rewritten

    def test_7_remove_keeps_the_draft_then_delete_drops_it(self):
        dlg = os.path.join(self.unpacked, "dq_ned.dlg.json")      # the conversation the quest created
        with open(dlg, "w") as fh:
            fh.write('{"__data_type": "DLG "}')
        out = self.post("/remove", tag="q_wolves")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["applied"]["deleted"], ["dq_ned.dlg.json"])
        self.assertFalse(os.path.exists(dlg))                      # deleted through the history...
        names = [h["name"] for h in CONSOLE.common().list_history(CONSOLE.common().history_dir(self.proj))]
        self.assertIn("dq_ned.dlg.json", names)                    # ...so History can restore it
        self.assertEqual([w["name"] for w in out["applied"]["written"]], ["module.jrl.json"])
        self.assertEqual(out["quests"], [{"tag": "q_wolves", "name": "Wolves", "saved": True,
                                          "built": False, "entries": 0}])
        out = self.post("/delete", tag="q_wolves")
        self.assertEqual(out["quests"], [])
        self.assertFalse(self.post("/delete", tag="q_wolves")["ok"])

    def test_8_builder_errors_reach_the_page(self):
        os.environ["FAKE_QUEST_FAIL"] = "no creature tagged nobody"
        out = self.post("/build", spec=json.dumps({"name": "Ghost", "giver": "nobody"}), new="1")
        self.assertEqual(out, {"ok": False, "error": "no creature tagged nobody"})

    def test_8c_area_plan_gives_size_and_objects(self):
        def loc(v): return {"type": "cexolocstring", "value": {"0": v}}
        def n(v, t="int"): return {"type": t, "value": v}
        with open(os.path.join(self.unpacked, "pickarea.are.json"), "w") as fh:
            json.dump({"Name": loc("Pick Area"), "Width": n(4), "Height": n(3)}, fh)
        with open(os.path.join(self.unpacked, "pickarea.git.json"), "w") as fh:
            json.dump({"Creature List": {"type": "list", "value": [
                {"Tag": n("ned", "cexostring"), "XPosition": n(12.5, "float"), "YPosition": n(7, "float")}]},
                "Placeable List": {"type": "list", "value": [
                    {"Tag": n("chest", "cexostring"), "X": n(3, "float"), "Y": n(4, "float")}]}}, fh)
        plan = CONSOLE.quests_lib().area_plan(self.unpacked, "PickArea")
        self.assertEqual((plan["name"], plan["w"], plan["h"]), ("Pick Area", 40, 30))
        self.assertEqual(sorted((o["kind"], o["tag"], o["x"], o["y"]) for o in plan["objects"]),
                         [("creature", "ned", 12.5, 7.0), ("placeable", "chest", 3.0, 4.0)])
        with self.assertRaises(CONSOLE.quests_lib().QuestError):
            CONSOLE.quests_lib().area_plan(self.unpacked, "../etc/passwd")
        out = json.loads(self.c.get("/quests/areaplan?area=pickarea"))
        self.assertTrue(out["ok"], out)

    def test_8b_a_builder_error_names_its_stage_and_field(self):
        os.environ["FAKE_QUEST_FAIL"] = "stage 2 (kill) needs a target"
        os.environ["FAKE_QUEST_STAGE"], os.environ["FAKE_QUEST_FIELD"] = "2", "target"
        out = self.post("/plan", spec=json.dumps({"name": "Ghost", "giver": "ned"}))
        self.assertEqual(out, {"ok": False, "error": "stage 2 (kill) needs a target", "stage": 2, "field": "target"})


@unittest.skipUnless(QUESTS._tool("nwnsc", "nwnsc") and QUESTS.base_scripts_dir(),
                     "needs the bundled nwnsc and base scripts")
class CompileCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qnm_ncs_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.staged = os.path.join(self.tmp, "staged")
        self.unpacked = os.path.join(self.tmp, "unpacked")
        os.makedirs(self.staged)
        os.makedirs(self.unpacked)

    def write(self, folder, name, text):
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(text)

    def test_good_scripts_pass_and_includes_come_from_the_project(self):
        self.write(self.unpacked, "inc_proj.nss", "int Two() { return 2; }\n")
        self.write(self.staged, "inc_new.nss", '#include "inc_proj"\nint Four() { return Two() * 2; }\n')
        self.write(self.staged, "q_ok.nss", '#include "inc_new"\nvoid main() { SetLocalInt(OBJECT_SELF, "n", Four()); }\n')
        result = QUESTS.compile_check(self.staged, self.unpacked)
        self.assertEqual((result["checked"], result["ok"]), (1, True), result)
        self.assertEqual(sorted(os.listdir(self.staged)), ["inc_new.nss", "q_ok.nss"])   # no .ncs left behind

    def test_a_broken_script_fails_the_check(self):
        self.write(self.staged, "q_bad.nss", "void main() { NoSuchFunction(); }\n")
        result = QUESTS.compile_check(self.staged, self.unpacked)
        self.assertFalse(result["ok"])
        self.assertTrue(result["output"])


if __name__ == "__main__":
    unittest.main()
