# Progress

Legend: `[x]` done · `[~]` in progress · `[ ]` todo · `[!]` blocked/needs attention.
Update this file at the end of every work chunk (the session may be cut off by token limits).

## Resume instructions (for a fresh session)
1. `cd ~/git/Q-tfn-content-studio` — read `PLAN.md` (design) then this file (state).
2. Run tests: `python3 -W ignore -m unittest discover -s tests -t . ` (needs `~/git/the-frozen-north`; skips otherwise;
   tests only *read* TFN and write to temp dirs).
3. Pick the first unchecked item below and continue. Keep generators writing to **staging only**.
4. Commit/push only when the user asks (remote `origin` = `/var/www/storage/git/q-tfn-content-studio`, a bare repo on the Linux box, branch `main`). Never modify `~/git/the-frozen-north` except through *Apply*.

## Milestones
- [x] **M0 Scaffold + plan** — repo created (`git init`), `PLAN.md`, `PROGRESS.md`.
- [x] **M1 Core** (25 tests)
  - [x] `gffjson.py` byte-exact reader/writer (4138/4140 TFN JSON files identical; 2 hand-edited files have tabs)
  - [x] `project.py` (paths, strict/lenient resref checks, LRU read cache, git status, tool discovery)
  - [x] `index.py` (incremental cached summaries: areas, creatures, items, utes, journal, placeable palette, quest wiring) — full build ≈ 3.5 s
  - [x] `changeset.py` (stage, diff, persist, apply w/ conflict + dirty guard, undo log)
  - [x] `validate.py` (lints for git/ute/utc/uti/jrl/dlg, `nwn_gff` round trip at float32 precision, `nwnsc` compile with timeout; legacy errors downgraded to "(pre-existing)" warnings)
- [x] **M2 Camps & spawns** (15 tests)
  - [x] `instances.py` (blueprint → GIT instance; verified vs real toolset output; Z inference; plan-tag removal)
  - [x] `camps.py` (plan validation, idempotent rebuild via `studio_plan` var, markers/vars/events/new UTEs)
  - [x] `spawns.py` (UTE builder, expected-mix maths, usage scan, CR advisory)
  - [x] `prefabs.py` + 10 starter prefabs (`scripts/make_starter_prefabs.py --check` verifies resrefs)
  - [x] `service.py` (shared Studio facade: lazy indexes, spec store, stage/validate/apply/undo) + CLI `bin/tfn-studio` (index, status, areas, area, prefabs, camp stage|stamp, ute stage, quest stage|describe, changes list|show|validate|apply|undo|discard, serve)
- [x] **M3 Quests** (19 tests)
  - [x] `dialogs.py` (builder, merge into existing dlg, add-then-remove restores real dialogs byte-for-byte)
  - [x] `quests.py` (journal, vars on blueprint **and placed instances**, dlg, uti, nss; talk/kill/pickup/explore; idempotent no-op rebuild via slot reuse + in-place var sync + deferred placement)
  - [x] CLI `tfn-studio quest stage|describe`; shipped examples `specs/quests/q_example_wolves.json`, `specs/camps/example_bandit_camp.json` (stage cleanly against real TFN: 0 errors, ~1.3 s)
- [x] **M4 Web UI** (10 API tests + 28-check Playwright browser test, zero console errors)
  - [x] `server.py` (JSON API; localhost bind, Host check, per-run token + Origin check on POST/DELETE, CSP, path-traversal safe)
  - [x] Dashboard · Camp Builder (`areamap.js` canvas, prefab stamping, props/creatures/markers/waypoints, groups, events, undo) · Spawn Designer (`uteeditor.js`) · Quest Builder (stages, map position picker, existing-quest browser) · Changes (diff, validate, apply, undo, discard)
  - [x] `tests/ui/ui_smoke.js` (Playwright; run against `bin/tfn-studio serve --port 8351`)
- [x] **M5 Extras**
  - [x] **Walkmesh** (`gamedata.py` + `walkmesh.py`, 7 tests): exact ground Z + walkability; ported from Q-nwn-mcp and *improved* (node `position` offset, `Tile_Height` × the tileset's `Transition` — see M7); calibrated on 28 areas/14 tilesets: 99 % heights within 0.35 m, 97 % existing creatures walkable. Integrated in camps/quests (Z + warnings), `/api/areas/<r>/walk`, map overlay + red rings. Found that the first example camp spot (70,70 in `mantle`) was non-walkable → moved to (68.5,45.5).
  - [x] base-game creatures/props: **mined from real TFN instances** instead of extracting game blueprints. Rationale (measured): 0/486 `.ute` entries use base-game creatures, 1,139/1,262 palette props are already base-game (mined), 968 placed instances use 472 base creatures. `index.mine_creature_template`, `base_creature_palette`, `/api/palette/creatures?base=1`, Camp Builder "base-game" chip. Not done: extracting arbitrary base blueprints / appearance picker (2DA) — low value for TFN.
  - [x] camp UX: **Find open ground** (summed-area search over the walk raster), **Save as prefab…** (`/api/prefabs`, injectable `prefab_dir`), prefab marker-group remapping
  - [ ] trigger/door/store support (not started; low priority)
- [~] **M6 Docs & e2e**
  - [x] `README.md`, `CLAUDE.md`, `.gitignore`
  - [x] `scripts/e2e_scratch_pack.py` (scratch copy of TFN → stage+apply example camp + 2 quests incl. an explore stage → real `nasher pack` as the swamp build does → verify packed resources). **PASSED 2026-10-02**: nasher exit 0 in 103 s, 142 MB module contains hunter_marek/alpha_wolf/q_alphapelt/e2e_scout_npc + dialogs, compiled enter_quest_adv.ncs, modified mantle.git, journal has both quests. Run: `python3 -u scripts/e2e_scratch_pack.py --work <dir>` (~2 min, needs ~700 MB free)

- [x] **M7 Setup & portability** (user ran it on macOS: `error: /Users/sean/git/the-frozen-north does not look like a TFN checkout`) — 30 tests in `tests/test_setup.py`
  - [x] **macOS/Windows aware tool lookup** (`project.platform_dirs/tool_candidates/find_tool`): `<TFN>/tools/<linux|macos_arm64|win>/…`, `../nwn-tools/<platform>/…`, `$NWN_TOOLS`, `.exe`/`neverwinter64` on Windows; before, only `linux/` was searched (a Linux ELF on a Mac was "found" and could not run). A tool that cannot execute now degrades to `SKIP:` instead of crashing validation.
  - [x] **Actionable checkout errors**: says whether the folder is missing / a file / lacks `src/git`/`src/are`, where the path came from (`--tfn`, `$TFN_ROOT`, default), and lists TFN checkouts nearby (TFN-specific marker `src/nss/inc_quest.nss`, so sibling NWN modules are not suggested).
  - [x] `--tfn PATH` accepted **before or after** the command (`cli.extract_tfn`); `tfn-studio doctor` (new `doctor.py`: Python, OS/tool folder, git, checkout, tools, NWN install, port; works without a checkout); friendly "port in use" error; launcher checks the Python version.
  - [x] NWN install auto-detect (`gamedata.find_root/find_user_dir`: `~/nwn-data`, macOS/Linux/Windows Steam, GOG); `--userdirectory` only passed when the folder exists.
  - [x] **Python 3.9 compatible** (macOS's stock `python3` is 3.9.6): one runtime `X | None` alias fixed in `index.py`; whole suite passes on 3.9.25 and 3.10.12.
  - [x] **MANUAL.md** — installation, startup, usage of every page, CLI reference, troubleshooting (sent to the user).
  - [x] **Extractor salvage** (`gamedata.GameData._extract`): `nwn_resman_extract` extracts NOTHING when any requested file is missing (base game: `tcm02_b92_02.wok`, `trs02_m00_00.wok`), which made heights/walkability silently unavailable for such an area (and the whole 200-name chunk was remembered as missing). A failed batch is now bisected so every existing file is extracted; a broken extractor gives up after 6 runs without success.
  - [x] **Height step fix**: `Tile_Height` lift is the tileset's `[GENERAL] Transition=` metres, not a constant 5 (`walkmesh.parse_transition/Walkmesh.height_step`). Evidence on real TFN objects standing on raised tiles: `benzor` (tcn01, Transition 4) 108/115 within 0.5 m vs 4/115 with 5 m; tno01 areas (Transition 2) 46/50 vs 0/50. Base-game Transition values: 5 for ttr01/tts01/tts02/tti01/ttu01/ttz01/trm02/tms01/tcm02/trs02/tss13, 4 tcn01, 3 interiors/dungeons (no height levels), 2 tno01, 1 twc03. (Same finding applied to Q-nwn-mcp `walkmesh.ts`.)

- [x] **M8 Manual as a web page** (user: "convert the md manual into HTML, link it in the web view, host it in the project root so it can be read without a working environment")
  - [x] `tfnstudio/mdhtml.py` — stdlib Markdown→HTML converter (headings with GitHub-style ids, tables incl. `\|`, nested/loose lists, fenced code in list items, links with a safe-scheme whitelist, no raw HTML). **Token-for-token identical to the markdown-it-py CommonMark+tables reference on MANUAL.md and 7 other real docs** (dev-time check, not a dependency); 42 tests in `tests/test_mdhtml.py`, mutation-checked.
  - [x] **`MANUAL.html` in the project root** — one self-contained file (inline CSS in the studio's palette, light/dark, print styles, sticky contents sidebar, copy buttons, ~68 KB, no network), generated by `scripts/build_manual.py` (`--check` in the tests). Verified from `file://` in real Chromium (desktop, dark, phone), no console errors.
  - [x] **Web view**: server routes `/manual`, `/manual/`, `/MANUAL.html` (+ read-only text whitelist `/README.md /PLAN.md /MANUAL.md` — exactly the documents the manual links to) with a CSP that allows exactly the page's inline script by sha256; falls back to rendering `MANUAL.md` if the HTML is missing. UI: **Manual ↗** link in every page's top bar (context-aware: `/manual#7-camp-builder` on the Camp Builder, opens in a new tab) and a Manual card on the Dashboard. CLI: `tfn-studio manual [--open]`; the checkout error and `doctor` point at the file.
  - [x] Found by testing on Python 3.9: `Path.write_text(newline=)` is 3.10+ → `mdhtml.write_page`. Browser smoke test now 49 checks (17 new for the manual: links, new tab, served vs `file://`, phone width).

- [x] **M9 Random camp events** (user: "Yes" to "add a random camp option to the Camp Builder", 2026-10-03; refined: camp at one of several
  hand-placed location markers with a direction) — design and as-built notes in PLAN.md section 4b
  - [x] `tfnstudio/campevent.py`: template transform (same maths as prefab stamping), per-spot variants with walkmesh heights/issues, event + gate script generators, contiguous event-slot wiring, chain/stale cleanup, header ownership, spot suggestions
  - [x] `camps.py`: `camp_event` in `validate_plan`; event mode in `build()` (props/creatures -> script, markers/waypoints stay in the GIT); `event_info()` dry run; `suggest_spots()`
  - [x] `index.summarize_area` `event_wps` (cache version 6); `validate.lint_git`: gaps in `eventN` and events without a `_wp_event` waypoint; `area_detail` waypoint facing
  - [x] server `POST /api/camps/event-info`, `POST /api/camps/suggest-spots`; CLI `camp stamp --random-camp --spot --include-here --weight --replaces-group --replace-radius --event-chance --script`, `camp spots`
  - [x] Camp Builder UI: Random camp panel, Spot and Pivot tools, spots draggable/turnable on the map, per-spot preview of the whole camp, Suggest, Import markers, Replaces group, live chance/wiring card, stage blockers
  - [x] tests: `tests/test_campevent.py` (67 new tests incl. nwnsc compile + negative control, idempotency, transitions, ownership, fake-walkmesh geometry), server tests, 17 new browser checks, example spec `specs/camps/example_random_camp.json`, e2e `nasher pack` with the random camp
  - [x] docs: MANUAL.md section 7.5 (+ CLI, files, safety, troubleshooting, glossary; MANUAL.html regenerated), README, CLAUDE.md
  - not done / ideas: see "Ideas" below. **Not run in a live NWN server** (static verification only, see PLAN.md 4b item 15).
- [x] **M10 Modern quest script style + converter** (user request, 2026-10-28)
  - [x] spec `script_style` `modern|legacy` (absent = legacy, so existing specs/drafts are unchanged); modern uses new generic `dlg_q_chk_at` (`target` param, any slot) instead of `dlg_q_chk_atcN`; script shipped by the change set only when TFN lacks it (`quests.GENERIC_AT[_SRC]`, `_cond_current`)
  - [x] Quest Builder: top-right "Quest scripts: Modern/Older" toggle (`quests.js`); new drafts modern, saved drafts without the field load as Older
  - [x] `convert_quests.py` + CLI `quest convert [--check] [--dialog R]`: numbered `dlg_q_*N` -> base + `target` param as a staged change set; NOT run on TFN (dry run says: 85 dialogs / 494 of 503 calls convertible, 9 left alone because they already carry params); verifies numbered scripts == generic script, effective-call equality, byte round-trip
  - [x] tests `tests/test_convert_quests.py` (6), 4 new in `test_quests.py`; manual section 9.3-9.5 (plain-English flow, limits, converter); MANUAL.html regenerated
  - quest slot limit left at 19 (TFN `HIGHEST_QUEST_COUNT = 20` in inc_quest.nss + hard-coded 20 in area_init.nss) — not changed
  - note: on this Mac 6 older tests fail with and without this change (GFF round-trip via the local nwn_gff: `.../LocName/value/id: missing in source`); run with `TFN_ROOT=~/Documents/GitHub/the-frozen-north`
- [x] **M11 Merged into Q-nwn-manager as `studio/`** (user request, 2026-10-28; copied without history, nothing committed, branch `feature/content-studio`)
  - [x] `project.py`: layouts `by_ext` (TFN `src/<ext>/`) and `flat` (nwn-manager `unpacked/`), profiles `tfn`/`generic` (`detect_layout`, `detect_profile`, `studio.json` override, `parse_rel`, base-script dirs); root from `--module`/`--tfn`, `$MODULE_ROOT`/`$TFN_ROOT`, nearest `nasher.cfg`; tools also from PATH and `$NWN_TOOLS_DIR`
  - [x] generic profile keeps staging in `<project>/.studio`, drafts in `<project>/studio-specs`; spawn/random-camp/ute staging refused with a clear message
  - [x] `runtime.py` + `runtime/generic/`: self-contained quest runtime (inc_quest, dlg_q_adv/chk_eli/chk_atp/chk_at, enter_quest_adv, qs_ondeath, qs_acquire, qs_npc/qs_questitem templates); installed by the first quest or `setup`; progress = PC local int `qs_<tag>` + journal; never overwrites a module's own script of the same name
  - [x] quests.py generic branches (journal created when missing, ScriptDeath -> qs_ondeath, explore via ARE OnEnter, templates), modern style forced; validate.py compiles staged includes and skips include-only files
  - [x] UI: brand/nav/legacy toggle depend on `/api/session` profile+features; default clone template `qs_npc`
  - [x] `nwn-manager studio ...` (bash wrapper; python source preferred, `_pytools_main.py` + spec updated), MANUAL chapter 18, README section
  - [x] tests: `tests/test_generic_module.py` (11, synthetic flat module, no TFN files), `tests/generic_fixture.py`
  - not done: base-game creature cloning (no `nwn_resman_extract` on macOS), embedding in the console, a blank-module `new` command, rebuilt `nwn-pytools` binaries, package rename (`tfnstudio` kept), running it in a real game

## Test status (2026-10-03)
232 unit tests (`python3 -W ignore -m unittest discover -s tests -t .`, ~40 s; green on Python 3.9 and 3.10) · 65 Playwright checks (`tests/ui/ui_smoke.js`) ·
e2e scratch-copy `nasher pack` passed incl. the random camp's `eve_ex_camp.ncs` / `spw_ex_camp.ncs` (`scripts/e2e_scratch_pack.py`).

## Ideas / not done (pick up here)
- Random camps: a shared camp/spot library per area; different templates per spot; drag-to-aim direction when placing a spot; a runtime mode that builds the camp at the
  event waypoint `area_refresh` picked (OBJECT_SELF) instead of absolute spots; hiding the replaced group's creatures before they appear (needs an `area_refresh` hook in TFN).
- [ ] **Decide what to do with the empty private GitHub repo `SeanMJOBrien/Q-tfn-content-studio`.** It was created by mistake on 2026-10-02, before the
  bare repo `/var/www/storage/git/q-tfn-content-studio` was named as the push target: size 0, nothing pushed, and this repo's `origin` does not point at it.
  Delete it (`gh auth refresh -h github.com -s delete_repo`, then `gh repo delete SeanMJOBrien/Q-tfn-content-studio`, or GitHub → Settings → Danger zone)
  or keep it as an additional remote.
- Triggers / doors / stores / sounds as plan object kinds (instances are easy; UI + validation need work).
- Walkability-aware *auto-scatter* of marker groups; per-area "suggested camp spots".
- Quest builder: raw editor for `prereq`/`jumpstage`/`bluff_dc`; multi-NPC UI for talk stages (backend supports `npc` per stage).
- Prefab thumbnails; prefab delete/rename in the UI.
- In-engine check of reference-form equipment on a persistent (plot) NPC instance (see Decisions & risks).

## Decisions & risks (keep current)
- Creature instances keep the blueprint's reference-form equipment (`EquippedRes`), as Q-nwn-mcp's `place_creature`
  does; real toolset instances inline full item structs. **Unverified in-engine** — TFN deletes/respawns hand-placed
  creatures from the blueprint anyway; plot/immortal NPCs persist, so check one in the toolset/server when possible.
- Orientation convention: facing in degrees, 0 = east, 90 = north (NWScript); creature orientation = (cos, sin);
  placeable `Bearing` = radians of the same facing.
- Placeable instances come from `src/utp` blueprints, else the *mode* instance mined from existing TFN GITs
  (`index.mine_placeable_template`). Base-game-only blueprints are not supported yet (M5).
- nwnsc quirks: `-b` needs a **relative** input path (cwd = file dir); some syntax errors make it loop forever → always
  run with a timeout (`validate.compile_script` does, 30 s).
- `pkill -f <pattern>` can kill the calling shell if the pattern is in its own command line → use `pkill -x`.
- `node --check` does NOT reliably catch syntax errors in ESM `.js` (exit 0 even for garbage): copy to `.mjs` first.
- DOM `Element.append(null|array)` prints "null"/"[object ...]": always use `put()`/`h()` from `static/common.js`.
- The web form sends `""` for untouched optional fields: server-side text defaults must treat blank as missing (`quests._txt`).

## Findings log (facts discovered while investigating; keep short)
- 2026-10-02: `nwn-mcp` server in Claude sessions runs from `~/git/Q-nwn-mcp/dist/index.js`;
  NWN data root `/home/qlippoth/nwn-data` (user dir `…/user`); `nwn_resman_extract` works there
  (`placeables.2da` extractable, 3 MB — heavily extended).
- TFN: 504 areas (362 MB GIT), 128 `.ute`, 506 `.utc`, 417 `.dlg`, 1358 `.uti`, single `module.jrl.json` (90 categories).
- Build = swamp model `thefrozennorth-build` (`swamp model method run thefrozennorth-build build` from `~/git`).
  Running `swamp` inside the TFN repo fails (stray `.swamp/` without `.swamp.yaml`) — run from `~/git`.
- Instances snapshot the blueprint VarTable at placement time (stale if the blueprint changes later), and omit an empty
  VarTable. ⇒ quest-var changes must patch placed instances too.
- Quest kill credit: `quest_kill = N` on the creature + `ai_ondeath` (party_credit.nss). Item pickup: Tag `quest` + `quest1`.
  Explore: area var `quest1` + `enter_script` calling `AdvanceQuest(OBJECT_SELF, oPC, 1)`.
- Parallel Bash calls that `cd` can race — always use absolute paths.

- Flat ground is not always z = 0: base tilesets' flat-tile walkmesh sits at constant offsets (trm02/tno01 +5, tbw01 ≈ +5.1, ttu01/ttz01 +1, tss13 ≈ +1.9) — always use the probe, never assume 0.
- macOS: default `python3` (Xcode CLT) is 3.9.6; TFN ships `tools/macos_arm64/{nasher,neverwinter,nwnsc,sqlite}`; Steam install is `~/Library/Application Support/Steam/steamapps/common/Neverwinter Nights`; unsigned tools copied via browser/AirDrop need `xattr -dr com.apple.quarantine`.
- TFN's own build docs: pack-only `nasher pack` (safe) vs `<os>_nasher_install.sh` (also wipes/reseeds databases) — `docs/TEST_PLAN.md`, `CHANGES_AND_TEST_PLAN.md`.

## Session log
- 2026-10-02 (session 1): investigated TFN spawn + quest systems, read Q-nwn-mcp/Q-nwn-manager docs,
  created project, wrote PLAN.md + PROGRESS.md, built M1 (core), M2 (camps/spawns/prefabs/CLI) and M3 (dialogs/quests);
  59 tests green; example camp + quest stage cleanly against the real TFN tree.
- 2026-10-02 (session 1, cont. 2): walkmesh feature (see M5), 77 tests + 28 UI checks green, e2e nasher pack passed.
- 2026-10-02 (session 1, cont.): M4 web server + 5 pages; browser smoke test found and fixed 3 real UI bugs
  (stage button not refreshing, stray "null"/"[object]" text, blank dialog fields → empty NPC lines); README/CLAUDE.md;
  e2e script written (scratch-copy nasher pack). Next: confirm e2e result, then M5 extras (base-game blueprints, walkmesh).
- 2026-10-02 (session 2): user hit the macOS checkout error → M7 (portability, `doctor`, 3.9 support, per-tileset height step, MANUAL.md); README updated.
- 2026-10-02 (session 2, cont.): M8 — MANUAL.html (converter, project-root file, `/manual`, links, tests); 165 unit + 49 browser checks green.
- 2026-10-02 (session 2, end): everything committed and pushed to the bare repo `/var/www/storage/git/q-tfn-content-studio` (`origin/main`).
- 2026-10-28: M10 (modern quest script style, `dlg_q_chk_at`, Modern/Older toggle, `quest convert` converter + manual 9.3-9.5). Converter never run for real.
