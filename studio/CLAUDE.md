# Q-tfn-content-studio — notes for Claude

Local web UI + CLI that generates The Frozen North (TFN) content (quests, camps incl. random camps, spawn groups, `.ute` blueprints) as
nasher source. Read `PLAN.md` (design) and `PROGRESS.md` (state, resume instructions, risks) first.

## Rules

* **Never write to `~/git/the-frozen-north` except through `changeset.apply_changeset`** (the web *Apply* / `tfn-studio changes apply`).
  Generators stage into `.studio/changes/`. Tests must only *read* the real TFN and write to temp dirs (`tests/fixture.py`).
* **No commits/pushes** unless the user asks. Keep `PROGRESS.md` current after every chunk of work (sessions get cut off).
* Python **stdlib only**; front end is dependency-free ES modules. Don't add packages or CDN links.
* Keep it **Python 3.9-compatible** (macOS's stock `python3` is 3.9.6): `from __future__ import annotations` in every module,
  no runtime-evaluated `A | B` (use `Optional[...]` in aliases), no `match`. Check with `$(uv python find 3.9) -W ignore -m unittest discover -s tests -t .`.
* Tools/paths are **per OS** (`project.find_tool`, `gamedata.find_root`): never hard-code `linux/` or `~/nwn-data`.
* `MANUAL.md` is the manual's source; **`MANUAL.html` (project root) is generated** by `python3 scripts/build_manual.py` (stdlib converter
  `tfnstudio/mdhtml.py`) and committed. After editing `MANUAL.md` regenerate it - `tests/test_mdhtml.py` fails when they disagree. The page must stay
  one self-contained file (inline CSS/JS, no network): it is read straight from the file system *and* served at `/manual`.
  Python 3.9: no `Path.write_text(newline=)` (use `mdhtml.write_page`), no `A | B` at runtime.
* JSON must be written with `tfnstudio.gffjson.dumps` (byte-exact nwn_gff style). Never `json.dump` GFF data.
* Front end: build DOM with `h()` / `put()` from `static/common.js` (text is inserted as text — no `innerHTML` with data);
  never call `Element.append(array|null)` directly.
* Build TFN with the swamp model `thefrozennorth-build` (run `swamp` from `~/git`; it fails inside the TFN repo because of a
  stray `.swamp/`). Don't run it unless asked.

## Layout

```
tfnstudio/  gffjson project index instances dialogs camps campevent spawns quests prefabs changeset validate service cli server doctor mdhtml
            web/{*.html, static/*.js, static/app.css}
specs/      saved camp/quest/ute specs (JSON)       prefabs/   10 starter camp prefabs (scripts/make_starter_prefabs.py)
tests/      unittest suite on a mini TFN built from real files; tests/ui/ui_smoke.js = Playwright browser test
```

## TFN facts the code relies on (verified against the real tree)

* Spawns: area VarTable (`cr`, `randomN`, `randomN_spawns`, …) + `random1…9` marker creatures + `.ute` (`SingleSpawn`=unique,
  `DifficultyIndex` 0-4 → 5…25 % unique, var `rare`). Instances omit an empty VarTable and snapshot the blueprint's vars.
* Quests: `questK="NN_<tag>"` slot vars, `dlg_q_*` generic scripts with `target` params, `quest_kill`, item Tag `quest`, explore via area
  `enter_script`. Registration is automatic in `area_init` (needs the var on a placed instance).
* GIT instance key order = `__struct_id` then case-insensitive alphabetical; list item struct ids: creature 4, placeable 9, waypoint 5.
* Events (`campevent.py`, verified in `area_init`/`area_refresh`): `events` is counted from `event1` up to the **first empty slot** (keep them contiguous);
  one `Random(events)` pick after one `event_chance` roll (0/unset = 50), only if the area has a `_wp_event` waypoint; the script runs with OBJECT_SELF = that waypoint.
  Duplicate script names in `eventN` are TFN's way of weighting. Props created at runtime must be finished like `area_init` does (static/plot for inventory or trap, `treas_init` for `treas_*`).
* Generated scripts start with `// tfn-studio camp event|gate: plan <id>`; **only scripts with the same plan id may be overwritten** (`campevent.check_script_free`).

## Quirks

* `nwnsc -b` needs a relative input path; some syntax errors make it loop forever → always use a timeout.
* `node --check` is unreliable on ESM `.js`: copy to `.mjs` first (see how PROGRESS.md/tests do it).
* `pkill -f` can kill your own shell (pattern appears in the command line); use `pkill -x`.
* Parallel Bash calls that `cd` can race — use absolute paths.

## Run

```
python3 -W ignore -m unittest discover -s tests -t .
bin/tfn-studio serve --port 8351            # UI;  node tests/ui/ui_smoke.js  (Playwright) to smoke-test it
```
