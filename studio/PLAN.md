# Q-tfn-content-studio — Plan

Local web pages and CLI tools for **extending The Frozen North (TFN)** with new
content: quests, camps, spawn groups, and encounter blueprints. Everything is
emitted as TFN-native nasher source (`src/**/*.json`, `src/nss/*.nss`) after a
staging + review step. Nothing touches the TFN tree until you press *Apply*.

Status/checklist lives in [PROGRESS.md](PROGRESS.md). Keep both current.

---

## 1. Why a new project (and not just Q-nwn-mcp / Q-nwn-manager)

| Existing tool | What it gives | Gap for TFN |
|---|---|---|
| `Q-nwn-mcp` (`mcp__nwn-mcp__*`) | ~150 tools: `place_creature`, `place_placeable`, `place_encounter`, `add_journal_quest`, `create_dialog`, `create_encounter_blueprint`, `verify_quest_completability`, … | Operates on a **packed `.mod`** (`load_module` → edit → `repack_module`), scoped to *non-persistent* modules. TFN's source of truth is `src/` JSON under nasher; a reload silently reverts un-repacked edits. No UI. |
| `Q-nwn-manager` (`nwn-manager`, `nwn-web-editor`) | nasher wrapper, wiki generator, browser editor for **areas** (scripts/lighting/fog/tags), **creature stats**, **.bic** files | No quest page, no spawn/camp page, no placeable stamping. |
| both | generic NWN knowledge | Neither knows TFN's *data-driven* conventions (below). Generic output would not work in-game. |

So: a TFN-aware generator that edits `src/` directly, shows diffs, validates, and
only then applies. The MCP tools remain useful for ad-hoc work on a packed `.mod`.

## 2. TFN conventions the generators must honour (verified in `the-frozen-north`)

### 2.1 Spawns (`SPAWN_SYSTEM.md`, `area_init.nss`, `area_refresh.nss`)
- Spawns are **data**: area local vars + marker objects; `area_init` reads them at module load.
- Area vars live in the **GIT** `VarTable` (`Type` 1=int, 2=float, 3=string):
  `cr` (int, required), `randomN` (string = `.ute` resref), `randomN_spawns` (int),
  `randomN_spawn_script`, `eventN`, `event_chance`, `trapped`, `init/enter/exit/refresh_script`.
- **Markers**: creature instances whose *resref* is `random1`…`random9` (blueprints exist in `src/utc`);
  `area_init` stores their positions and deletes them. More markers = better spread.
- **Hand-placed creatures** (non-immortal, non-`hen_*`): recorded (resref/pos/facing) then deleted,
  respawned at the same spot every refresh. Immortal/`hen_*` persist.
- **Placeables**: only resref prefix `plx_` is recorded+respawned; everything else stays a plain GIT object.
- **`.ute` blueprint** = data container: `CreatureList[{ResRef, CR, Appearance, SingleSpawn}]`
  (SingleSpawn=1 → "unique" pool), `DifficultyIndex` 0..4 → unique chance 5/10/15/20/25 %,
  VarTable `rare` (string resref, 15 % chance per refresh).
- Event spawns: waypoints with resref `_wp_event` + area vars `event1..9`.
- GIT creature instance = UTC blueprint − {`Comment`,`PaletteID`,`__data_type`} + {`XPosition`,`YPosition`,`ZPosition`,`XOrientation`,`YOrientation`}; the **VarTable is copied onto the instance**
  (quest vars are read from the placed instance, not the blueprint).
- Placeable instance struct id 9, creature 4, waypoint 5, door 8, trigger 1, sound 6, store 11, encounter 7.
- Reseed guidance (`SEED_SYSTEM.md` §12): camps/spawn groups/quests need **no reseed**;
  new areas/tile edits/transitions/item blueprints do.

### 2.2 Quests (`inc_quest.nss`, `dlg_q_*`, `src/jrl/module.jrl.json`)
- Journal: one `module.jrl.json`; categories `{Tag, Name, Priority 0-4, Picture 65535, XP 0, Comment, EntryList[{ID, End, Text}]}`.
  Tag prefix `q_` (quest) or `b_` (bounty, resets after 6 h). Entry `ID` == quest **stage**. Tag ≤ 27 chars.
- Stages are advanced by **variables on the quest object** (NPC / creature / item / area):
  `questN = "<NN>_<tag>"` (NN = 2-digit stage), plus optional `questN_prereqM`, `_reward_xp_tier` (1-4: 50/100/200/400 base XP),
  `_reward_xp_level`, `_reward_gold`, `_reward_item`, `_pc_script`, `_self_script`, `_nohighlight`, `_jumpstage`, `_bluff_dc`.
- Eligibility: PC must be at stage `NN-1` (unless `_jumpstage`), prereqs met, not already past.
- Dialog glue = generic scripts with `Key/Value` params: `dlg_q_chk_eli`(target) / `dlg_q_chk_eliN`,
  `dlg_q_adv`(target) / `dlg_q_advN`, `dlg_q_chk_atcN` (currently at), `dlg_q_chk_atp`/`atpN` (at or past),
  `dlg_q_chk_advb` (bluff), `dlg_q_chk_multi` (params `quest`,`stages`).
- **Kill**: target creature `questN` + `quest_kill = N` (+ `boss`), `ScriptDeath = ai_ondeath` (credit via `party_credit.nss`).
- **Pickup**: item with Tag `quest` + var `quest1` (advances on acquire, then destroyed); dropped by a creature's `ItemList`.
- **Explore**: area var `questN` + `enter_script` calling `AdvanceQuest(OBJECT_SELF, oPC, N)`.
- Registration is automatic: `area_init` scans creature **instances** for `questN` and adds `q_*`/`b_*` to the module lists;
  quest NPCs only get highlight if plot/immortal or commoner/defender/merchant faction.

### 2.3 File formats
- nasher JSON from `nwn_gff -p`: 2-space indent, floats printed `%.16g` (fallback `%.17g`), `ensure_ascii=False`.
  Python's default `json.dumps` reproduces ~87 % of files byte-for-byte; the rest differ only in float text
  (`65.20569999999999` vs `65.2057`) → we ship a custom serializer so diffs stay minimal.

## 3. Architecture

Python 3.10, **stdlib only** (no install step), vanilla JS + `<canvas>` front end (no CDN, works offline).

```
Q-tfn-content-studio/
  PLAN.md  PROGRESS.md  README.md  CLAUDE.md
  bin/tfn-studio                 launcher (serve | index | camp | quest | ute | changes | validate)
  tfnstudio/
    gffjson.py                   typed-field helpers + byte-exact JSON writer/reader
    project.py                   TfnProject: paths, indexes (areas, blueprints, palette, scripts), git status
    instances.py                 blueprint -> GIT instance; facing/orientation; Z fallback inference; area bounds
    gamedata.py / walkmesh.py    NWN install access (nwn_resman_extract) + tile walkmesh: exact Z and walkability
    dialogs.py                   DialogBuilder (entries/replies/links/params) + merge into existing .dlg
    camps.py                     CampPlan -> ChangeSet (GIT edits, markers, vars, plx_, waypoints)
    spawns.py                    UTE builder, difficulty math, usage scan
    quests.py                    QuestSpec -> ChangeSet (jrl, utc/utc-instances vars, dlg, uti, nss)
    prefabs.py                   prefab load/save/stamp (rotation, offsets)
    changeset.py                 staging, diff, apply (dirty guard), undo log
    validate.py                  lint rules, nwn_gff round-trip, nwnsc compile
    server.py                    ThreadingHTTPServer: JSON API + static pages; localhost + token + Origin checks
    doctor.py / mdhtml.py        `doctor`/`manual` commands; Markdown->HTML for MANUAL.html (served at /manual)
    web/                         index, camps, spawns, quests, changes (+ static/app.css, common.js, …)
  prefabs/*.json                 camp templates (bandit camp, hunter camp, undead graveyard, …)
  specs/camps|quests/*.json      saved plans (declarative, re-appliable, idempotent)
  tests/                         unittest suite (uses a temp copy of TFN files; skips if TFN absent)
  .studio/                       staging + undo logs (gitignored)
```

### 3.1 Pages
| Page | Purpose |
|---|---|
| **Dashboard** `/` | TFN path, git branch/dirty state, content counts, staged change sets, validation status, links. |
| **Camp Builder** `/camps` | Pick an area → tile-grid canvas with existing objects; stamp prefabs, place creatures/placeables/markers/waypoints; configure `randomN` groups + `cr`; live preview; stage. |
| **Spawn Designer** `/spawns` | Author `.ute` encounter blueprints (commons/uniques/rare/difficulty), see usage across areas, CR sanity checks. |
| **Quest Builder** `/quests` | Wizard: tag/name/kind → stages (talk/kill/pickup/explore/turn-in) → rewards → dialog text; previews journal, vars, dialog tree; stage. |
| **Changes** `/changes` | Staged change sets: file list, unified diffs, validation results, Apply / Discard / Undo. |

### 3.2 Safety rules (non-negotiable)
1. Generators only write to the **staging area**; Apply copies into `<TFN>/src/**` after a dirty-file guard (`git status --porcelain` on target paths; refuse unless forced) and logs an undo record.
2. Server binds `127.0.0.1`, checks `Host`/`Origin`, and requires a per-run token header on every POST.
3. All resrefs validated `^[a-z0-9_]{1,16}$`; tags ≤ 32 chars; paths never built from raw user input; writes confined to `src/<ext>/`.
4. Re-applying a plan is **idempotent**: generated instances carry a `studio_plan` local var; re-apply replaces them.
5. No commits/pushes from tooling. The TFN working tree is the user's; we never run its build unless asked
   (the build is the swamp model `thefrozennorth-build`, method `build`).

### 3.3 Validation layers
1. Exact-format JSON (idempotent re-serialization).
2. Structure lint (required fields/types per object kind).
3. Cross-reference lint (resrefs exist, dialog graph integrity, quest tag/stage rules, `randomN` ute + marker blueprint exist, `cr` present, bounds).
4. `nwn_gff` JSON→GFF→JSON round trip (proves the toolset/engine can load it).
5. `nwnsc` compile for any generated `.nss`.

## 4. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold, plan, progress tracker | this file + PROGRESS.md exist |
| M1 | Core: `gffjson` (byte-exact on ≥ 99.9 % of TFN JSON), `project` index, `changeset`, `validate` | round-trip test over all of `src/` passes |
| M2 | Camps/spawns: instances, camp plans, UTE builder, prefab stamping, CLI | tests green; generated GIT passes `nwn_gff` round trip |
| M3 | Quests: journal, vars, dialog builder (new + merge), kill/pickup/explore/turn-in | generated dlg graph valid; scripts compile |
| M4 | Web server + all pages | API tests + manual browser smoke |
| M5 | Walkmesh heights/walkability, mined base-game creatures/props, prefab save + open-ground finder | calibration test + UI checks |
| M6 | Docs, polish, e2e on a scratch copy of TFN (nasher pack) | README + `scripts/e2e_scratch_pack.py` (passed) |

## 4b. Random camp events (M9, requested 2026-10-03; implemented 2026-10-03)

User question: "Can I have a camp and some creatures randomly spawn in place of another encounter?"  Verified in TFN
(`area_refresh.nss`, `inc_event.nss`, `inc_area.nss`, `SPAWN_SYSTEM.md` section 4):

* Creatures instead of the usual creatures already exists: each spawn marker picks its type from the `.ute` (common pool, or the
  unique pool with the difficulty's 5-25 %), plus a 15 %/refresh rare. Spawn Designer covers it.
* A camp (props) cannot live in a `.ute`; Camp Builder camps are permanent (props = `plx_` respawn, creatures recorded and
  respawned every refresh). Randomness comes from the **event system**: `_wp_event` waypoints + area vars `eventN` (script
  names) + `event_chance` (default 50, 0 is impossible). Per refresh: one roll, then ONE random `eventN` script runs with ONE
  random event waypoint as OBJECT_SELF. Events are *additive*: `area_refresh` runs the event first and still spawns every group.
* "Instead of" needs a hook: `randomN_spawn_script` runs on each creature of group N right after it spawns (delayed 0.3 s x n).

User's idea (refined 2026-10-03): *a spawn of placeables + creatures created randomly when an area refreshes, at one of several
location markers placed by hand in each area, so the placement and the direction of the arrangement are right.*

**Feature:** a camp plan gets an optional `camp_event` block. The plan's creatures and placeables then form a **template**: they are
NOT written to the GIT but compiled into a generated event script. Candidate **spots** (position + direction, placed by hand in the
Camp Builder, imported from the area's `_wp_event` waypoints, or suggested from open ground) say where the template may appear; each
spot rotates the template about its pivot by `spot.facing - origin.facing` and moves the pivot to the spot. Every variant is computed
at stage time, so the studio checks **each spot** against the walkmesh (exact Z, walkability, bounds) and previews it on the map.

```
"camp_event": {"script": "eve_wolf_den",            # optional, <=16 chars, default eve_<id>
               "weight": 1,                         # 1-4 eventN slots (more slots = more likely among the area's events)
               "origin": {"x": 70, "y": 45, "facing": 90},   # template pivot + front direction; default: centroid, 90
               "spots": [{"x": 12, "y": 80, "facing": 0}, ...],   # <=24 candidates; none = the design location only
               "include_origin": false,             # also allow the design location when spots exist
               "replaces_group": 2,                 # optional: the camp REPLACES spawn group N when it appears
               "replace_radius": 0}                 # m from the chosen spot; 0 = the whole group
```
The chance is the area's `event_chance` (plan field `event_chance`: one source of truth). The UI shows the effective % per
refresh = event_chance x our slots / all slots. One uniformly random variant is built per event.

Generated files (staged like everything else): `src/nss/<script>.nss` (one function per spot + a `switch (Random(n))`), optionally
`src/nss/spw_<..>.nss` (the gate), the area GIT (`eventN` slots, `event_chance`, `randomN_spawn_script`, an auto `_wp_event`
waypoint when the area has none: events cannot fire without one).

Design decisions (assumed, no questions asked):
1. **Compile-time variants** (absolute coordinates per spot), not runtime-relative: the studio is the single source of truth, every
   spot is validated and previewed, no runtime ground-height or rotation maths. Moving a marker means editing the plan and staging again.
2. Marker/waypoint objects of the plan stay permanent GIT objects; only creatures and placeables become the template.
3. An explicit `z` on a plan object means "height above the ground at the design position" for variants (items on tables keep their offset).
4. A tagged marker waypoint (`ce_<id>`, blueprint `nw_waypoint001`) is created first at the chosen spot: "the camp is standing" =
   that tag exists, and it dies with the area cleanup, so no flag ever needs resetting. The gate, the radius test and the script's own
   re-entry guard use it.
5. The gate chains to an existing group spawn script (header comment `// tfn-studio chains: <script>`), restores it when the plan no
   longer replaces the group, and refuses to wrap another plan's gate.
6. Generated scripts carry a header (`// tfn-studio camp event|gate: plan <id>`); only scripts with the same plan id are overwritten,
   so TFN's own scripts (e.g. `eve_bears`) can never be clobbered. Stale `eventN` / gate wiring of a plan that left event mode is removed.
7. Runtime parity with `area_init`: the generated script finishes every prop with a `CampFinishProp` helper that repeats `area_init`'s
   chain at runtime (so it follows the blueprint as it is when the game runs, no stage-time guess): `plx_*` props are left as they are,
   trapped props / props whose use-script does not exist / props with an inventory become static decor + plot, `treas_*` props get
   `ExecuteScript("treas_init")`. Creatures whose blueprint carries `quest1` are put on the area's `quest_npcs` list like the static
   creatures `area_refresh` creates.
8. The replaced group's creatures exist for up to a few seconds before the gate removes them (spawn scripts run delayed): keep the
   camp away from where players enter. A core-script tweak (`area_refresh` honouring a suppress flag) would remove that window; not
   done because the studio never edits core scripts.
9. Several camp plans in one area are fine (each has its own event slot); a shared "camp library" with common spots is a later idea.

As built (what implementation changed or added to the design above; all verified against the TFN scripts and by tests):

10. **Event slots must stay contiguous.** `area_init` counts `events` from `event1` up to the *first empty slot*, so a gap hides every
    later event. The studio therefore manages the whole run (`plan_event_run`/`write_event_run`): it appends the camp's slots, closes gaps
    when slots are released, warns when an old orphan slot becomes reachable, and `validate.lint_git` warns about gaps and about events without
    a `_wp_event` waypoint in any area. Duplicate script names are TFN's own weighting device (`mantle` lists `eve_adventure` twice), so
    `weight` simply means "this many slots".
11. **Spot suggestions** place the camp's *actual objects* at each candidate pivot and each of 8 directions (45 degree steps, preferring
    the direction towards the area centre): every object must stand on walkable ground, creatures also need walkable neighbours, and nothing
    may crowd an existing object. (A first version demanded a free square window around the footprint; the real `bandit_cave` has no
    15 m square, so it found nothing.) Deterministic per seed; spots already placed are avoided.
12. Without walkmesh data every object of a camp takes **the spot's own ground height** (a per-object guess would scatter one camp over
    several heights); an explicit `z` stays "height above that ground". The staging card says how many spots are guesses.
13. `camp_event.origin` defaults to the centre of the camp's objects with facing 90; the design location itself is built only when there are
    no spots or `include_origin` is set.
14. Live preview (`POST /api/camps/event-info`) runs the same pipeline as staging on a scratch copy and returns every spot's objects, issues,
    the chance and the wiring; `POST /api/camps/suggest-spots` and the CLI (`camp stamp --random-camp`, `camp spots`) share it.
15. Not verified in a running NWN server: correctness rests on reading `area_refresh`/`area_init`/`inc_area`, `nwnsc` compiling both generated
    scripts, `nasher pack` including them in `TFN.mod` (e2e), and unit/browser tests. First in-game test: stage with `event_chance` 100 and 4 slots.

## 5. Assumptions (made without asking, per instructions)
- Tool name/location: `~/git/Q-tfn-content-studio` (matches the `Q-` naming of sibling repos).
- Python stdlib only; Linux paths for tools auto-detected from `../nwn-tools/linux/…`; overridable by flags/env.
- Z for new objects comes from the tile **walkmesh** (calibrated: 99 % of existing TFN objects within 0.35 m); only without the NWN install does it fall back to the nearest existing object, flagged "approximate".
- Base-game creatures/props are not extracted from the game: TFN-used ones are mined from real instances (measured: 0/486 `.ute` entries use base creatures).
- New NPCs are **clones** of an existing blueprint (appearance/gear picked from the palette), not synthesized from scratch.
- Quests need **no new scripts** except the generic area-enter helper for "explore" stages.
