#!/usr/bin/env python3
"""Generate the starter prefab library (prefabs/*.json).

Run from the repo root:  python3 scripts/make_starter_prefabs.py [--check]
`--check` also verifies every resref exists in TFN (src/utp / src/utw / palette mined from GITs).
All resrefs below are ones TFN's own areas already use, so stamped output is valid in-game.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tfnstudio import prefabs as PF  # noqa: E402


def P(res, dx, dy, facing=0.0):
    return {"kind": "placeable", "resref": res, "dx": dx, "dy": dy, "facing": facing}


def M(group, dx, dy):
    return {"kind": "marker", "group": group, "dx": dx, "dy": dy, "facing": 0}


def W(res, dx, dy):
    return {"kind": "waypoint", "resref": res, "dx": dx, "dy": dy, "facing": 90}


def ring(make, n, r, start=0.0, inward=True):
    """n items evenly spaced on a circle of radius r; `make(dx, dy, facing)` builds each."""
    out = []
    for i in range(n):
        ang = start + 360.0 * i / n
        dx, dy = r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))
        out.append(make(round(dx, 2), round(dy, 2), round((ang + 180) % 360 if inward else ang, 1)))
    return out


PREFABS = [
    dict(id="camp_small", name="Small campfire camp",
         description="A campfire with three bedrolls, a barrel, sacks and a woodpile. Pure decoration.",
         tags=["camp", "decor", "neutral"],
         items=[P("plc_campfr", 0, 0)]
         + ring(lambda x, y, f: P("plc_bedrolls", x, y, f), 3, 2.6, 30)
         + [P("plc_sacks", 3.4, 1.2, 20), P("plc_barrel", -3.2, -2.6), P("plc_woodpile", 2.0, -3.4, 90)]),

    dict(id="camp_tents", name="Tent camp",
         description="Three tents around a pot fire, with bedrolls, crates and a weapon rack.",
         tags=["camp", "decor", "neutral"],
         items=[P("plc_campfrwpot", 0, 0)]
         + ring(lambda x, y, f: P("x2_plc_tent_r", x, y, f), 2, 5.8, 70)
         + ring(lambda x, y, f: P("x2_plc_tent_b", x, y, f), 1, 5.8, 310)
         + [P("plc_bedrolls", 2.2, 0.8, 200), P("plc_bedrolls", -2.0, -1.4, 20), P("plc_barrel", -1.6, 3.4),
            P("treas_crate", 3.2, -3.0, 40), P("plc_weaponrack", -4.4, -2.6, 0), P("plc_sacks", 1.0, -3.8, 80)]),

    dict(id="bandit_camp", name="Bandit camp (random spawns)",
         description="Tents, spit fire, table with chairs, kegs and a weapon rack, ringed by four `random1` "
                     "markers so a spawn group appears around it. Assign group 1 to a bandit encounter.",
         tags=["camp", "bandit", "spawn", "hostile"],
         items=[P("plc_campfrwspit", 0, 0, 0)]
         + ring(lambda x, y, f: P("x2_plc_tent_r", x, y, f), 2, 6.5, 60)
         + ring(lambda x, y, f: P("x2_plc_tent_b", x, y, f), 1, 6.5, 320)
         + [P("plc_table", 3.4, -0.6, 90), P("plc_chair", 3.4, 0.9, 270), P("plc_chair", 3.4, -2.1, 90),
            P("plc_keg", 4.6, 1.6, 30), P("plc_keg", 4.9, -3.0, 140), P("plc_sacks", -2.4, 2.8, 15),
            P("plc_box2", -3.4, -2.4, 70), P("plc_weaponrack", -4.2, 3.0, 90), P("plc_bones", 1.4, -2.2, 50)]
         + ring(lambda x, y, f: M(1, x, y), 4, 8.0, 20)),

    dict(id="goblin_camp", name="Goblin / orc camp (random spawns)",
         description="Pot fire and cauldron, skull poles at the entrance, bone piles, a cage and hay bedding; "
                     "five `random1` markers around it.",
         tags=["camp", "goblin", "orc", "spawn", "hostile"],
         items=[P("plc_campfrwpot", 0, 0), P("x0_cauldron", 2.6, 1.6, 200), P("x0_skullpole", -4.0, -7.4, 0),
                P("x0_skullpole", 4.0, -7.4, 0), P("plc_pileskulls", 4.6, 3.0, 30), P("plc_bones", -2.2, 2.4, 80),
                P("plc_bones", 1.2, -3.0, 200), P("plc_bones", -3.8, -1.8, 310), P("plc_bloodstain", 2.0, -1.0, 40),
                P("plc_bloodstain", -1.0, -2.0, 140), P("plc_humancage", -5.6, 2.6, 0),
                P("plc_haybundle", 3.4, -3.4, 60), P("plc_haybundle", -3.0, 4.2, 150)]
         + ring(lambda x, y, f: M(1, x, y), 5, 7.0, 15)),

    dict(id="hunter_camp", name="Hunter's camp",
         description="A lone tent, spit fire, woodpile, hay and a weapon rack. Peaceful - add an NPC separately.",
         tags=["camp", "decor", "neutral"],
         items=[P("x2_plc_tent_b", -3.6, 2.0, 340), P("plc_campfrwspit", 0, 0), P("plc_woodpile", 2.6, -2.6, 90),
                P("plc_haybundle", -2.6, -3.0, 20), P("plc_weaponrack", 3.6, 2.6, 180), P("plc_barrel", -5.0, -0.6),
                P("plc_sacks", -1.8, 4.0, 60), P("plc_bedrolls", 1.6, 2.0, 250)]),

    dict(id="ruined_camp", name="Raided / ruined camp",
         description="Burnt and broken wagons, corpses, blood and bones. One small loot chest (`treas_*` containers "
                     "roll TFN loot).",
         tags=["camp", "decor", "ruin", "loot"],
         items=[P("plc_burnwagon", -3.0, 1.5, 20), P("plc_ruinwagon", 3.6, -1.0, 100), P("plc_wagonwheel", -0.5, -3.0, 70),
                P("plc_wagonwheel", 6.0, 2.0, 10), P("plc_arrowcorpse", 0.5, 1.2, 190), P("plc_arrowcorpse", -4.8, -2.2, 300),
                P("plc_spearcorpse", 2.2, 3.4, 90), P("plc_bones", -1.8, 3.4, 40), P("plc_bones", 4.6, -3.6, 130),
                P("plc_bones", 0.0, -1.0, 250), P("plc_bloodstain", 0.2, 0.2, 10), P("plc_bloodstain", -4.4, -1.8, 100),
                P("plc_bloodstain", 2.0, 3.0, 200), P("treas_smallchest", 1.2, -4.4, 160), P("plc_barrel", -6.0, -3.6),
                P("plc_sacks", 5.8, -2.6, 30)]),

    dict(id="spider_nest", name="Spider nest (random spawns)",
         description="Webs and cocoons with a skeleton victim; four `random1` markers. Pair with a spider encounter.",
         tags=["nest", "spider", "spawn", "hostile"],
         items=[P("x2_plc_web", 0, 0, 10), P("x2_plc_web", 3.0, 2.0, 80), P("x2_plc_web", -3.4, 1.0, 150),
                P("x2_plc_web", 1.0, -3.6, 220), P("x2_plc_web", -2.0, -4.0, 300), P("spdcocoon001", 1.6, 1.4, 40),
                P("spdcocoon001", -1.4, -1.2, 120), P("spdcocoon001", 3.6, -1.6, 200), P("plc_bones", -0.4, 2.6, 60),
                P("nw_pl_skeleton", 2.0, -0.6, 90)]
         + ring(lambda x, y, f: M(1, x, y), 4, 6.5, 45)),

    dict(id="graveyard_small", name="Small graveyard (random spawns)",
         description="Six headstones in two rows, a dead tree and bones; four `random1` markers. Pair with an "
                     "undead encounter.",
         tags=["graveyard", "undead", "spawn", "hostile"],
         items=[P("plc_headstone", x, y, 270) for y in (2.5, -2.5) for x in (-3.0, 0.0, 3.0)]
         + [P("x0_deadtree", -6.0, 4.0), P("plc_bones", 1.4, 0.0, 30), P("nw_pl_skeleton", -1.4, -0.2, 120)]
         + ring(lambda x, y, f: M(1, x, y), 4, 7.0, 30)),

    dict(id="ambush_site", name="Roadside ambush (spawns + event points)",
         description="Four `random1` markers on either side of a path plus two `_wp_event` waypoints, boulders "
                     "and a dead tree for cover. Set `event1`/`event_chance` on the area to use the waypoints.",
         tags=["ambush", "spawn", "event", "hostile"],
         items=[M(1, -6.0, -4.0), M(1, 6.0, -2.0), M(1, -6.5, 3.5), M(1, 6.5, 4.5), W("_wp_event", 0, -5.0),
                W("_wp_event", 0, 5.0), P("plc_boulder", -4.4, 0.4, 20), P("plc_boulder", 4.8, -4.4, 140),
                P("x0_deadtree", 7.4, 1.2)]),

    dict(id="wagon_camp", name="Merchant wagon camp",
         description="Two wagons, a campfire, bedrolls, crates and barrels. Decoration for a travelling merchant.",
         tags=["camp", "decor", "neutral", "merchant"],
         items=[P("plc_emptywagon", -3.4, 0.0, 90), P("plc_fullwagon", 3.6, -0.4, 80), P("plc_campfr", 0, -4.6),
                P("plc_bedrolls", -2.0, -4.4, 340), P("plc_bedrolls", 2.0, -4.6, 200), P("treas_crate", -6.4, 2.6, 30),
                P("plc_box1", 6.6, 2.4, 100), P("plc_barrel", -5.8, -2.6), P("plc_barrel", 6.0, -3.2),
                P("plc_sacks", 0.4, 3.0, 45)]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify resrefs against the TFN checkout")
    args = ap.parse_args()
    for pf in PREFABS:
        PF.save_prefab(pf)
        print("wrote", pf["id"], f"({len(pf['items'])} items)")
    if args.check:
        from tfnstudio import index as IX
        from tfnstudio.project import TfnProject
        proj = TfnProject()
        pal = {e["resref"] for e in IX.placeable_palette(proj, IX.area_index(proj))}
        creatures = set(proj.list_resrefs("utc"))
        wps = set(proj.list_resrefs("utw"))
        bad = []
        for pf in PF.load_prefabs().values():
            for it in pf["items"]:
                if it["kind"] == "placeable" and it["resref"] not in pal:
                    bad.append((pf["id"], it["resref"]))
                elif it["kind"] == "creature" and it["resref"] not in creatures:
                    bad.append((pf["id"], it["resref"]))
                elif it["kind"] == "waypoint" and it["resref"] not in wps:
                    bad.append((pf["id"], it["resref"]))
                elif it["kind"] == "marker" and f"random{it['group']}" not in creatures:
                    bad.append((pf["id"], f"random{it['group']}"))
        if bad:
            print("MISSING in TFN:", bad)
            return 1
        print("all prefab resrefs exist in TFN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
