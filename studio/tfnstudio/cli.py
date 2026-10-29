"""tfn-studio command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import prefabs as PF
from . import quests as QS
from .doctor import run_doctor, run_manual
from .project import ProjectError
from .service import SPEC_ROOT, Studio, StageResult

C = {"red": "\033[31m", "yellow": "\033[33m", "green": "\033[32m", "dim": "\033[2m", "off": "\033[0m"}


def _c(color: str, text: str) -> str:
    return f"{C[color]}{text}{C['off']}" if sys.stdout.isatty() else text


def _spec_file(kind: str, arg: str, st: "Studio | None" = None) -> Path:
    p = Path(arg)
    if p.suffix == ".json" or "/" in arg:
        return p
    root = st.spec_root if st is not None else SPEC_ROOT        # a module's own plans live in that module
    return root / kind / f"{arg}.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectError(f"cannot read {path}: {exc}")
    except ValueError as exc:
        raise ProjectError(f"{path} is not valid JSON: {exc}")


def print_stage(res: StageResult, as_json: bool) -> int:
    if as_json:
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.ok else 1
    cs = res.change
    print(f"change set {_c('green', cs.id)}  ({cs.kind}: {cs.title})")
    for f in cs.summary()["files"]:
        mark = "+" if f["action"] == "create" else "~"
        print(f"  {mark} {f['rel']}  (+{f['added']} -{f['removed']})  {_c('dim', f['note'])}")
    for n in cs.notes:
        print(f"  note: {n}")
    errors = [i for i in res.issues if i.level == "error"]
    warns = [i for i in res.issues if i.level == "warning"]
    for i in errors:
        print(_c("red", f"  ERROR   {i.rel}: {i.message}"))
    for i in warns:
        print(_c("yellow", f"  warning {i.rel}: {i.message}"))
    for i in res.issues:
        if i.level == "info":
            print(_c("dim", f"  info    {i.rel}: {i.message}"))
    print(f"{len(errors)} error(s), {len(warns)} warning(s)")
    print(f"next: tfn-studio changes show {cs.id} --diff   |   tfn-studio changes apply {cs.id}")
    return 0 if res.ok else 1


# ---------------------------------------------------------------------------
# command handlers
# ---------------------------------------------------------------------------

def cmd_index(st: Studio, a) -> int:
    def prog(what, i, n):
        if sys.stderr.isatty() and i % 50 == 0:
            print(f"\r{what} {i}/{n}   ", end="", file=sys.stderr)
    st.refresh(prog)
    print(json.dumps({"areas": len(st.areas), "creatures": len(st.creatures), "items": len(st.items),
                      "utes": len(st.utes), "placeables_in_palette": len(st.palette())}))
    return 0


def cmd_status(st: Studio, a) -> int:
    print(json.dumps(st.status(), indent=2))
    return 0


def cmd_areas(st: Studio, a) -> int:
    rows = [r for r in st.areas.values()
            if not a.filter or a.filter.lower() in (r["resref"] + " " + r.get("name", "")).lower()]
    if a.json:
        print(json.dumps(rows, indent=1))
        return 0
    for r in sorted(rows, key=lambda r: r["resref"]):
        groups = ",".join(f"r{g['n']}:{g['ute']}x{g['spawns']}" for g in r.get("groups", []))
        print(f"{r['resref']:24s} {r.get('width', 0):>2}x{r.get('height', 0):<2} cr={str(r.get('cr')):>4}  "
              f"{r.get('name', '')[:34]:34s} {groups}")
    return 0


def cmd_area(st: Studio, a) -> int:
    d = st.area_detail(a.resref)
    d.pop("tiles", None)
    if not a.objects:
        d.pop("objects", None)
    print(json.dumps(d, indent=1))
    return 0


def cmd_prefabs(st: Studio, a) -> int:
    for pf in st.prefabs().values():
        print(f"{pf['id']:18s} r={pf['radius']:>5}  {len(pf['items']):>2} items  {pf['name']} - {pf['description'][:70]}")
    return 0


def cmd_camp_stage(st: Studio, a) -> int:
    plan = _read_json(_spec_file("camps", a.spec, st))
    return print_stage(st.stage_camp(plan, validate=not a.no_validate), a.json)


def cmd_camp_stamp(st: Studio, a) -> int:
    path = _spec_file("camps", a.plan, st)
    if path.is_file():
        plan = _read_json(path)
    else:
        if not a.area:
            raise ProjectError("new plan: pass --area")
        plan = {"id": path.stem, "title": a.title or path.stem, "area": a.area, "objects": [], "groups": []}
    prefab = st.prefabs().get(a.prefab)
    if not prefab:
        raise ProjectError(f"unknown prefab {a.prefab!r} (see: tfn-studio prefabs)")
    gmap = {}
    for pair in (a.group_map or "").split(","):
        if pair:
            k, v = pair.split("=")
            gmap[int(k)] = int(v)
    objs = PF.stamp(prefab, a.x, a.y, a.rotation, gmap)
    plan["objects"].extend(objs)
    if a.cr is not None:
        plan["cr"] = a.cr
    if a.random_camp:
        _make_random_camp(plan, a)
    elif a.spot or a.replaces_group:
        raise ProjectError("--spot, --include-here, --replaces-group and friends only make sense with --random-camp")
    if a.event_chance is not None:
        plan["event_chance"] = a.event_chance
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    groups = sorted({o["group"] for o in objs if o["kind"] == "marker"})
    print(f"stamped {a.prefab} ({len(objs)} objects) into {path}")
    if a.random_camp:
        ce = plan["camp_event"]
        print(f"random camp: {len(ce.get('spots') or [])} spot(s) + {'the stamp position' if ce.get('include_origin') else 'no design location'}; "
              f"stage it to see the chance and the wiring ({'tfn-studio camp stage ' + path.stem})")
    missing = [g for g in groups if g not in {x['n'] for x in plan.get('groups', [])}]
    if missing:
        print(f"note: markers use spawn group(s) {missing}; add a `groups` entry (ute, spawns) to the plan")
    return 0


def _parse_spot(text: str) -> dict:
    """`X,Y` or `X,Y,FACING` (degrees, 0 = east, 90 = north)."""
    parts = [p.strip() for p in text.split(",")]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        vals = []
    if len(vals) not in (2, 3):
        raise ProjectError(f"--spot {text!r}: use X,Y or X,Y,FACING (numbers)")
    return {"x": vals[0], "y": vals[1], "facing": vals[2] % 360 if len(vals) == 3 else 90.0}


def _make_random_camp(plan: dict, a) -> None:
    """Turn the plan's props and creatures into a random camp event built around the stamp position."""
    ce = plan.get("camp_event") if isinstance(plan.get("camp_event"), dict) else {}
    ce.setdefault("origin", {"x": a.x, "y": a.y, "facing": (90.0 + a.rotation) % 360})
    ce.setdefault("spots", [])
    ce["spots"].extend(_parse_spot(t) for t in a.spot)
    if a.include_here:
        ce["include_origin"] = True
    if a.weight is not None:
        ce["weight"] = a.weight
    if a.replaces_group is not None:
        ce["replaces_group"] = a.replaces_group
    if a.replace_radius is not None:
        ce["replace_radius"] = a.replace_radius
    if a.script:
        ce["script"] = a.script
    plan["camp_event"] = ce


def cmd_camp_spots(st: Studio, a) -> int:
    path = _spec_file("camps", a.plan, st)
    plan = _read_json(path)
    res = st.suggest_camp_spots(plan, a.count, a.seed or "")
    if not res["spots"]:
        print("no suitable open ground found for this camp (it needs a walkable footprint of "
              f"about {res['footprint'] * 2:.0f} m across, clear of other objects)")
        return 1
    for i, sp in enumerate(res["spots"], 1):
        print(f"  {i}: --spot {sp['x']:g},{sp['y']:g},{sp['facing']:g}")
    if a.add:
        ce = plan.setdefault("camp_event", {})
        ce.setdefault("spots", []).extend(res["spots"])
        path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"added {len(res['spots'])} spot(s) to {path}")
    return 0


def cmd_ute_stage(st: Studio, a) -> int:
    return print_stage(st.stage_ute(_read_json(_spec_file("utes", a.spec, st)), validate=not a.no_validate), a.json)


def cmd_quest_stage(st: Studio, a) -> int:
    spec = _read_json(_spec_file("quests", a.spec, st))
    return print_stage(st.stage_quest(spec, validate=not a.no_validate), a.json)


def cmd_setup(st: Studio, a) -> int:
    """Install the studio's quest runtime into a module that has none (generic profile)."""
    info = st.runtime_status()
    print(f"module profile: {info['profile']}   layout: {info['layout']}")
    if info["profile"] != "generic":
        print("This module ships its own quest scripts; nothing to install.")
        return 0
    if a.check:
        print("runtime installed" if info["installed"] else f"missing: {', '.join(info['missing']) or '-'}")
        if info["foreign"]:
            print(f"module scripts with the studio's names (will not be touched): {', '.join(info['foreign'])}")
        return 0
    return print_stage(st.stage_runtime(validate=not a.no_validate), a.json)


def cmd_quest_describe(st: Studio, a) -> int:
    for row in QS.describe(_read_json(_spec_file("quests", a.spec, st))):
        reward = f"  reward={row['reward']}" if row["reward"] else ""
        print(f"stage {row['stage']}{' (END)' if row['end'] else ''}: {row['how']}{reward}\n    {row['journal'][:100]}")
    return 0


def cmd_quest_convert(st: Studio, a) -> int:
    """Older quest dialogs (dlg_q_adv3 ...) -> parameterized (dlg_q_adv + target=3).  --check writes nothing."""
    only = a.dialog or None
    if a.check:
        rep = st.convert_quests_check(only)
        if a.json:
            print(json.dumps(rep, indent=2))
            return 0
        for fam, v in rep["scripts"].items():
            state = "ok" if v["ok"] else "NOT VERIFIED - left alone"
            print(f"  {fam}1..9: {state}" + (f"  (differs: {v['bad']})" if v["bad"] else "") + (f"  {v['why']}" if v["why"] else ""))
        for d in rep["dialogs"]:
            extra = []
            if d["skipped_with_params"]:
                extra.append(f"left alone (already has params): {', '.join(d['skipped_with_params'])}")
            if d["skipped_unverified_family"]:
                extra.append(f"left alone (script not verified): {', '.join(d['skipped_unverified_family'])}")
            if d["refused"]:
                extra.append(f"REFUSED: {d['refused']}")
            if d["converted"] or extra:
                print(f"  {d['dialog']}: {d['converted']} call(s) to convert" + (f"  [{'; '.join(extra)}]" if extra else ""))
        print(f"{rep['calls_converted']} call(s) in {rep['dialogs_changed']} dialog(s) would be converted. Nothing was written.")
        print("next: tfn-studio quest convert   (stages a change set you can review, apply and undo)")
        return 0
    return print_stage(st.stage_convert_quests(only, validate=not a.no_validate), a.json)


def cmd_changes(st: Studio, a) -> int:
    act = a.action
    if act == "list":
        for c in st.status()["changes"]:
            flag = "applied" if c["applied"] else "staged "
            print(f"{c['id']:44s} {flag} {c['kind']:6s} {c['files']:>2} files  {c['title']}")
        return 0
    cid = a.id
    if not cid:
        raise ProjectError("this action needs a change id")
    if act == "show":
        cs = st.load_change(cid)
        print(json.dumps(cs.summary(), indent=1))
        if a.diff:
            print(cs.diff())
        return 0
    if act == "validate":
        issues = st.validate_change(cid)
        for i in issues:
            print(f"{i.level:8s} {i.rel}: {i.message}")
        return 1 if any(i.level == "error" for i in issues) else 0
    if act == "apply":
        res = st.apply_change(cid, allow_dirty=a.allow_dirty, force=a.force)
        print(json.dumps({k: res[k] for k in ("ok", "problems", "applied")}, indent=1))
        return 0 if res["ok"] else 1
    if act == "undo":
        res = st.undo_change(cid, force=a.force)
        print(json.dumps(res, indent=1))
        return 0 if res["ok"] else 1
    if act == "discard":
        print("discarded" if st.discard_change(cid) else "not found")
        return 0
    return 2


def cmd_serve(st: Studio, a) -> int:
    from .server import serve
    serve(st, a.host, a.port, open_browser=a.open)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tfn-studio", description="Extend The Frozen North: quests, camps, spawns.",
        epilog="--tfn PATH may be written before or after the command. First time? Run:  tfn-studio doctor")
    ap.add_argument("--tfn", "--module", dest="tfn", metavar="PATH",
                    help="module project (default: $MODULE_ROOT / $TFN_ROOT, else the nwn-manager project you are in, "
                         "else ~/git/the-frozen-north)")
    ap.add_argument("--json", action="store_true", help="machine-readable output where supported")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="check Python, the TFN checkout, tools and the NWN install (works without a checkout)")
    p.add_argument("--port", type=int, default=8350, help="port to test for `serve` (default 8350)")
    p.set_defaults(fn=None)
    p = sub.add_parser("manual", help="print where MANUAL.html is (readable in any browser, needs no setup); --open shows it")
    p.add_argument("--open", action="store_true", help="open it in the default browser")
    p.set_defaults(fn=None)
    p = sub.add_parser("setup", help="install the studio's quest runtime into a module that has none (stages a change set)")
    p.add_argument("--check", action="store_true", help="only say what is installed")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(fn=cmd_setup)
    sub.add_parser("index", help="build/refresh the content indexes").set_defaults(fn=cmd_index)
    sub.add_parser("status", help="TFN checkout, tools, staged changes").set_defaults(fn=cmd_status)

    p = sub.add_parser("areas", help="list areas")
    p.add_argument("--filter")
    p.set_defaults(fn=cmd_areas)
    p = sub.add_parser("area", help="area details")
    p.add_argument("resref")
    p.add_argument("--objects", action="store_true", help="include every placed object")
    p.set_defaults(fn=cmd_area)
    sub.add_parser("prefabs", help="list camp prefabs").set_defaults(fn=cmd_prefabs)

    camp = sub.add_parser("camp", help="camp plans").add_subparsers(dest="sub", required=True)
    p = camp.add_parser("stage", help="generate a change set from a camp plan")
    p.add_argument("spec", help="plan name (specs/camps/NAME.json) or path")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(fn=cmd_camp_stage)
    p = camp.add_parser("stamp", help="stamp a prefab into a (new) plan file")
    p.add_argument("plan")
    p.add_argument("prefab")
    p.add_argument("--area")
    p.add_argument("--title")
    p.add_argument("--x", type=float, required=True)
    p.add_argument("--y", type=float, required=True)
    p.add_argument("--rotation", type=float, default=0.0)
    p.add_argument("--group-map", help="remap marker groups, e.g. 1=2,3=4")
    p.add_argument("--cr", type=int)
    p.add_argument("--random-camp", action="store_true",
                   help="make the plan's props and creatures a random camp: it appears at one of the --spot places when the area refreshes")
    p.add_argument("--spot", action="append", default=[], metavar="X,Y[,FACING]",
                   help="a place the random camp may appear (repeatable; FACING in degrees, 0 = east, 90 = north)")
    p.add_argument("--include-here", action="store_true", help="the stamp position is one of the places too")
    p.add_argument("--weight", type=int, help="event slots the camp takes (1-4): more slots = appears more often")
    p.add_argument("--replaces-group", type=int, metavar="N", help="while the camp stands, spawn group randomN is removed")
    p.add_argument("--replace-radius", type=float, metavar="M", help="only remove group creatures within M metres of the camp (default: all)")
    p.add_argument("--event-chance", type=int, metavar="PCT", help="the area's event_chance (chance that a refresh has an event at all)")
    p.add_argument("--script", help="name of the generated event script (default: eve_<plan id>)")
    p.set_defaults(fn=cmd_camp_stamp)
    p = camp.add_parser("spots", help="suggest open spots for a plan's random camp (needs the NWN game data)")
    p.add_argument("plan", help="plan name (specs/camps/NAME.json) or path")
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--seed", help="a different seed gives different spots")
    p.add_argument("--add", action="store_true", help="append the spots to the plan file")
    p.set_defaults(fn=cmd_camp_spots)

    ute = sub.add_parser("ute", help="encounter blueprints").add_subparsers(dest="sub", required=True)
    p = ute.add_parser("stage")
    p.add_argument("spec")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(fn=cmd_ute_stage)

    quest = sub.add_parser("quest", help="quests").add_subparsers(dest="sub", required=True)
    p = quest.add_parser("stage", help="generate a change set from a quest spec")
    p.add_argument("spec", help="quest tag (specs/quests/TAG.json) or path")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(fn=cmd_quest_stage)
    p = quest.add_parser("describe", help="print the stage -> mechanism plan")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_quest_describe)
    p = quest.add_parser("convert", help="convert older quest dialogs to parameters (stages a change set; --check = dry run)")
    p.add_argument("--dialog", action="append", metavar="RESREF", help="only this dialog (repeatable)")
    p.add_argument("--check", action="store_true", help="report what would change; write nothing")
    p.add_argument("--no-validate", action="store_true")
    p.set_defaults(fn=cmd_quest_convert)

    p = sub.add_parser("changes", help="list / show / validate / apply / undo / discard change sets")
    p.add_argument("action", choices=["list", "show", "validate", "apply", "undo", "discard"])
    p.add_argument("id", nargs="?")
    p.add_argument("--diff", action="store_true")
    p.add_argument("--allow-dirty", action="store_true", help="apply even if target files have uncommitted git changes")
    p.add_argument("--force", action="store_true", help="apply despite validation errors / conflicts (or force undo)")
    p.set_defaults(fn=cmd_changes)

    p = sub.add_parser("serve", help="start the local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8350)
    p.add_argument("--open", action="store_true", help="open a browser tab")
    p.set_defaults(fn=cmd_serve)
    return ap


def extract_tfn(argv: list[str]) -> tuple[list[str], str | None]:
    """Pull `--tfn PATH` / `--tfn=PATH` out of argv wherever it is, so it works before or after the command."""
    out: list[str] = []
    tfn: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--tfn", "--module") and i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            tfn = argv[i + 1]
            i += 2
            continue
        if arg.startswith(("--tfn=", "--module=")) and len(arg.split("=", 1)[1]) > 0:
            tfn = arg.split("=", 1)[1]
            i += 1
            continue
        out.append(arg)
        i += 1
    return out, tfn


def main(argv: list[str] | None = None) -> int:
    argv, tfn = extract_tfn(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(argv)
    tfn = tfn or args.tfn
    try:
        if args.cmd == "doctor":
            return run_doctor(tfn, port=args.port)
        if args.cmd == "manual":
            return run_manual(open_browser=args.open)
        studio = Studio(tfn)
        return args.fn(studio, args)
    except ProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
