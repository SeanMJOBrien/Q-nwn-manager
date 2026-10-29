"""Random camp events: geometry, generated scripts, event/gate wiring, ownership, idempotency, previews, spot suggestions."""

from __future__ import annotations

import math
import unittest

from tests.fixture import MiniTfnCase  # noqa: F401  (sets sys.path)

from tfnstudio import campevent as CE
from tfnstudio import gffjson as G
from tfnstudio import index as IX
from tfnstudio import instances as I
from tfnstudio import prefabs as PF
from tfnstudio import validate as V
from tfnstudio.camps import CampBuilder, PlanError, summarize_plan, validate_plan
from tfnstudio.changeset import ChangeSet, apply_changeset, undo_applied
from tfnstudio.walkmesh import Probe, WalkGrid

PLAN = {
    "id": "wolf_den",
    "title": "Wolf den",
    "area": "bandit_cave",
    "cr": 7,
    "objects": [
        {"kind": "placeable", "resref": "_campfire", "x": 40.0, "y": 40.0, "facing": 0},
        {"kind": "placeable", "resref": "treas_barrel", "x": 42.0, "y": 40.5, "facing": 0},
        {"kind": "creature", "resref": "bandit", "x": 44.0, "y": 44.0, "facing": 180, "tag": "camp_guard"},
        {"kind": "creature", "resref": "bandit_dog", "x": 41.0, "y": 36.0, "facing": 90},
    ],
    "event_chance": 20,
    "camp_event": {
        "origin": {"x": 40, "y": 40, "facing": 90},
        "spots": [{"x": 12, "y": 60, "facing": 0}, {"x": 60, "y": 20, "facing": 135}, {"x": 20, "y": 20, "facing": 270}],
    },
}


def plan(**changes):
    out = G.clone(PLAN)
    camp = changes.pop("camp_event", None)
    out.update(changes)
    if camp is not None:
        out["camp_event"] = {**out["camp_event"], **camp} if camp else camp
    return out


class FakeWalk:
    """Stand-in for the tile walkmesh: the ground rises 0.05 m per metre towards the east and a 4 m wide strip is blocked."""

    SIZE = 80

    def __init__(self, blocked=((30.0, 34.0),)):
        self.blocked = blocked

    def available(self):
        return True

    def prepare(self, are):
        pass

    def _is_blocked(self, x):
        return any(lo <= x < hi for lo, hi in self.blocked)

    def probe(self, are, x, y):
        if not (0 <= x < self.SIZE and 0 <= y < self.SIZE):
            return Probe(False, error="outside the area")
        z = round(0.05 * x, 4)
        if self._is_blocked(x):
            return Probe(False, z, 7, "Water")
        return Probe(True, z, 1, "Dirt")

    def grid(self, are):
        g = WalkGrid(self.SIZE, self.SIZE)
        for y in range(self.SIZE):
            for x in range(self.SIZE):
                g.rows[y][x] = 0 if self._is_blocked(x + 0.5) else 1
        return g


def make_git(events=(), chance=None, event_wp=True):
    """A minimal area GIT dict for the wiring helpers."""
    git: dict = {}
    for n, script in enumerate(events, 1):
        if script:
            G.set_var(git, f"event{n}", script)
    if chance is not None:
        G.set_var(git, "event_chance", chance)
    if event_wp:
        bp = {"TemplateResRef": G.resref("_wp_event"), "Tag": G.cexostring("")}
        I.add_instance(git, "waypoint", I.waypoint_instance(bp, 10.0, 10.0, 0.0, 90.0))
    return git


def reader(files):
    return lambda name: files.get(name)


def event_text(plan_id, name="x"):
    return f"// Random camp: {name}\n// tfn-studio camp event: plan {plan_id}\nvoid main() {{}}\n"


def gate_text(plan_id, chain="-"):
    return f"// Gate\n// tfn-studio camp gate: plan {plan_id}\n// tfn-studio chains: {chain}\nvoid main() {{}}\n"


class GeometryTests(unittest.TestCase):
    ORIGIN = {"x": 40.0, "y": 40.0, "facing": 90.0}

    def test_same_spot_changes_nothing(self):
        self.assertEqual(CE.transform(42, 41, 10, self.ORIGIN, dict(self.ORIGIN)), (42, 41, 10))

    def test_same_direction_only_moves(self):
        x, y, f = CE.transform(42, 41, 10, self.ORIGIN, {"x": 100, "y": 5, "facing": 90})
        self.assertAlmostEqual(x, 102)
        self.assertAlmostEqual(y, 6)
        self.assertAlmostEqual(f, 10)

    def test_turning_the_camp_is_counter_clockwise_about_the_pivot(self):
        # the camp's "front" faces north (90); the spot faces west (180): a quarter turn to the left
        x, y, f = CE.transform(42, 40, 0, self.ORIGIN, {"x": 40, "y": 40, "facing": 180})
        self.assertAlmostEqual(x, 40)
        self.assertAlmostEqual(y, 42)       # the object east of the pivot is now north of it
        self.assertAlmostEqual(f, 90)

    def test_facing_wraps(self):
        _x, _y, f = CE.transform(40, 40, 300, self.ORIGIN, {"x": 40, "y": 40, "facing": 270})
        self.assertAlmostEqual(f, 120)      # 300 + 180 = 480 -> 120

    def test_matches_prefab_stamping(self):
        pf = {"id": "t", "items": [{"kind": "placeable", "resref": "a", "dx": 2, "dy": 0.5, "facing": 30}]}
        for rotation in (0, 45, 90, 200, 330):
            stamped = PF.stamp(pf, 50, 50, rotation=rotation)[0]
            origin = {"x": 0, "y": 0, "facing": 90}
            x, y, f = CE.transform(2, 0.5, 30, origin, {"x": 50, "y": 50, "facing": 90 + rotation})
            self.assertAlmostEqual(x, stamped["x"], places=3)
            self.assertAlmostEqual(y, stamped["y"], places=3)
            self.assertAlmostEqual(f, stamped["facing"], places=3)

    def test_candidates(self):
        ce = CE.parse_camp_event({"spots": [{"x": 1, "y": 2, "facing": 10}]}, "p")
        cands = CE.candidates(ce, self.ORIGIN)
        self.assertEqual([c["label"] for c in cands], ["spot 1"])
        ce["include_origin"] = True
        self.assertEqual([c["label"] for c in CE.candidates(ce, self.ORIGIN)], ["design location", "spot 1"])
        ce["spots"] = []
        ce["include_origin"] = False
        self.assertEqual([c["label"] for c in CE.candidates(ce, self.ORIGIN)], ["design location"])


class NameAndOwnershipTests(unittest.TestCase):
    def test_script_names_fit_the_resref_limit(self):
        self.assertEqual(CE.default_script("wolf_den"), "eve_wolf_den")
        self.assertEqual(CE.default_script("eve_wolf_den"), "eve_wolf_den")
        a = CE.default_script("a_very_long_camp_name_one")
        b = CE.default_script("a_very_long_camp_name_two")
        self.assertLessEqual(len(a), 16)
        self.assertLessEqual(len(b), 16)
        self.assertNotEqual(a, b)                       # a hash suffix keeps long names apart
        self.assertEqual(a, CE.default_script("a_very_long_camp_name_one"))
        self.assertTrue(CE.SCRIPT_RE.match(a))
        self.assertEqual(CE.gate_script_name("eve_wolf_den"), "spw_wolf_den")
        self.assertLessEqual(len(CE.gate_script_name("eve_a_very_long_name")), 16)

    def test_marker_tag_fits_and_is_stable(self):
        self.assertEqual(CE.camp_tag("wolf_den"), "ce_wolf_den")
        long_a, long_b = "x" * 31 + "a", "x" * 31 + "b"
        self.assertLessEqual(len(CE.camp_tag(long_a)), 32)
        self.assertNotEqual(CE.camp_tag(long_a), CE.camp_tag(long_b))

    def test_headers_identify_generated_scripts(self):
        self.assertEqual(CE.generated_by(event_text("wolf_den")), ("event", "wolf_den"))
        self.assertEqual(CE.generated_by(gate_text("wolf_den")), ("gate", "wolf_den"))
        self.assertIsNone(CE.generated_by("void main() {}\n"))
        self.assertIsNone(CE.generated_by(None))
        self.assertEqual(CE.chain_of(gate_text("p", "spawn_x")), "spawn_x")
        self.assertEqual(CE.chain_of(gate_text("p", "-")), "")

    def test_only_own_scripts_may_be_overwritten(self):
        CE.check_script_free(None, "event", "wolf_den", "eve_wolf_den")
        CE.check_script_free(event_text("wolf_den"), "event", "wolf_den", "eve_wolf_den")
        for existing in ("void main() {}\n", event_text("other_plan"), gate_text("wolf_den")):
            with self.assertRaises(CE.CampEventError, msg=existing):
                CE.check_script_free(existing, "event", "wolf_den", "eve_wolf_den")
        with self.assertRaises(CE.CampEventError):
            CE.check_script_free(None, "event", "wolf_den", "nw_c2_default1", elsewhere=True)


class ParseTests(unittest.TestCase):
    def test_absent_or_disabled(self):
        for raw in (None, {}, False, {"enabled": False, "script": "x"}):
            self.assertIsNone(CE.parse_camp_event(raw, "p"))

    def test_defaults_and_normalisation(self):
        ce = CE.parse_camp_event({"spots": [{"x": "5", "y": 6, "facing": 370}]}, "wolf_den")
        self.assertEqual((ce["script"], ce["gate"], ce["weight"]), ("eve_wolf_den", "spw_wolf_den", 1))
        self.assertEqual(ce["spots"], [{"x": 5.0, "y": 6.0, "facing": 10.0}])
        self.assertIsNone(ce["origin"])
        self.assertIsNone(ce["replaces_group"])
        self.assertEqual(ce["replace_radius"], 0)
        ce = CE.parse_camp_event({"script": "EVE_Bears2", "weight": 2, "replaces_group": "3", "replace_radius": 15,
                                  "origin": {"x": 1, "y": 2}}, "p")
        self.assertEqual((ce["script"], ce["weight"], ce["replaces_group"], ce["replace_radius"]), ("eve_bears2", 2, 3, 15.0))
        self.assertEqual(ce["origin"], {"x": 1.0, "y": 2.0, "facing": 90.0})

    def test_rejects_unusable_values(self):
        for bad in ("x", {"script": "Bad Name"}, {"script": "a" * 17}, {"weight": 0}, {"weight": 9}, {"weight": "many"},
                    {"replaces_group": 12}, {"replaces_group": "z"}, {"replace_radius": -1}, {"replace_radius": 1000},
                    {"spots": "nope"}, {"spots": [{"x": 1}]}, {"spots": [{"x": 1, "y": float("nan")}]},
                    {"spots": [{"x": i, "y": i} for i in range(CE.MAX_SPOTS + 1)]}, {"origin": {"x": 1}}):
            with self.assertRaises(CE.CampEventError, msg=str(bad)):
                CE.parse_camp_event(bad, "p")


class EventSlotTests(unittest.TestCase):
    """TFN counts events from event1 and stops at the first empty slot (area_init.nss), so the slots must stay contiguous."""

    def test_the_game_stops_counting_at_a_gap(self):
        self.assertEqual(CE.event_run(make_git(["a", "b", "", "d"])), ["a", "b"])
        self.assertEqual(CE.event_run(make_git([])), [])

    def test_plan_event_run(self):
        self.assertEqual(CE.plan_event_run(["a", "b"], "me", 1), ["a", "b", "me"])
        self.assertEqual(CE.plan_event_run(["a", "me", "b"], "me", 1), ["a", "me", "b"])         # keeps its place
        self.assertEqual(CE.plan_event_run(["me", "a", "me"], "me", 1), ["me", "a"])             # surplus dropped
        self.assertEqual(CE.plan_event_run(["a", "me"], "me", 3), ["a", "me", "me", "me"])

    def test_write_event_run_compacts_and_clears(self):
        git = make_git(["a", "b", "c"])
        self.assertEqual(CE.write_event_run(git, ["a", "c"]), [])
        gv = G.vars_of(git)
        self.assertEqual([gv.get("event1"), gv.get("event2"), gv.get("event3")], ["a", "c", None])

    def test_write_event_run_warns_when_an_orphan_becomes_reachable(self):
        git = make_git(["a", "b"])
        G.set_var(git, "event4", "orphan")                  # unreachable: event3 is empty
        warnings = CE.write_event_run(git, ["a", "b", "c"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("event4", warnings[0])

    def test_apply_wiring_appends_and_is_stable(self):
        ce = CE.parse_camp_event({"weight": 2}, "p")
        git = make_git(["eve_adventure"], chance=20)
        w = CE.apply_wiring(git, reader({"eve_adventure": "void main(){}"}), "p", ce)
        self.assertEqual(w.slots, [2, 3])
        self.assertEqual(w.other_events, ["eve_adventure"])
        self.assertEqual(CE.event_run(git), ["eve_adventure", "eve_p", "eve_p"])
        snapshot = G.dumps(git)
        CE.apply_wiring(git, reader({"eve_adventure": "void main(){}", "eve_p": event_text("p")}), "p", ce)
        self.assertEqual(G.dumps(git), snapshot)             # the second run changes nothing

    def test_apply_wiring_refuses_when_the_nine_slots_are_full(self):
        ce = CE.parse_camp_event({"weight": 1}, "p")
        git = make_git([f"s{n}" for n in range(1, 10)])
        with self.assertRaises(CE.CampEventError):
            CE.apply_wiring(git, reader({}), "p", ce)

    def test_chance_per_refresh(self):
        git = make_git(["a", "eve_p", "b"], chance=20)
        chance, is_default, total, p = CE.effective_chance(git, 1)
        self.assertEqual((chance, is_default, total), (20, False, 3))
        self.assertAlmostEqual(p, 0.2 / 3)
        _c, is_default, _t, _p = CE.effective_chance(make_git(["a"]), 1)
        self.assertTrue(is_default)
        self.assertEqual(CE.effective_chance(make_git(["a"]), 1)[0], 50)                 # TFN: unset means 50
        zero = make_git(["a"], chance=0)
        self.assertEqual(CE.effective_chance(zero, 1)[0], 50)                            # ... and so does 0
        self.assertEqual(CE.effective_chance(make_git(["a"], event_wp=False), 1)[3], 0.0)  # no event waypoint: never runs

    def test_release_stale_removes_only_this_plans_scripts_and_closes_the_gap(self):
        files = {"eve_old": event_text("p"), "eve_other": event_text("q"), "eve_adventure": "void main(){}"}
        git = make_git(["eve_adventure", "eve_old", "eve_other"])
        notes = CE.release_stale(git, reader(files), "p", "eve_new", None)
        self.assertEqual(CE.event_run(git), ["eve_adventure", "eve_other"])
        self.assertTrue(any("eve_old" in n for n in notes))

    def test_release_stale_restores_the_chained_spawn_script(self):
        files = {"spw_p": gate_text("p", "spawn_x")}
        git = make_git([])
        G.set_var(git, "random2_spawn_script", "spw_p")
        notes = CE.release_stale(git, reader(files), "p", None, None)
        self.assertEqual(G.get_var(git, "random2_spawn_script"), "spawn_x")
        self.assertTrue(notes)
        git = make_git([])
        G.set_var(git, "random2_spawn_script", "spw_p")
        files["spw_p"] = gate_text("p", "-")
        CE.release_stale(git, reader(files), "p", None, None)
        self.assertIsNone(G.get_var(git, "random2_spawn_script"))

    def test_release_stale_keeps_the_current_gate_and_moves_a_stale_one(self):
        files = {"spw_p": gate_text("p", "-")}
        git = make_git([])
        G.set_var(git, "random2_spawn_script", "spw_p")
        self.assertEqual(CE.release_stale(git, reader(files), "p", None, ("spw_p", 2)), [])
        self.assertEqual(G.get_var(git, "random2_spawn_script"), "spw_p")
        notes = CE.release_stale(git, reader(files), "p", None, ("spw_p", 3))               # now replaces group 3
        self.assertIsNone(G.get_var(git, "random2_spawn_script"))
        self.assertTrue(notes)

    def test_wire_gate_chains_and_protects(self):
        git = make_git([])
        G.set_var(git, "random1", "ute_a")
        G.set_var(git, "random1_spawn_script", "spawn_x")
        self.assertEqual(CE.wire_gate(git, reader({}), "p", "spw_p", 1), "spawn_x")
        self.assertEqual(G.get_var(git, "random1_spawn_script"), "spw_p")
        # run again with the gate already in place: the chain is read back from the gate script
        self.assertEqual(CE.wire_gate(git, reader({"spw_p": gate_text("p", "spawn_x")}), "p", "spw_p", 1), "spawn_x")
        # another plan's gate is never taken over
        G.set_var(git, "random1_spawn_script", "spw_q")
        with self.assertRaises(CE.CampEventError):
            CE.wire_gate(git, reader({"spw_q": gate_text("q")}), "p", "spw_p", 1)
        with self.assertRaises(CE.CampEventError):                       # the group must exist
            CE.wire_gate(git, reader({}), "p", "spw_p", 5)


class ScriptTextTests(unittest.TestCase):
    def variant(self, label="spot 1", x=12.0, y=60.0, facing=0.0, quest=False, props=True):
        objs = []
        if props:
            objs.append(CE.VObj("placeable", "treas_barrel", x + 1, y, 0.5, 90.0))
        objs.append(CE.VObj("creature", "bandit", x - 1, y, 0.5, 180.0, tag="camp_guard", quest_npc=quest))
        return CE.Variant(label, x, y, 0.5, facing, objs)

    def test_one_function_per_spot_and_a_random_choice(self):
        src = CE.event_script_source("wolf_den", "Wolf den", "bandit_cave",
                                     [self.variant("spot 1"), self.variant("spot 2", 60, 20, 135)], tag="ce_wolf_den")
        self.assertEqual(CE.generated_by(src), ("event", "wolf_den"))
        self.assertIn("void CampSpot1(object oArea)", src)
        self.assertIn("void CampSpot2(object oArea)", src)
        self.assertIn("switch (Random(2))", src)
        self.assertIn("case 1: CampSpot2(oArea); break;", src)
        self.assertIn('GetResRef(oArea) != "bandit_cave"', src)
        self.assertIn('GetObjectByTag(CAMP_TAG)', src)
        self.assertIn('"nw_waypoint001", 60.0000, 20.0000, 0.5000, 135.0000, CAMP_TAG', src)
        self.assertIn('"bandit", 59.0000, 20.0000, 0.5000, 180.0000, "camp_guard"', src)

    def test_a_single_spot_needs_no_switch(self):
        src = CE.event_script_source("p", "T", "a", [self.variant()], tag="ce_p")
        self.assertNotIn("switch", src)
        self.assertIn("CampSpot1(oArea);", src)

    def test_helpers_are_only_included_when_needed(self):
        creatures_only = CE.event_script_source("p", "T", "a", [self.variant(props=False)], tag="ce_p")
        self.assertNotIn("nwnx_object", creatures_only)
        self.assertNotIn("CampFinishProp", creatures_only)
        self.assertNotIn("nwnx_creature", creatures_only)
        with_props = CE.event_script_source("p", "T", "a", [self.variant()], tag="ce_p")
        self.assertIn('#include "nwnx_object"', with_props)
        self.assertIn("CampFinishProp(CampCreate(OBJECT_TYPE_PLACEABLE", with_props)
        self.assertIn('ExecuteScript("treas_init", oProp)', with_props)           # treasure props, like area_init
        quest = CE.event_script_source("p", "T", "a", [self.variant(quest=True)], tag="ce_p")
        self.assertIn('#include "nwnx_creature"', quest)
        self.assertIn("CampQuestNpc(oArea, CampCreate(OBJECT_TYPE_CREATURE", quest)

    def test_titles_and_strings_cannot_break_the_script(self):
        src = CE.event_script_source("p", "Bad\nname */ é", "a", [self.variant()], tag="ce_p")
        self.assertEqual(src.splitlines()[0], "// Random camp: Bad name */ ? (plan p) in area a.")
        self.assertEqual(CE.comment_text("x" * 200), "x" * 80)
        self.assertEqual(CE._nwstr('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')

    def test_gate_for_the_whole_group_or_a_radius(self):
        whole = CE.gate_script_source("p", "a", 2, 0, "", tag="ce_p")
        self.assertEqual(CE.generated_by(whole), ("gate", "p"))
        self.assertEqual(CE.chain_of(whole), "")
        self.assertIn("DestroyObject(OBJECT_SELF);", whole)
        self.assertNotIn("GetDistanceBetween", whole)
        self.assertNotIn("ExecuteScript", whole)
        near = CE.gate_script_source("p", "a", 2, 25, "spawn_x", tag="ce_p")
        self.assertEqual(CE.chain_of(near), "spawn_x")
        self.assertIn("GetDistanceBetween(OBJECT_SELF, oCamp)", near)
        self.assertIn("fDist <= 25.0000", near)
        self.assertIn('ExecuteScript("spawn_x", OBJECT_SELF);', near)


class PlanBlockTests(unittest.TestCase):
    def test_plans_without_a_camp_event_are_unchanged(self):
        p = validate_plan({"id": "ok", "area": "x"})
        self.assertIsNone(p["camp_event"])
        self.assertIsNone(summarize_plan({"id": "ok", "area": "x"})["camp_event"])

    def test_camp_event_needs_something_to_place(self):
        with self.assertRaises(PlanError):
            validate_plan({"id": "ok", "area": "x", "camp_event": {"spots": []},
                           "objects": [{"kind": "marker", "group": 1, "x": 1, "y": 1}]})
        # the live preview may ask before anything is placed
        p = validate_plan({"id": "ok", "area": "x", "camp_event": {}, "objects": []}, require_template=False)
        self.assertIsNone(p["camp_event"])             # {} means "off"
        p = validate_plan({"id": "ok", "area": "x", "camp_event": {"weight": 1}, "objects": []}, require_template=False)
        self.assertEqual(p["camp_event"]["weight"], 1)

    def test_bad_blocks_are_plan_errors(self):
        with self.assertRaises(PlanError):
            validate_plan({"id": "ok", "area": "x", "camp_event": {"weight": 7},
                           "objects": [{"kind": "creature", "resref": "bandit", "x": 1, "y": 1}]})
        with self.assertRaises(PlanError):               # a tag that cannot sit safely in a script
            validate_plan({"id": "ok", "area": "x", "camp_event": {"weight": 1},
                           "objects": [{"kind": "creature", "resref": "bandit", "x": 1, "y": 1, "tag": 'bad"tag'}]})

    def test_summary(self):
        s = summarize_plan(plan())
        self.assertEqual(s["camp_event"], {"script": "eve_wolf_den", "spots": 3, "weight": 1, "replaces_group": None})


class CampEventBuildTests(MiniTfnCase):
    AREA = "bandit_cave"

    def build(self, pl, walk=None):
        return CampBuilder(self.project(), walk=walk).build(pl)

    def git_of(self, cs):
        return cs.load("git", self.AREA)

    def compile_errors(self, cs, name):
        p = self.project()
        if p.tool("nwnsc") is None:
            self.skipTest("nwnsc not available")
        return V.compile_script(p, name, cs.pending_text(cs.rel_nss(name)))

    # ------------------------------------------------------------------ what gets written
    def test_nothing_of_the_camp_goes_into_the_area_file(self):
        cs = self.build(plan())
        git = self.git_of(cs)
        mine = [(k, G.get(i, "TemplateResRef")) for k, i in I.plan_instances(git, "wolf_den")]
        self.assertEqual(mine, [("waypoint", "_wp_event")])          # only the event waypoint the area lacked
        self.assertEqual(sorted(cs.files), ["src/git/bandit_cave.git.json", "src/nss/eve_wolf_den.nss"])
        gv = G.vars_of(git)
        self.assertEqual((gv["event1"], gv["event_chance"], gv["cr"]), ("eve_wolf_den", 20, 7))
        self.assertTrue(any("added one" in n and "_wp_event" in n for n in cs.notes), cs.notes)

    def test_markers_and_waypoints_stay_permanent(self):
        pl = plan()
        pl["objects"] += [{"kind": "marker", "group": 2, "x": 30.0, "y": 30.0},
                          {"kind": "waypoint", "resref": "_wp_event", "x": 35.0, "y": 35.0}]
        pl["groups"] = [{"n": 2, "ute": "bandit_moderate", "spawns": 4}]
        cs = self.build(pl)
        git = self.git_of(cs)
        mine = sorted(G.get(i, "TemplateResRef") for _k, i in I.plan_instances(git, "wolf_den"))
        self.assertEqual(mine, ["_wp_event", "random2"])             # the plan's own event waypoint: no second one added
        self.assertFalse(any("added one" in n for n in cs.notes))

    def test_the_script_has_every_spot_and_is_deterministic(self):
        cs = self.build(plan())
        src = cs.pending_text("src/nss/eve_wolf_den.nss")
        self.assertEqual(src.count("void CampSpot"), 3)
        self.assertIn("switch (Random(3))", src)
        # spot 2 is the barrel at (+2, +0.5) from the pivot, turned 45 degrees left about (60, 20)
        self.assertIn('"treas_barrel", 61.0607, 21.7678,', src)
        self.assertEqual(src, self.build(plan()).pending_text("src/nss/eve_wolf_den.nss"))

    def test_generated_scripts_compile(self):
        pl = plan(camp_event={"replaces_group": 1, "replace_radius": 20})
        cs = self.build(pl)
        self.assertEqual(self.compile_errors(cs, "eve_wolf_den"), [])
        self.assertEqual(self.compile_errors(cs, "spw_wolf_den"), [])
        # a negative control: the compiler really runs and would catch a typo
        p = self.project()
        broken = cs.pending_text("src/nss/eve_wolf_den.nss").replace("CampSpot2(oArea);", "CampSpotTwo(oArea);")
        self.assertTrue(V.compile_script(p, "eve_wolf_den", broken))

    def test_quest_giver_and_all_prop_kinds_compile(self):
        p = self.project()
        npc = p.read("utc", "bandit")
        G.set_field(npc, "TemplateResRef", "resref", "camp_npc")
        G.set_var(npc, "quest1", "01_q_test")
        G.write(p.json_path("utc", "camp_npc"), npc)
        pl = plan()
        pl["objects"].append({"kind": "creature", "resref": "camp_npc", "x": 38.0, "y": 38.0, "facing": 0})
        cs = self.build(pl)
        src = cs.pending_text("src/nss/eve_wolf_den.nss")
        self.assertIn('CampQuestNpc(oArea, CampCreate(OBJECT_TYPE_CREATURE, oArea, "camp_npc"', src)
        self.assertEqual(self.compile_errors(cs, "eve_wolf_den"), [])

    def test_the_whole_change_set_validates(self):
        p = self.project()
        cs = CampBuilder(p).build(plan(camp_event={"replaces_group": 1}))
        issues = V.validate_changeset(p, cs, roundtrip=False)
        self.assertEqual([i.message for i in issues if i.level == "error"], [])

    # ------------------------------------------------------------------ wiring
    def test_chance_and_notes(self):
        cs = self.build(plan())
        self.assertTrue(any("about 20.0% of area refreshes" in n and "6.7% per spot" in n for n in cs.notes), cs.notes)
        cs = self.build(plan(event_chance=None))
        self.assertTrue(any("TFN default" in n and "50.0%" in n for n in cs.notes), cs.notes)

    def test_weight_takes_that_many_slots(self):
        cs = self.build(plan(camp_event={"weight": 2}, events=[{"n": 1, "script": "eve_adventure"}]))
        gv = G.vars_of(self.git_of(cs))
        self.assertEqual([gv["event1"], gv["event2"], gv["event3"]], ["eve_adventure", "eve_wolf_den", "eve_wolf_den"])
        self.assertTrue(any("2 of 3 event slot(s)" in n for n in cs.notes), cs.notes)
        self.assertTrue(any("share the event roll" in n for n in cs.notes), cs.notes)

    def test_group_replacement_wires_a_gate_that_chains(self):
        pl = plan(camp_event={"replaces_group": 2, "replace_radius": 0},
                  groups=[{"n": 2, "ute": "bandit_moderate", "spawns": 4, "script": "eve_adventure"}])
        cs = self.build(pl)
        gv = G.vars_of(self.git_of(cs))
        self.assertEqual(gv["random2_spawn_script"], "spw_wolf_den")
        gate = cs.pending_text("src/nss/spw_wolf_den.nss")
        self.assertEqual(CE.chain_of(gate), "eve_adventure")
        self.assertEqual(CE.generated_by(gate), ("gate", "wolf_den"))
        self.assertTrue(any("random2 loses all of its creatures" in n for n in cs.notes), cs.notes)

    def test_replacing_a_group_the_area_does_not_have_is_an_error(self):
        with self.assertRaises(PlanError) as cm:
            self.build(plan(camp_event={"replaces_group": 6}))
        self.assertIn("random6", str(cm.exception))

    # ------------------------------------------------------------------ safety
    def test_other_peoples_scripts_are_never_overwritten(self):
        p = self.project()
        if not p.script_exists("eve_adventure"):
            self.skipTest("this TFN checkout has no eve_adventure")
        with self.assertRaises(PlanError) as cm:
            self.build(plan(camp_event={"script": "eve_adventure"}))
        self.assertIn("belongs to", str(cm.exception))
        base = p.root / "nwn-base-scripts" / "nw_c2_default1.nss"
        if base.is_file():
            with self.assertRaises(PlanError) as cm:
                self.build(plan(camp_event={"script": "nw_c2_default1"}))
            self.assertIn("base-game", str(cm.exception))

    def test_unknown_blueprints_are_plan_errors(self):
        pl = plan()
        pl["objects"][0]["resref"] = "no_such_prop_zz"
        with self.assertRaises(PlanError):
            self.build(pl)

    # ------------------------------------------------------------------ re-staging
    def test_restaging_changes_nothing_and_undo_restores(self):
        p = self.project()
        before = p.read("git", self.AREA)
        first = CampBuilder(p).build(plan(camp_event={"replaces_group": 1, "replace_radius": 30}))
        res = apply_changeset(p, first)
        self.assertTrue(res.ok, res.problems)
        try:
            again = CampBuilder(p).build(plan(camp_event={"replaces_group": 1, "replace_radius": 30}))
            self.assertEqual([f.rel for f in again.changed_files()], [], again.diff())
        finally:
            undo_applied(p, first.id)
        self.assertEqual(p.read("git", self.AREA), before)
        self.assertFalse(p.script_exists("eve_wolf_den"))

    def test_leaving_event_mode_unwires_everything(self):
        p = self.project()
        pl = plan(camp_event={"replaces_group": 1, "replace_radius": 0},
                  groups=[{"n": 1, "ute": "bandit_moderate", "spawns": 4, "script": "eve_adventure"}])
        first = CampBuilder(p).build(pl)
        self.assertTrue(apply_changeset(p, first).ok)
        try:
            normal = G.clone(pl)
            normal["camp_event"] = None
            normal["groups"] = []                       # the group's script must come back from the gate's chain, not the plan
            second = CampBuilder(p).build(normal)
            git = self.git_of(second)
            gv = G.vars_of(git)
            self.assertNotIn("event1", gv)
            self.assertEqual(gv["random1_spawn_script"], "eve_adventure")
            kinds = sorted(G.get(i, "TemplateResRef") for _k, i in I.plan_instances(git, "wolf_den"))
            # the camp is a plain camp again (and the event waypoint that only the event needed is gone)
            self.assertEqual(kinds, ["_campfire", "bandit", "bandit_dog", "treas_barrel"])
            self.assertTrue(any("The camp scripts stay" in n for n in second.notes), second.notes)
        finally:
            undo_applied(p, first.id)

    def test_entering_event_mode_takes_the_objects_out_of_the_area_file(self):
        p = self.project()
        normal = G.clone(PLAN)
        normal["camp_event"] = None
        first = CampBuilder(p).build(normal)
        self.assertTrue(apply_changeset(p, first).ok)
        try:
            self.assertEqual(len(list(I.plan_instances(p.read("git", self.AREA), "wolf_den"))), 4)
            second = CampBuilder(p).build(plan())
            left = [G.get(i, "TemplateResRef") for _k, i in I.plan_instances(self.git_of(second), "wolf_den")]
            self.assertEqual(left, ["_wp_event"])
        finally:
            undo_applied(p, first.id)

    def test_renaming_the_script_moves_the_wiring(self):
        p = self.project()
        first = CampBuilder(p).build(plan())
        self.assertTrue(apply_changeset(p, first).ok)
        try:
            second = CampBuilder(p).build(plan(camp_event={"script": "eve_wolves2"}))
            self.assertEqual(CE.event_run(self.git_of(second)), ["eve_wolves2"])
            self.assertTrue(any("eve_wolf_den" in n and "no longer used" in n for n in second.notes), second.notes)
        finally:
            undo_applied(p, first.id)

    def test_two_camps_share_an_area_but_not_a_group(self):
        p = self.project()
        a = CampBuilder(p).build(plan(camp_event={"replaces_group": 1}))
        self.assertTrue(apply_changeset(p, a).ok)
        try:
            other = plan(id="bear_den", title="Bear den")
            other["camp_event"] = {"origin": {"x": 40, "y": 40, "facing": 90}, "spots": [{"x": 20, "y": 60, "facing": 0}]}
            b = CampBuilder(p).build(other)
            self.assertEqual(CE.event_run(self.git_of(b)), ["eve_wolf_den", "eve_bear_den"])
            self.assertTrue(any("1 of 2 event slot(s)" in n for n in b.notes), b.notes)
            clash = G.clone(other)
            clash["camp_event"]["replaces_group"] = 1
            with self.assertRaises(PlanError) as cm:
                CampBuilder(p).build(clash)
            self.assertIn("one camp per group", str(cm.exception))
        finally:
            undo_applied(p, a.id)

    # ------------------------------------------------------------------ the ground
    def test_heights_come_from_the_walkmesh_for_every_object(self):
        info = CampBuilder(self.project(), walk=FakeWalk()).event_info(plan())
        self.assertEqual(len(info["variants"]), 3)
        for v in info["variants"]:
            self.assertEqual(v["z_how"], "walkmesh")
            for o in v["objects"]:
                self.assertAlmostEqual(o["z"], round(0.05 * o["x"], 4), places=3)

    def test_without_a_walkmesh_a_camp_stands_at_one_height(self):
        info = CampBuilder(self.project()).event_info(plan())
        for v in info["variants"]:
            self.assertEqual({o["z"] for o in v["objects"]}, {v["z"]})

    def test_an_explicit_height_stays_above_the_ground(self):
        pl = plan()
        pl["objects"][1]["z"] = round(0.05 * 42.0 + 0.5, 4)           # half a metre above the ground at the design location
        info = CampBuilder(self.project(), walk=FakeWalk()).event_info(pl)
        for v in info["variants"]:
            barrel = next(o for o in v["objects"] if o["resref"] == "treas_barrel")
            self.assertAlmostEqual(barrel["z"], 0.05 * barrel["x"] + 0.5, places=3)

    def test_a_spot_on_blocked_ground_is_reported_per_spot(self):
        pl = plan(camp_event={"spots": [{"x": 12, "y": 60, "facing": 0}, {"x": 32, "y": 40, "facing": 90}]})
        info = CampBuilder(self.project(), walk=FakeWalk()).event_info(pl)
        good, bad = info["variants"]
        self.assertEqual([i for i in good["issues"] if i["level"] != "info"], [])
        text = " ".join(i["message"] for i in bad["issues"] if i["level"] == "warning")
        self.assertIn("non-walkable", text)
        self.assertIn("creature", text)
        cs = self.build(pl, walk=FakeWalk())                           # warnings do not stop staging
        self.assertTrue(any("spot 2" in w for w in cs.warnings), cs.warnings)

    def test_a_spot_that_pushes_the_camp_out_of_the_area_is_an_error(self):
        pl = plan(camp_event={"spots": [{"x": 78, "y": 78, "facing": 45}]})
        info = CampBuilder(self.project()).event_info(pl)             # the preview reports it ...
        self.assertTrue(any("outside the area" in e for e in info["errors"]), info["errors"])
        with self.assertRaises(PlanError) as cm:                      # ... staging refuses
            self.build(pl)
        self.assertIn("outside the area", str(cm.exception))

    def test_duplicate_spots_are_called_out(self):
        pl = plan(camp_event={"spots": [{"x": 12, "y": 60, "facing": 0}, {"x": 12.5, "y": 60, "facing": 0}]})
        info = CampBuilder(self.project()).event_info(pl)
        self.assertTrue(any("almost identical" in i["message"] for i in info["variants"][1]["issues"]))

    # ------------------------------------------------------------------ preview and suggestions
    def test_event_info_is_a_dry_run(self):
        p = self.project()
        before = p.read("git", self.AREA)
        info = CampBuilder(p).event_info(plan(camp_event={"replaces_group": 1}))
        self.assertTrue(info["enabled"])
        self.assertEqual(info["script"], "eve_wolf_den")
        self.assertEqual(info["gate"], "spw_wolf_den")
        self.assertEqual(len(info["variants"]), 3)
        self.assertEqual(info["wiring"]["slots"], [1])
        self.assertAlmostEqual(info["wiring"]["effective"], 0.2)
        self.assertEqual(info["wiring"]["gate"]["group"], 1)
        self.assertEqual(info["added_waypoint"]["x"], 12.0)
        self.assertEqual(info["footprint"], round(math.hypot(4, 4), 2))
        self.assertEqual(p.read("git", self.AREA), before)            # nothing was written
        self.assertFalse(p.script_exists("eve_wolf_den"))

    def test_event_info_edge_cases(self):
        p = self.project()
        self.assertEqual(CampBuilder(p).event_info(plan(camp_event={"enabled": False})), {"enabled": False})
        empty = CampBuilder(p).event_info(plan(objects=[], camp_event={"weight": 1}))
        self.assertTrue(empty["enabled"] and empty["empty"])
        self.assertIn("Place at least one", empty["message"])
        with self.assertRaises(PlanError):
            CampBuilder(p).event_info(plan(area="no_such_area"))

    def test_hand_placed_markers_are_offered_as_spots(self):
        p = self.project()
        pl = plan()
        pl["objects"] += [{"kind": "waypoint", "resref": "_wp_event", "x": 35.0, "y": 70.0, "facing": 180, "tag": "campsite_a"},
                          {"kind": "waypoint", "resref": "_wp_event", "x": 15.0, "y": 15.0, "facing": 0}]
        first = CampBuilder(p).build(pl)
        self.assertTrue(apply_changeset(p, first).ok)
        try:
            other = plan(id="other_camp")
            info = CampBuilder(p).event_info(other)
            spots = info["waypoint_spots"]
            self.assertEqual(len(spots), 2)
            self.assertEqual(sorted((s["x"], s["y"], s["facing"]) for s in spots), [(15.0, 15.0, 0.0), (35.0, 70.0, 180.0)])
            # the plan's own output is not offered back to it
            self.assertEqual(CampBuilder(p).event_info(pl)["waypoint_spots"], [])
            self.assertEqual(IX.summarize_area(self.AREA, p.read("are", self.AREA), p.read("git", self.AREA))["event_wps"], 2)
        finally:
            undo_applied(p, first.id)

    def test_suggested_spots_fit_the_camp_spread_out_and_are_repeatable(self):
        p = self.project()
        builder = CampBuilder(p, walk=FakeWalk())
        template = [o for o in PLAN["objects"]]
        origin = PLAN["camp_event"]["origin"]
        res = builder.suggest_spots(plan(camp_event={"spots": []}), 5, "seed-a")
        spots = res["spots"]
        self.assertGreaterEqual(len(spots), 3)
        self.assertLessEqual(len(spots), 5)
        walk = FakeWalk()
        for s in spots:
            self.assertEqual(s["facing"] % 45, 0)
            for o in template:                                         # the whole camp, turned to this spot, stands on open ground
                x, y, _f = CE.transform(o["x"], o["y"], o["facing"], origin, s)
                self.assertTrue(walk.probe(None, x, y).walkable, (s, o))
                if o["kind"] == "creature":
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        self.assertTrue(walk.probe(None, x + dx, y + dy).walkable, (s, o))
        for i, a in enumerate(spots):
            for b in spots[i + 1:]:
                self.assertGreaterEqual(math.hypot(a["x"] - b["x"], a["y"] - b["y"]), 10)
        self.assertEqual(spots, builder.suggest_spots(plan(camp_event={"spots": []}), 5, "seed-a")["spots"])
        # a suggested spot always stages without errors
        staged = builder.event_info(plan(camp_event={"spots": spots}))
        self.assertEqual(staged["errors"], [])
        # spots that are already placed are not suggested again
        placed = plan(camp_event={"spots": [{"x": s["x"], "y": s["y"], "facing": 0} for s in spots[:2]]})
        again = builder.suggest_spots(placed, 5, "seed-b")["spots"]
        for s in again:
            for t in spots[:2]:
                self.assertGreaterEqual(math.hypot(s["x"] - t["x"], s["y"] - t["y"]), 10)

    def test_no_room_means_no_suggestions(self):
        everything_blocked = FakeWalk(blocked=((0.0, 80.0),))
        self.assertEqual(CampBuilder(self.project(), walk=everything_blocked).suggest_spots(plan(), 4)["spots"], [])

    def test_suggestions_need_the_walkmesh(self):
        with self.assertRaises(PlanError) as cm:
            CampBuilder(self.project()).suggest_spots(plan(), 3)
        self.assertIn("walkmesh", str(cm.exception))


class EventLintTests(MiniTfnCase):
    def issues(self, **vars_):
        p = self.project()
        cs = ChangeSet(p, "t", "camp")
        git = cs.load("git", "bandit_cave")
        for k, v in vars_.items():
            G.set_var(git, k, v)
        cs.save("git", "bandit_cave", git)
        return V.validate_changeset(p, cs, roundtrip=False, compile_scripts=False)

    def test_events_after_an_empty_slot_never_run(self):
        msgs = [i.message for i in self.issues(event2="eve_adventure") if i.level == "warning"]
        self.assertTrue(any("event2" in m and "empty slot" in m for m in msgs), msgs)

    def test_events_without_an_event_waypoint_never_fire(self):
        msgs = [i.message for i in self.issues(event1="eve_adventure") if i.level == "warning"]
        self.assertTrue(any("_wp_event" in m for m in msgs), msgs)


if __name__ == "__main__":
    unittest.main()
