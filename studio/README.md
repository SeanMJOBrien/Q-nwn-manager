# TFN Content Studio

Local web pages and CLI tools for **extending The Frozen North** with new content: quests, camps (permanent, or **random camps that
appear only sometimes at one of several spots**), spawn groups and encounter blueprints. You design on a map or in a form, the studio generates TFN-native nasher source
(`src/**/*.json`, `.nss`), shows the exact diff, validates it, and only then writes it into the TFN tree.

* Python 3.9+ (macOS's stock `python3` works), **standard library only** — nothing to install. Front end is vanilla JS + `<canvas>`, works offline.
* Reads and writes the **nasher source tree** of `~/git/the-frozen-north` (override with `--tfn` or `$TFN_ROOT`).
* Nothing touches TFN until you press **Apply**; every apply has an **Undo**.

```
bin/tfn-studio doctor           # first time: checks Python, the TFN checkout, tools, NWN install, port
bin/tfn-studio serve            # then open http://127.0.0.1:8350/   (add --open to launch the browser)
bin/tfn-studio --tfn ~/path/to/the-frozen-north serve   # TFN somewhere else (or export TFN_ROOT=...)
bin/tfn-studio --help
```

**New here? Read the manual — it needs nothing installed:** open [`MANUAL.html`](MANUAL.html) in any browser (one self-contained file:
installation on macOS/Linux/Windows, startup, every page step by step, command-line reference, troubleshooting). The running studio serves
the same page at `/manual` (the **Manual ↗** link in every page's top bar jumps to the section for that page), and
`bin/tfn-studio manual [--open]` prints / opens its location. The source is [`MANUAL.md`](MANUAL.md); after editing it run
`python3 scripts/build_manual.py` to regenerate the HTML (a test fails when the two disagree).

## Why this exists (vs. Q-nwn-mcp / Q-nwn-manager)

| Tool | Good for | Gap for TFN |
|---|---|---|
| `Q-nwn-mcp` (`mcp__nwn-mcp__*`) | ~150 MCP tools: `place_creature`, `place_placeable`, `add_journal_quest`, `create_dialog`, … | Works on a packed `.mod` (load → edit → repack) and targets *non-persistent* modules. TFN's truth is `src/` JSON. |
| `Q-nwn-manager` (`nwn-manager`, web editor) | nasher wrapper, wiki, browser editor for area scripts/lighting, creature stats, `.bic` | No quest, camp or spawn pages. |
| **this project** | TFN's *data-driven* spawn system and *variable-driven* quest system | — |

TFN rarely uses hand-placed live monsters: spawns are **data** (area variables + marker creatures) that `area_init`
turns into creatures every refresh, and quests are **variables** read by `inc_quest.nss`. Generic tools don't know
those conventions; this one generates exactly what the module's scripts expect.

## The pages

| Page | What you do |
|---|---|
| **Dashboard** | Checkout/branch/dirty state, tools found, index status, staged change sets. |
| **Camp Builder** `/camps` | Pick an area; stamp one of 10 prefabs (bandit/goblin/hunter camps, spider nest, graveyard, ambush…) or place props, creatures, spawn markers and event waypoints on a pan/zoom map with a walkability overlay, **Find open ground** for a prefab's footprint, and **Save as prefab…** for your own layouts; assign `random1…9` spawn groups, area `cr` and event scripts; make the camp a **random camp** (built only now and then, at one of several spots with their own direction); stage. |
| **Spawn Designer** `/spawns` | Author `.ute` encounter blueprints (common/unique pools, difficulty, rare); live expected-mix preview, CR advice, "used by" list. |
| **Quest Builder** `/quests` | Giver (new clone or existing NPC), stages by *talk / kill / pickup / explore*, rewards, dialog text; live mechanism plan; browse how the 90 existing quests are wired. |
| **Changes** `/changes` | Review staged change sets: files, unified diffs, validation (JSON round trip through `nwn_gff`, lints, script compile), Apply / Undo / Discard. |

Typical flow: **build → Stage → review on Changes → Apply → build the module → restart the server.**
Build with the swamp model (from `~/git`, not inside the TFN repo):
`swamp model method run thefrozennorth-build build`. Camps, spawn groups and quests need **no reseed**
(`SEED_SYSTEM.md` §12); new areas/tiles/transitions/item blueprints do.

## What gets generated

**Camps / spawns** (`SPAWN_SYSTEM.md`)

* props → `Placeable List` instances (from `src/utp`, or the most common real instance mined from TFN's GITs);
* creatures → `Creature List` instances (blueprint + position; the blueprint's VarTable is copied, as the toolset does);
* spawn markers → creatures with resref `random1…9`; area vars `randomN`, `randomN_spawns`, `randomN_spawn_script`, `cr`;
* event waypoints (`_wp_event`) + `eventN` / `event_chance`;
* new encounters → `src/ute/<resref>.ute.json`.

**Random camps** (`camp_event` in a plan; Camp Builder → *Random camp*): the plan's props and creatures are not stored in the area. They become the template of a generated
event script `src/nss/eve_<id>.nss` that builds the camp, when the area refreshes and the `event_chance` roll picks it, at one randomly chosen **spot** (position + direction; the camp is
rotated about its pivot and re-grounded on the walkmesh per spot, and every spot is checked and previewed when you stage). The studio wires the area's `eventN` slots (kept contiguous, as
`area_init` requires), adds a `_wp_event` waypoint if the area has none, and can **replace a spawn group** while the camp stands (`src/nss/spw_<id>.nss` on `randomN_spawn_script`, chaining to the group's own script).
Spots can be clicked in, suggested on open ground, or imported from waypoints placed in the toolset. Only scripts carrying the studio's header comment are ever overwritten.

Every generated instance carries the local variable `studio_plan = <plan id>`, so re-staging a plan **replaces** its
previous output instead of duplicating it.

**Quests** (`inc_quest.nss`)

* journal category appended to `src/jrl/module.jrl.json` (Comment marker `tfn-content-studio`);
* quest-giver blueprint (cloned, `Plot=1`) + dialog using TFN's generic `dlg_q_chk_eli` / `dlg_q_adv` / `dlg_q_chk_atcN` scripts — or the quest nodes **merged into an existing NPC's dialog** (removable, idempotent);
* stage wiring by variable: `questK = "NN_<tag>"` + `questK_reward_*` on the NPC (blueprint **and every placed instance**, because instances snapshot the blueprint's variables), `quest_kill` on kill targets, a `quest`-tagged item for pickups (dropped by a creature's `ItemList`), `questK` + `enter_script = enter_quest_adv` on explore areas (the tiny generic script is generated for you);
* optional placement of the NPC / boss in an area.

## Command line

```
bin/tfn-studio doctor | manual [--open]      # environment check / where the browser-readable manual is (both work without a TFN checkout)
bin/tfn-studio status | index | areas [--filter wood] | area mantle --objects | prefabs
bin/tfn-studio camp stamp my_camp bandit_camp --area mantle --x 70 --y 70 --rotation 30 --cr 4 --group-map 1=4
bin/tfn-studio camp stamp wolves hunter_camp --area mantle --x 70 --y 70 --random-camp --spot 14.5,75.5,90 --spot 134.5,64.5,270   # appears at one of the spots
bin/tfn-studio camp spots wolves --count 3 --add     # suggest open ground for more spots (needs the NWN install)
bin/tfn-studio camp stage my_camp        # → change set id, diff summary, validation
bin/tfn-studio quest describe q_example_wolves
bin/tfn-studio quest stage q_example_wolves
bin/tfn-studio ute stage my_encounter
bin/tfn-studio changes list | show ID --diff | validate ID | apply ID | undo ID | discard ID
```

Specs are plain JSON in `specs/camps/`, `specs/quests/`, `specs/utes/` (examples shipped:
`example_bandit_camp.json`, `example_random_camp.json`, `q_example_wolves.json`). They are declarative and re-appliable — handy for scripting
and for driving the tools from Claude.

## Safety model

* All generators write to a **staging area** (`.studio/changes/<id>/`). *Apply* copies files into `<TFN>/src/**`.
* Apply refuses files with **uncommitted git changes** and files changed since staging (override explicitly), and keeps an **undo record**.
* Writes are confined to `<TFN>/src/`; resrefs are validated (`^[a-z0-9_]{1,16}$` for new ones).
* The server binds to `127.0.0.1`, checks the `Host` header, requires a per-run token (`X-Studio-Token`) and same-origin `Origin` on every POST/DELETE, and sends no CORS headers. It has no login — don't expose it.
* JSON is re-serialized **byte-exactly** like `nwn_gff -p` (4138 of 4140 TFN files round-trip identically), so diffs contain only real changes.
* Tooling never commits or pushes.

## Validation

1. canonical `nwn_gff` JSON formatting; 2. structural + cross-reference lints (blueprints exist, group markers exist, `cr` set,
quest tags ≤ 27 chars and in the journal, dialog graph integrity, scripts exist…); 3. `nwn_gff` JSON → GFF → JSON round trip
(float-32 aware); 4. `nwnsc` compile of generated scripts (with a timeout — nwnsc can hang on some syntax errors).
Problems that were already present in a file before your change are shown as *(pre-existing)* warnings and don't block.

## Tests

```
python3 -W ignore -m unittest discover -s tests -t .     # 232 tests, ~40 s; reads TFN, writes only to temp dirs (Python 3.9 and 3.10 verified)
python3 scripts/build_manual.py --check                     # MANUAL.html is in sync with MANUAL.md
bin/tfn-studio serve --port 8351 &  node tests/ui/ui_smoke.js   # real-browser smoke test, 65 checks (needs Playwright)
python3 -u scripts/e2e_scratch_pack.py --work /tmp/tfn-e2e   # stage+apply on a scratch TFN copy, run the real nasher pack (~2 min)
```

## Heights and walkability

The studio reads the NWN install (`$NWN_ROOT`, else the usual Steam/GOG/`~/nwn-data` locations) through `nwn_resman_extract` and ports Q-nwn-mcp's
walkmesh logic: world position → tile → tileset `.set` model → ASCII `.wok` mesh → triangle test. Beyond Q-nwn-mcp it also applies the
mesh node's `position` offset and the tileset's `Transition` metres per `Tile_Height` level (5 for most outdoor sets, 4 for `tcn01`, 2 for `tno01`). Calibrated on 28 TFN areas across 14 tilesets, **99 % of existing objects' stored heights
match the computed floor within 0.35 m** and 97 % of existing creatures/waypoints probe as walkable.

* New objects get their exact Z from the walkmesh (neighbour-guessing is only the fallback).
* The map has a **walkable** layer; ghosts and plan objects (creatures, spawn markers, waypoints) on non-walkable ground get a red ring and a warning.
* Props on non-walkable surfaces are allowed (rocks, trees, walls) and only noted.

## Known limits

* Creature/placeable blueprints must exist in TFN (`src/utc`, `src/utp`) or already be placed in some TFN area (the studio then reuses the most common real instance — that covers 1,139 base-game props and 472 base-game creatures such as guards and animals). Base-game blueprints TFN never uses are not available; quest targets/NPCs can only be cloned from `src/utc` blueprints.
* Creature instances keep the blueprint's reference-form equipment (as Q-nwn-mcp does); verify one plot NPC in-game.
* Without the NWN install (`nwn_resman_extract` + `data/nwn_base.key`) heights fall back to neighbouring objects and no walkability checks are possible.
* Tools are auto-detected per OS (`<TFN>/tools/<linux|macos_arm64|win>/…`, then `../nwn-tools/<platform>/…`, or `$NWN_TOOLS`); override with `$NWN_GFF`, `$NWNSC`, `$NASHER`, `$NWN_RESMAN_EXTRACT`. Intel Macs have no bundled tools (validation is skipped unless you point those variables at your own builds).

See [PLAN.md](PLAN.md) for the design and [PROGRESS.md](PROGRESS.md) for status.
