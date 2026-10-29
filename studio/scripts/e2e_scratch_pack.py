#!/usr/bin/env python3
"""End-to-end check on a SCRATCH COPY of TFN (the real checkout is only read).

  1. copy <TFN>/src, nasher.cfg and nwn-base-scripts to a work dir (~520 MB),
  2. stage + apply the shipped example camp, the example random camp, the example quest, and an "explore" quest through the studio,
  3. run the same `nasher pack` the swamp model `thefrozennorth-build` runs,
  4. unpack the module and confirm the generated resources are inside it (and the journal contains the new quests).

Usage:  python3 scripts/e2e_scratch_pack.py [--tfn PATH] [--work DIR] [--keep] [--skip-pack]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tfnstudio import gffjson as G  # noqa: E402
from tfnstudio.project import DEFAULT_TFN_ROOT  # noqa: E402
from tfnstudio.service import Studio  # noqa: E402

COMPILE_ERROR_PATTERN = re.compile(r"^Error:|Errors encountered during compilation|matching \.ncs files", re.M)
SHIM_SCRIPTS = [Path.home() / "git/extensions/models/nwn-build/bin/gen_include_shims.sh",
                Path.home() / "git/nwn-tools/gen_include_shims.sh"]


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def stage_and_apply(studio: Studio, kind: str, spec: dict) -> dict:
    res = studio.stage_camp(spec) if kind == "camp" else studio.stage_quest(spec)
    errors = [i for i in res.issues if i.level == "error"]
    print(f"   staged {res.change.id}: {len(res.change.changed_files())} files, "
          f"{len(errors)} errors, {sum(1 for i in res.issues if i.level == 'warning')} warnings")
    for e in errors:
        print(f"   ERROR {e.rel}: {e.message}")
    if errors:
        raise SystemExit(f"{kind} change set has validation errors")
    applied = studio.apply_change(res.change.id)
    if not applied["ok"]:
        raise SystemExit(f"apply failed: {applied['problems']}")
    studio.invalidate()
    return {"id": res.change.id, "files": applied["applied"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tfn", default=str(DEFAULT_TFN_ROOT))
    ap.add_argument("--work")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--skip-pack", action="store_true")
    args = ap.parse_args()
    tfn = Path(args.tfn).resolve()
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="tfnstudio-e2e-"))
    work.mkdir(parents=True, exist_ok=True)
    scratch = work / "tfn"
    t0 = time.time()
    try:
        step(f"copying TFN to {scratch}")
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        shutil.copytree(tfn / "src", scratch / "src", symlinks=True)
        shutil.copy2(tfn / "nasher.cfg", scratch / "nasher.cfg")
        shutil.copytree(tfn / "nwn-base-scripts", scratch / "nwn-base-scripts")
        (scratch / "tools").symlink_to(tfn / "tools")

        studio = Studio(scratch, work / "studio", spec_root=ROOT / "specs")
        step("stage + apply example camp")
        camp = studio.load_spec("camps", "example_bandit_camp")
        r1 = stage_and_apply(studio, "camp", camp)

        step("stage + apply example random camp (generated event script + group gate script)")
        r1b = stage_and_apply(studio, "camp", studio.load_spec("camps", "example_random_camp"))

        step("stage + apply example quest (new giver, kill boss with pickup item, rewards)")
        quest = studio.load_spec("quests", "q_example_wolves")
        r2 = stage_and_apply(studio, "quest", quest)

        step("stage + apply an explore quest (generates enter_quest_adv.nss)")
        free_area = next(a for a in studio.areas.values()
                         if not (a.get("hooks") or {}).get("enter_script") and a["resref"] != "mantle"
                         and a.get("width", 0) >= 4 and a.get("has_git"))
        explore = {
            "tag": "q_e2e_scout", "name": "E2E Scout the Area", "giver": {
                "mode": "new", "resref": "e2e_scout_npc", "name": "Scout Elan", "clone_from": "jolie",
                "place": {"area": "mantle", "x": 40.0, "y": 40.0, "facing": 90}},
            "stages": [
                {"n": 1, "via": "talk", "journal": "Scout Elan wants someone to look at " + free_area["name"] + ".",
                 "offer": "Could you scout ahead for me?"},
                {"n": 2, "via": "explore", "journal": "You scouted the area. Report back.", "area": free_area["resref"]},
                {"n": 3, "via": "talk", "journal": "Elan thanks you.", "text": "Excellent report!",
                 "reward": {"xp_tier": 1, "xp_level": 3, "gold": 40}}]}
        r3 = stage_and_apply(studio, "quest", explore)
        all_files = sorted({f for r in (r1, r1b, r2, r3) for f in r["files"]})
        print("   files written into the scratch copy:", *all_files, sep="\n     ")
        if args.skip_pack:
            print("\nskipped nasher pack (--skip-pack)")
            return 0

        step("generating include shims + running nasher pack (a few minutes)")
        shim_script = next((p for p in SHIM_SCRIPTS if p.is_file()), None)
        if shim_script is None:
            raise SystemExit("gen_include_shims.sh not found")
        shims = scratch / ".build" / "include-shims"
        shims.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(shim_script), str(shims), str(scratch / "src" / "nss"), str(scratch / "nwn-base-scripts")],
                       check=True, cwd=scratch, capture_output=True)
        tools = tfn / "tools" / "linux"
        nasher = tools / "nasher" / "nasher"
        flags = f"-oe -i {shims} -i {scratch / 'nwn-base-scripts'} -i {scratch / 'src' / 'nss'}"
        cmd = [str(nasher), "pack", f"--erfUtil:{tools / 'neverwinter' / 'nwn_erf'}", f"--gffUtil:{tools / 'neverwinter' / 'nwn_gff'}",
               f"--tlkUtil:{tools / 'neverwinter' / 'nwn_tlk'}", f"--nssCompiler:{tools / 'nwnsc' / 'nwnsc'}",
               f"--nssFlags:{flags}", "--yes"]
        t1 = time.time()
        proc = subprocess.run(cmd, cwd=scratch, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        out = proc.stdout + proc.stderr
        (work / "nasher.log").write_text(out)
        print(f"   nasher exit {proc.returncode} after {time.time() - t1:.0f}s; log: {work / 'nasher.log'}")
        if proc.returncode != 0 or COMPILE_ERROR_PATTERN.search(out):
            print(out[-3000:])
            raise SystemExit("nasher pack FAILED")
        mod = scratch / ".build" / "modules" / "TFN.mod"
        if not mod.is_file():
            raise SystemExit(f"packed module not found at {mod}")
        print(f"   packed module: {mod} ({mod.stat().st_size / 1e6:.1f} MB)")

        step("listing the packed module and checking generated resources")
        erf = tools / "neverwinter" / "nwn_erf"
        gff = tools / "neverwinter" / "nwn_gff"
        out_dir = work / "unpacked"
        out_dir.mkdir(exist_ok=True)
        listing = subprocess.run([str(erf), "-t", "-f", str(mod)], check=True, capture_output=True, text=True)
        present = {ln.split()[0].lower() for ln in listing.stdout.splitlines() if ln.strip()}
        expect = ["hunter_marek.utc", "hunter_marek.dlg", "alpha_wolf.utc", "q_alphapelt.uti", "e2e_scout_npc.utc",
                  "e2e_scout_npc.dlg", "enter_quest_adv.ncs", "eve_ex_camp.ncs", "spw_ex_camp.ncs", "mantle.git", "module.jrl"]
        missing = [e for e in expect if e not in present]
        for e in expect:
            print(f"   {'ok     ' if e not in missing else 'MISSING'} {e}")
        if missing:
            raise SystemExit(f"missing from packed module: {missing}")
        subprocess.run([str(erf), "-x", "-f", str(mod), "module.jrl"], check=True, capture_output=True, cwd=out_dir)
        jrl_json = subprocess.run([str(gff), "-i", str(out_dir / "module.jrl"), "-l", "gff", "-k", "json"],
                                  check=True, capture_output=True, text=True).stdout
        tags = {G.get(c, "Tag") for c in json.loads(jrl_json)["Categories"]["value"]}
        for tag in ("q_example_wolves", "q_e2e_scout"):
            print(f"   journal contains {tag}: {tag in tags}")
            if tag not in tags:
                raise SystemExit(f"journal tag {tag} missing")
        print(f"\nE2E OK in {time.time() - t0:.0f}s")
        return 0
    finally:
        if not args.keep and not args.work:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"(kept work dir {work})")


if __name__ == "__main__":
    sys.exit(main())
