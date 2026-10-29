# TFN Content Studio — Installation, Startup and Usage Manual

Version of 2026-10-03. For the design background see [PLAN.md](PLAN.md); for a short overview see [README.md](README.md).

**Just want to read this, with nothing set up?** Open `MANUAL.html` (in the same folder as this file) in any browser — it is one self-contained file
that needs no studio, Python or internet. The running studio serves the same page at `/manual`; every page's top bar has a **Manual ↗** link to it,
and `./bin/tfn-studio manual` prints its location.

**What this is.** A small web app that runs on your own computer. You design **quests**, **camps** (props + creatures + spawn
markers), **spawn groups** and **encounter blueprints** on a map or in forms. The studio turns that into the exact files
*The Frozen North* (TFN) expects (`src/**/*.json`, a few `.nss`), shows you the diff, validates it, and only then — when you
press **Apply** — writes it into your TFN checkout. Everything can be undone.

---

## Contents

1. [Quick start](#1-quick-start)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Starting and stopping](#4-starting-and-stopping)
5. [How you work with it (the loop)](#5-how-you-work-with-it-the-loop)
6. [Dashboard](#6-dashboard)
7. [Camp Builder](#7-camp-builder)
8. [Spawn Designer](#8-spawn-designer)
9. [Quest Builder](#9-quest-builder)
10. [Changes: review, apply, undo](#10-changes-review-apply-undo)
11. [After Apply: build, restart, test](#11-after-apply-build-restart-test)
12. [Command line reference](#12-command-line-reference)
13. [Where things live](#13-where-things-live)
14. [Safety model and good habits](#14-safety-model-and-good-habits)
15. [Troubleshooting](#15-troubleshooting)
16. [Reference](#16-reference)
17. [Updating, moving and removing](#17-updating-moving-and-removing)
18. [Using the studio with any module (nwn-manager)](#18-using-the-studio-with-any-module-nwn-manager)

---

## 1. Quick start

Open a terminal in the studio folder and run:

```bash
cd ~/git/Q-tfn-content-studio
./bin/tfn-studio doctor                       # checks Python, your TFN checkout, tools, NWN install, port
```

`doctor` prints one line per check: `[ok]`, `[warn]` (optional feature reduced) or `[FAIL]` (must fix).

If it says the TFN checkout is missing — **this is the error
`... does not look like a TFN checkout (missing src/git or src/are)`** — tell the studio where your checkout really is.
The default is `~/git/the-frozen-north`; if yours lives anywhere else, use one of:

```bash
./bin/tfn-studio --tfn "/path/to/the-frozen-north" doctor       # one-off (works before OR after the command)
export TFN_ROOT="/path/to/the-frozen-north"                     # for this terminal
echo 'export TFN_ROOT="/path/to/the-frozen-north"' >> ~/.zshrc  # permanently (macOS default shell: zsh)
```

The right folder is the **nasher project root** — the folder that directly contains `src/`, `nasher.cfg` and `tools/`
(so that `src/are` and `src/git` exist inside it). Pointing at `src/` itself, or at the folder *above* the checkout, does not work.

When `doctor` is green (warnings are fine):

```bash
./bin/tfn-studio serve --open                 # opens http://127.0.0.1:8350/ in your browser
```

Stop it with **Ctrl+C**.

---

## 2. Requirements

| Need | Details |
|---|---|
| **Python 3.9 or newer** | Nothing to `pip install` — the studio uses only the standard library. macOS's stock `/usr/bin/python3` (3.9.x, from the Xcode Command Line Tools) works; so does Homebrew Python. Tested on 3.9 and 3.10. |
| **git** | Used to show the branch and to refuse overwriting files you have uncommitted changes in. macOS: `xcode-select --install`. |
| **A TFN checkout** | The nasher project (`the-frozen-north`) with `src/are`, `src/git`, `src/utc`, `src/dlg`, … The studio reads and (on Apply) writes only inside its `src/` folder. |
| **A modern browser** | Current Chrome, Firefox, Edge or Safari. No internet needed: all pages and scripts are local. |
| **NWN tools** *(recommended)* | `nwn_gff` (JSON round-trip validation), `nwnsc` (script compile check). TFN ships them in its own `tools/<platform>/` folder, so with a normal checkout they are found automatically. Without them validation of that kind is skipped (shown as *info*). |
| **NWN:EE install** *(optional)* | Gives exact ground heights and a walkable/non-walkable overlay on the map (needs `data/nwn_base.key` and the `nwn_resman_extract` tool). Without it, heights are guessed from neighbouring objects and there is no walkability check. |

Tool folders are named per operating system: `linux`, `macos_arm64` (Apple-silicon Macs), `win`. On an **Intel Mac** no bundled
tools exist; set `NWN_GFF` / `NWNSC` to your own builds, or live with the skipped checks.

---

## 3. Installation

### 3.1 Recommended folder layout

Keep the three things side by side:

```
~/git/
  the-frozen-north/        your TFN checkout (has src/, tools/, nwn-base-scripts/, nasher.cfg)
  Q-tfn-content-studio/    this tool
  nwn-tools/               OPTIONAL shared tools: macos_arm64/…, linux/…, win/…  (only needed if TFN's own tools/ is missing)
```

Nothing is installed system-wide; the studio runs from its folder.

### 3.2 Getting the studio onto the machine

You need the `Q-tfn-content-studio` folder (about 65 files, under 1 MB). Pick whichever fits:

* **Through git (recommended — later updates are just `git pull`).** The studio's repository is a bare repo on the Linux machine,
  `/var/www/storage/git/q-tfn-content-studio` (the `origin` remote of its working copy). On the machine you want it on, clone it over SSH
  (replace `user@host` with how you log in to the machine that holds `/var/www/storage`):
  `git clone user@host:/var/www/storage/git/q-tfn-content-studio ~/git/Q-tfn-content-studio`.
* **Copy it from the machine it was built on** (replace user/host):
  `rsync -av --exclude .studio --exclude __pycache__ --exclude .git user@host:git/Q-tfn-content-studio/ ~/git/Q-tfn-content-studio/`
* **From an archive**: unpack the `.tar.gz` you were sent into `~/git/` (`tar -xzf Q-tfn-content-studio.tar.gz -C ~/git`).

Make sure the launcher is executable: `chmod +x ~/git/Q-tfn-content-studio/bin/tfn-studio`
(or always start it as `python3 bin/tfn-studio …`).

### 3.3 Check Python

```bash
python3 --version        # 3.9 or newer
```

If macOS answers with a dialog about "command line developer tools", accept it (that installs `python3` and `git`), or run
`xcode-select --install`, or `brew install python`.

### 3.4 Tell the studio where TFN is

Default location: `~/git/the-frozen-north`. Anything else: `--tfn PATH` or `TFN_ROOT` (see [Quick start](#1-quick-start)).
Check the folder is right:

```bash
ls "/path/to/the-frozen-north/src" | head        # should list: are  dlg  git  jrl  nss  utc  utp …
ls "/path/to/the-frozen-north/src/are" | head -3
```

If `src/are` is empty or missing, that clone is incomplete (or is on a branch without content): `git -C … status`, `git -C … pull`.

### 3.5 Tools (`nwn_gff`, `nwnsc`, `nwn_resman_extract`)

The studio looks, in this order, for each tool:

1. an environment variable naming the program: `NWN_GFF`, `NWNSC`, `NASHER`, `NWN_RESMAN_EXTRACT`;
2. `$NWN_TOOLS/<platform>/…` if you set `NWN_TOOLS`;
3. `<TFN>/tools/<platform>/…` — TFN's own bundled tools;
4. `<TFN>/../nwn-tools/<platform>/…` — a shared `nwn-tools` folder next to the checkout;
5. `<studio>/../nwn-tools/<platform>/…`.

`<platform>` is `macos_arm64` on a Mac, `linux` on Linux, `win` on Windows. Inside it the programs are
`neverwinter/nwn_gff`, `neverwinter/nwn_resman_extract`, `nwnsc/nwnsc`, `nasher/nasher` (Windows: `.exe`, and `neverwinter64/`).

**macOS Gatekeeper.** If a tool was copied through a browser, AirDrop or a zip, macOS may refuse to run it ("cannot be opened
because the developer cannot be verified"). Clear the quarantine flag once:

```bash
xattr -dr com.apple.quarantine ~/git/the-frozen-north/tools
chmod +x ~/git/the-frozen-north/tools/macos_arm64/*/*
```

### 3.6 NWN install (optional, for exact heights and walkability)

The studio finds your NWN:EE install by itself if it is at one of the usual places (the folder must contain `data/nwn_base.key`):

| OS | Checked locations |
|---|---|
| any | `~/nwn-data` |
| macOS | `~/Library/Application Support/Steam/steamapps/common/Neverwinter Nights` |
| Linux | `~/.local/share/Steam/steamapps/common/Neverwinter Nights`, `~/.steam/steam/steamapps/common/Neverwinter Nights` |
| Windows | `C:/Program Files (x86)/Steam/steamapps/common/Neverwinter Nights` (and `Program Files`), `C:/GOG Games/Neverwinter Nights Enhanced Edition` |

Elsewhere: `export NWN_ROOT="/path/to/Neverwinter Nights"` (the folder that contains `data/`). The optional user folder is taken from
`NWN_USER`, else `<install>/user`, `~/Documents/Neverwinter Nights` or `~/.local/share/Neverwinter Nights` — whichever exists.
TFN uses no haks and no custom TLK, so the base game is all that is needed.

### 3.7 Run the check

```bash
./bin/tfn-studio doctor
```

Example of a healthy result (your versions and paths will differ):

```
[ok]   Python 3.9.6
[info] Darwin 24.5.0 (arm64); tool folder expected: macos_arm64
[ok]   Studio folder: /Users/sean/git/Q-tfn-content-studio
[ok]   git version 2.39.5
[ok]   TFN checkout: /Users/sean/git/the-frozen-north
[ok]   branch master, 0 uncommitted file(s)
[ok]   nwn_gff: /Users/sean/git/the-frozen-north/tools/macos_arm64/neverwinter/nwn_gff
[ok]   nwnsc: …/tools/macos_arm64/nwnsc/nwnsc
[ok]   NWN install: /Users/sean/Library/Application Support/Steam/steamapps/common/Neverwinter Nights
[ok]   port 8350 is free
Everything looks good. Start with:  ./bin/tfn-studio serve
```

A `[warn]` never stops the studio from running; it tells you which optional feature is reduced and how to enable it.

### 3.8 Optional: prove it works without touching TFN

Staging only writes to the studio's own `.studio/` folder, never to TFN:

```bash
./bin/tfn-studio quest describe q_example_wolves      # prints the 4-stage plan of the shipped example quest
./bin/tfn-studio quest stage q_example_wolves         # builds a change set + validates; prints its id
./bin/tfn-studio changes list
./bin/tfn-studio changes discard <id>                 # throw it away again
```

---

## 4. Starting and stopping

```bash
cd ~/git/Q-tfn-content-studio
./bin/tfn-studio serve                 # http://127.0.0.1:8350/
```

| Option | Meaning |
|---|---|
| `--open` | open the Dashboard in your default browser |
| `--port N` | use another port (default 8350). If it is busy you get a clear error and a suggested port |
| `--host H` | bind address (default `127.0.0.1`). **Leave it.** The studio has no login; see [Safety](#14-safety-model-and-good-habits) |
| `--tfn PATH` | which TFN checkout (also `TFN_ROOT`) |

* **First start:** the studio builds its content index in the background (the Dashboard shows *building… …*). On a fresh
  checkout that takes tens of seconds; afterwards only changed files are re-read (cache in `.studio/cache/`, safe to delete).
  You can already use the pages while it builds; lists fill in as soon as it is ready.
* Open the address **`http://127.0.0.1:8350/`** (or `http://localhost:8350/`). Other host names or your LAN address are refused on purpose.
* **Stop:** Ctrl+C in the terminal. Staged change sets and undo records survive restarts.
* **Keep it running in the background:** `nohup ./bin/tfn-studio serve > /tmp/tfn-studio.log 2>&1 &` (stop with `kill <pid>`),
  or use a second terminal tab.
* **Several checkouts / branches:** run one studio per checkout on different ports, e.g. `--tfn ~/git/tfn-a --port 8350` and
  `--tfn ~/git/tfn-b --port 8351`. Staged change sets are stored per studio folder, so apply each one against the checkout it was staged for.

The top bar of every page shows the TFN branch and path so you always know what you are editing, and a **Manual ↗** link that opens this manual
(at the section for the page you are on) in a new tab.

---

## 5. How you work with it (the loop)

```
 design  →  Stage  →  review on Changes  →  Apply  →  build module  →  restart server  →  test in game
 (map / forms)  (nothing written to TFN yet)   (files written, undo kept)
```

1. **Design** in Camp Builder, Spawn Designer or Quest Builder.
2. **Stage changes.** The studio generates the files and validates them. The result is a *change set*; TFN is untouched.
3. **Review** it on the **Changes** page: file list, coloured diffs, validation messages.
4. **Apply to TFN…** writes the files into `<TFN>/src/`. **Undo apply** restores the previous files.
5. **Build and restart** the module the way you normally do ([section 11](#11-after-apply-build-restart-test)). `area_init` reads
   spawn markers, area variables and quest NPCs at module load, so a restart is required.
6. **Test in game.**

Camps, spawn groups and quests need **no database reseed** (`SEED_SYSTEM.md` §12). New areas, tile edits, transitions and new
item blueprints do.

Good habit: before the first Apply of a session, create a git branch in the TFN checkout
(`git -C ~/git/the-frozen-north switch -c content/my-new-camp`) so all generated changes land on a branch you can review and merge.

---

## 6. Dashboard

`/` — status at a glance.

* **TFN checkout:** path, branch @ commit, and the number of **uncommitted files** (Apply refuses to overwrite those).
* **Tools:** `nwn_gff`, `nwnsc`, `nasher` — *found* (with path) or *missing*; **walkmesh:** *game data found* or *unavailable*.
* **Content:** file counts per type (`.are`, `.utc`, `.utp`, `.ute`, `.uti`, `.dlg`); **Index** status and a **Refresh index** button
  (use it after you changed TFN files outside the studio, e.g. after a `git pull`).
* **Change sets:** the latest staged/applied sets (click one to open it on the Changes page).
* **After you apply:** the short reminder list from [section 11](#11-after-apply-build-restart-test).

Three big cards link to the builders; a fourth opens this manual.

---

## 7. Camp Builder

`/camps` — place props, creatures, spawn markers and event waypoints on a map of an area, wire up spawn groups, stage.
It can also build a **random camp**: a camp that the area creates only now and then, at one of several spots you choose ([7.5](#75-random-camp-a-camp-that-appears-only-sometimes)).

### 7.1 Layout

* **Left:** *Area* (search and pick), *Camp plan* (title, id, cr, save/load), *Place* tabs.
* **Centre:** the map. Top toolbar, then the canvas.
* **Right:** *Spawn groups*, *Events*, *Random camp*, *Plan objects* (selection details), *Stage*.

### 7.2 Step by step

1. **Pick an area.** Search by name or resref (e.g. `mantle`) and click it. The card shows size, tileset, interior/exterior,
   the area's `cr`, how many creatures/props exist, and the spawn groups it already has. Changing area discards the current plan (it asks first).
2. **Name the plan.** *Title* (e.g. "Wolf den in Mantle Clearing") — the *Plan id* is derived (`a-z 0-9 _`).
   *Re-staging a plan with the same id replaces its objects instead of duplicating them.*
   Set **Area cr** if the area has none (spawns/loot/XP need it; the card warns "no cr set").
3. **Place things** with the tabs under *Place*:
   * **Prefabs** — ready-made layouts (bandit camp, goblin camp, hunter camp, wagon camp, ruined camp, tents, small camp, graveyard,
     spider nest, ambush site). Click one, then click the map to stamp it. **R / Shift+R** rotates before you click.
     If the prefab contains spawn markers, a box lets you map each prefab group to a group number of this area
     (pick an unused one for a dedicated camp group). **Find open ground** jumps the view to the nearest place where the whole footprint is walkable
     (needs the NWN install) and offers a *Stamp "…" here* button.
   * **Props** — every placeable TFN already uses (searchable; filters: decor, container, light, usable, respawning).
     Containers roll TFN loot (`treas_*`) — place them deliberately. `plx_` props respawn on every area refresh.
   * **Creatures** — TFN's creatures plus base-game ones TFN areas already place (filters: monster, npc, other, henchman, base-game).
     A hand-placed creature is recorded by `area_init` and **respawns at that exact spot every refresh**. For roaming groups use *Spawns*.
   * **Spawns** — invisible **spawn markers** for group 1–9. `area_init` reads each marker's position and removes it; the group's
     encounter is spread over all its markers (more markers = better spread).
   * **Waypoints** — **event waypoints** (`_wp_event`). On each refresh there is an `event_chance`% roll; on success one event script runs with a random event waypoint as the acting object.
4. **Spawn groups** (right). *+ group* adds a row: choose the encounter blueprint (`.ute`), the number of **spawns** and an optional
   spawn **script**. *+ new encounter…* opens a small encounter editor and adds the new `.ute` to the same change set.
   Markers in the plan whose group has no encounter are flagged ("nothing will spawn there").
5. **Events** (right). *+ event* adds script names (`event1…event9` on the area); set **event_chance %**.
6. **Adjust.** Click an object (Select tool, **Esc**) to see it under *Plan objects*: x, y, z (leave empty for the exact walkmesh height),
   facing, ⟲/⟳ 15°, duplicate, delete, group (markers), tag. Prefab stamps can be selected/rotated/deleted as a whole ("select all", "⟳ stamp", "delete stamp").
7. **Save the plan** (*Save plan*) any time → `specs/camps/<id>.json`; the dropdown reloads saved plans. Your own layout can become a
   prefab: **Save as prefab…** → `prefabs/<id>.json`.
8. **Stage changes** (right, bottom). The button is disabled while something blocking is missing (no area, no id, a group without
   encounter, nothing placed). Warnings (no cr, markers without encounter) do not block. After staging, **Review & apply →** opens the change set.

### 7.3 Map controls

| Action | How |
|---|---|
| Zoom | mouse wheel / two-finger scroll |
| Pan | **hold Space and drag** (works on trackpads), or right-button drag |
| Fit area to view | **F** or the *Fit* button |
| Select / cancel a tool | **Esc** |
| Rotate placement (or selection) ±15° | **R** / **Shift+R** (or the ⟲ ⟳ buttons) |
| Nudge selection | arrow keys 0.5 m; with **Shift** 2 m |
| Delete selection | **Delete** or **Backspace** |
| Undo | **Ctrl+Z** (⌘Z on macOS) |
| Place without grid snap | hold **Alt** (**⌥** on macOS) |
| Move / turn / delete a camp spot | Select tool: click a spot (a teal numbered circle) and drag it; **R** / **Shift+R** turns it; **Delete** removes it |
| Layers | checkboxes: tiles, walkable, grid, existing objects, camp spots, labels; *snap 0.5 m* |

Coordinates are metres: **x** east, **y** north, origin at the south-west corner, 10 m per tile. **Facing** is in degrees, 0 = east, 90 = north.
Colours: creatures red, props blue, waypoints green, doors orange, triggers purple, spawn markers magenta, random-camp spots teal.

### 7.4 Heights and walkability

With the NWN install available, every new object gets its **exact Z** from the tile walkmesh (calibrated: 99 % of TFN's existing objects match
within 0.35 m), the **walkable** layer is shown, and creatures, spawn markers and waypoints placed on non-walkable ground get a **red ring and a warning**.
Props on non-walkable surfaces (rocks, trees, walls) are allowed and only noted. Without the install, Z is guessed from neighbours — check heights in the toolset.

### 7.5 Random camp: a camp that appears only sometimes

Everything you place normally is **permanent**: it is written into the area and is there after every refresh. A **random camp** is different. The props and
creatures of the plan become a *template*, and the area builds that template **only now and then, when it refreshes, at one of the spots you chose** —
each spot with its own direction, so tents, fire and guards line up with the terrain wherever the camp turns up. Nothing of the camp is stored in the area file.

**How it works in the game.** When an area refreshes TFN makes one roll against the area's `event_chance` (most TFN areas use 20 %; 50 % when none is set).
If the roll succeeds, **one** of the area's event scripts (`event1…event9`) runs. The studio writes such an event script for your camp, so the camp shares that roll
with the area's other events (for example wandering adventurers): *chance the camp appears = `event_chance` × the camp's event slots ÷ all event slots.*
The camp is removed again with the rest of the area's spawns at the next refresh.

1. **Build the camp as usual** — place the props and creatures (or stamp a prefab) where you like; this is only the *design*. Spawn markers and waypoints you place
   stay permanent, ordinary area objects.
2. In **Random camp** (right) tick **Build this camp only sometimes, at a random spot**.
3. **Add spots.** Press **+ Spot (click map)** and click the map: the whole camp follows the cursor, turned by the toolbar *rotation* (**R** rotates it). Each spot is a numbered teal
   circle whose arrow shows the way the camp's front faces, with the camp drawn half-transparent at every spot (red marks warn about objects on non-walkable ground or outside the area).
   Drag a spot to move it, type exact **x / y / °** in the list, turn it with ⟲ ⟳ (45°). **Suggest** adds spots on open ground where the *whole* camp fits and nothing existing is in the way (needs the NWN install);
   press it again for different spots. **Import markers** takes waypoints that are already in the area: its `_wp_event` event waypoints and any waypoint whose tag starts with `camp_spot` —
   place those in the toolset where you want the camp, and rotate them the way the camp should face (a waypoint's facing becomes the spot's direction).
4. **Direction.** Design the camp with its "front" pointing **north (90°)**. The **pivot** (default: the centre of the camp; *Set…* moves it) is the point that lands on each spot; a spot turns the camp about the pivot
   by *(spot direction − 90°)*. Facing is in degrees, 0 = east, 90 = north.
5. **Also build it where it is designed now** adds the design location as one more possible place. With no spots at all the design location is the only place.
6. **Replaces** (optional) — choose one of the area's spawn groups (`random1…9`). While the camp stands, that group's creatures are removed as they spawn: all of them, or only those within *m* metres of the camp.
   When the camp is not built the group spawns as usual, and a spawn script the group already had keeps running. One camp can replace a group; two camps cannot replace the same one.
7. **Event slots** (1–4): a camp that takes more slots is picked more often (TFN itself lists `eve_adventure` twice in some areas for the same reason).
8. Look at the **info card**: it shows the chance per refresh (and per spot), which event slots are used, which other events share the roll, a `_wp_event` waypoint the studio will add when the area has none
   (events only run from one), and every problem per spot. Errors (a spot that pushes the camp out of the area) block *Stage changes*; warnings do not.
9. **Stage**, review, **Apply**, build the module and restart the server like any other change.

**What gets written.** `src/nss/eve_<plan id>.nss` (the event script; the name can be changed — at most 16 characters) and, when it replaces a group, `src/nss/spw_<…>.nss` (the gate script); the area's
`eventN` variables and, for a replaced group, its `randomN_spawn_script`. Both scripts begin with a header comment (`// tfn-studio camp event: plan <id>`). **Only scripts with that header are ever overwritten** —
a name that belongs to TFN or to another plan is refused. Staging the same plan again replaces the scripts; turning *random camp* off removes the wiring again and the props and creatures become
permanent area objects like any other plan.

**Good to know.**

* Every spot is checked when you stage: heights come from the tile walkmesh object by object, creatures on non-walkable ground and objects too close to existing ones give warnings, a camp that would reach outside the area is an error.
  Without the NWN install the camp stands at one guessed height per spot and the card says so.
* The camp's props behave like toolset-placed ones: containers, trapped props and props with an inventory become static decor, `treas_*` props roll TFN loot, `plx_` props stay as they are; creatures with a quest are registered as quest NPCs.
* TFN counts an area's events from `event1` up to the **first empty slot**, so the studio keeps the slots contiguous (and the Changes page warns about an existing gap that hides events).
  An area can have at most nine event slots; a camp can have at most 24 spots.
* Adding a camp to an area that already has events makes those events a little rarer, because they share the roll — the info card lists them. If the area has no `event_chance`, TFN uses 50 % for *all* events: set it under **Events**.
* To see the camp in game quickly, stage it with **event_chance** 100 and **Event slots** 4 while testing, then put the real values back and stage again.


---

## 8. Spawn Designer

`/spawns` — author **encounter blueprints** (`.ute`). In TFN a `.ute` is the data container behind a random spawn group
(`random1…random9` on an area): a pool of common creatures, an optional pool of *unique* creatures, a difficulty and an optional rare spawn.

* **Left:** all existing blueprints (search; creature count and number of areas using each), **+ New encounter**, and your saved drafts.
* **Editor (centre):**
  * **Resref** (≤16 chars, `a-z 0-9 _`; the badge says *new* / *editing existing* / *invalid*) and optional **Name**.
  * **Difficulty (unique chance):** Very easy 5 % · Easy 10 % · Normal 15 % · Hard 20 % · Impossible 25 % — the chance that a spawn is taken from the unique pool.
  * **Rare creature (15 % per refresh):** optional creature resref.
  * **Creatures:** add from the searchable list; each is **common** or **unique (single spawn)**.
  * **Preview:** pick a *Group spawns* number and optionally an area to *Check CR against*. You see the expected number of each creature per refresh,
    the spawn range, the average common CR, and warnings/advice (for example CR outliers for that area).
* **Right:** *Used by* — areas/groups/spawn counts/CR where this blueprint is used (links open the Camp Builder on that area). Editing an
  existing blueprint rewrites its creature list, difficulty and rare entry; other fields are kept.
* **Stage changes** validates and creates the change set; **Save draft** keeps the form in `specs/utes/`.

---

## 9. Quest Builder

`/quests` — multi-stage quests built the way TFN's `inc_quest.nss` expects: a journal entry per stage, and **variables** on NPCs, creatures, items and areas that advance the stage.

### 9.1 Layout

* **Left:** **+ New quest**, *Your drafts* (saved specs), and *Existing TFN quests* (search; click for a read-only view of how a real quest is wired).
* **Centre:** *basics*, *Quest giver*, *Stages*.
* **Right:** *Mechanism plan* (live summary: stage → mechanism → reward), **Stage changes**, **Save draft**.

### 9.2 Step by step

1. **Basics.** *Journal tag* `q_…` for a quest or `b_…` for a bounty (bounties can be redone every 6 h); at most 27 characters. The chip says
   *ok*, *invalid*, or *tag used by a TFN quest*. *Quest name*, *Journal priority* 0–4.
2. **Quest giver.**
   * *Create a new NPC (clone an existing one)*: new resref, display name, **Clone appearance & stats from** (pick from the list), a greeting for when no quest applies.
   * *Use an existing NPC*: the quest variables are added to the blueprint **and every placed instance**, and the quest nodes are merged
     into the NPC's existing conversation (or a new dialog is created).
   * Optionally **place** the NPC in an area (*Pick on map…* shows a map; spots near existing creatures are known to be walkable).
3. **Stages.** Stage 1 is always the giver's offer (offer text, accept/decline replies and NPC answers). Add more with the buttons:
   * **+ Talk to an NPC** — the player returns to the giver (or another existing NPC) and the quest advances.
   * **+ Kill a creature** — a *new named boss* (clone of a creature, optionally placed in an area) or an *existing creature blueprint*; tick *boss* for better loot / XP / treasure-map chance.
   * **+ Pick up an item** — a new quest item (resref, name, description) dropped by a chosen creature.
   * **+ Enter an area** — advances when the player enters an area (a tiny generic `enter_quest_adv` script is generated for you).

   Every stage has its **journal text**. Reorder with ↑ ↓, **Remove** where allowed. The **last stage completes the quest** and is where the **reward** goes:
   *XP tier* (1–4 = 50/100/200/400 base XP), *for level*, *gold*, *item*.
4. **Check the Mechanism plan** (right) — it lists, per stage, which NPC/creature/item/area carries which variable.
5. **Save draft** any time (`specs/quests/<tag>.json`). **Stage changes** generates the journal category (appended to `src/jrl/module.jrl.json`),
   dialog, blueprints, items, variables and placements, then validates everything.

Existing NPC dialogs are never overwritten: the quest nodes are merged in and tagged so re-staging replaces them cleanly.

### 9.3 Script style: Modern or Older (top-right button)

The button at the top right of the Quest Builder page — **Quest scripts: Modern ⇄** / **Quest scripts: Older ⇄** — chooses how the quest's *conversation* is wired.
Click it to switch; the choice is saved with the draft (`"script_style": "modern"` or `"legacy"` in the spec).

* **Modern** (the default for every *new* quest). One generic script does each kind of check, and the conversation hands it a small note — a **parameter** —
  saying which quest slot to look at. "Is the player currently at this stage?" is always `dlg_q_chk_at` with the note `target = 3`, whatever the slot.
  There is no slot limit below the game's own (19), and no pile of near-identical scripts.
* **Older.** What the studio did before: it calls TFN's *slot-numbered* scripts, one per slot (`dlg_q_chk_atc1`, `dlg_q_chk_atc2`, … up to 9; above 9 it falls back to
  `dlg_q_chk_multi`). Use it only when you want a new quest to look exactly like TFN's older ones.
* **Your existing quests are never converted.** A saved draft that has no `script_style` (everything made before this feature, including the shipped example) opens as **Older**
  and produces exactly the same output as before. Switching a draft's style and staging it again simply regenerates its dialog nodes in the other style.

#### What is a "parameter"?

A dialog line can run a script, and the dialog editor lets you attach little *Key = Value* notes to that line. The script reads them while it runs.
So instead of writing a new script for every quest slot, you write one script and say, on each dialog line, **which slot** (`target = 3`) it should use.
Nothing about the quest changes for the player; only the bookkeeping behind the conversation is simpler.

#### How a quest conversation works (plain English)

Every quest NPC carries **slots**: little labelled notes on the NPC named `quest1`, `quest2`, … Each note says "I am the person who moves quest *Wolf Hunt*
to stage 05" (stored as `05_q_wolf_hunt`), and may carry a reward. The conversation then follows the same story every time you talk to the NPC:

1. **You speak to the NPC.** The game looks down the dialog's *starting list* from the top and uses the **first line whose condition says yes**.
2. **"Can I hand you the next stage?"** (`dlg_q_chk_eli`, *target = slot*). It looks at the slot's note and asks: is the player *one stage behind* the stage this slot
   advances to, and have all required earlier stages been done? If yes, this is a turn-in line ("Splendid, here is your pay"). The studio puts the **latest** stages first
   so a player who finished everything is not offered the beginning again.
3. **"Are you in the middle of this stage?"** (`dlg_q_chk_at`, *target = slot* — the Older style uses `dlg_q_chk_atcN`). If the player is exactly at the stage this slot
   handed out, the NPC gives a **reminder** ("Have you finished yet?") — or a **farewell** if it was the last stage.
4. **"Is this a brand-new player?"** The stage-1 offer uses the same "can I hand you the next stage" check, so only players who haven't started see the offer.
5. **Nobody matched?** A new NPC falls back to its plain greeting.
6. **The player picks a reply.** When a line that *advances* is spoken (accepting the offer, or the turn-in text), it runs `dlg_q_adv` with *target = slot*.
   That script re-checks the rules, moves the journal to the new stage, and gives the slot's reward (XP, gold, item).
7. **Other mechanisms** (kill, pick up, enter an area) use the very same slot notes, but placed on the creature, item or area instead of the NPC;
   no dialog is needed for those.

In short: *the notes on the object say what a stage is; the parameter on each dialog line says which note to read; three generic scripts do the work.*

| Question the dialog asks | Modern | Older |
|---|---|---|
| Can the player be handed the next stage? | `dlg_q_chk_eli` + `target=K` | same |
| Advance the quest now | `dlg_q_adv` + `target=K` | same |
| Is the player currently at this stage? | **`dlg_q_chk_at` + `target=K`** (any slot) | `dlg_q_chk_atcK` (slots 1–9), else `dlg_q_chk_multi` |

The only script the studio adds to TFN for this is `dlg_q_chk_at` (shown on the Changes page the first time a Modern quest is staged, and skipped if it is already there).

### 9.4 Limits

| Limit | Value | Notes |
|---|---|---|
| Quests in the module | no fixed cap | each quest is one journal category |
| Quest slots on one NPC, item or area | **19** (`quest1` … `quest19`) | TFN's `HIGHEST_QUEST_COUNT = 20`; `area_init.nss` repeats the number. The studio uses the next free slot automatically |
| Prerequisites per stage | 19 | same constant |
| Stages per quest | 99 | two-digit stage prefix (`NN_tag`) |
| Quest tag length | 27 characters | `q_…` or `b_…` |

Raising the slot limit would mean editing TFN's `inc_quest.nss` and the hard-coded number in `area_init.nss`; the studio does not do this for you.

### 9.5 Converting older quests to parameters (optional, never automatic)

TFN's older dialogs (86 of them today) call numbered scripts such as `dlg_q_adv3`. A command can rewrite them to the modern form (`dlg_q_adv` + `target=3`).
**It only ever runs when you ask**, and it only *stages* a change set — nothing in TFN changes until you review and apply it, and **Undo** restores it.

```
./bin/tfn-studio quest convert --check            # dry run: lists what would change, writes nothing
./bin/tfn-studio quest convert --dialog aarin     # stage ONE dialog first and look at its diff
./bin/tfn-studio quest convert                    # stage them all
```

What keeps it safe:

* It changes only the script name and its parameter list on a dialog line — never text, links or order.
* A line that **already has parameters** (for example an area-effect advance, or a check with an `npc_tag`) is left alone and listed.
* Before converting, it confirms that each numbered script really is "the generic script with the slot filled in"; any family that is not is left untouched.
* Per dialog it checks that the list of (script, slot) calls is identical before and after, and that the file round-trips byte for byte; otherwise the dialog is skipped.
* The numbered scripts are **not deleted**; other content may still call them.

Risk: low-to-moderate. The rewrite is mechanical and checked, but only a playthrough proves a quest still behaves. Convert one NPC, restart, test its quests, then do the rest.

---

## 10. Changes: review, apply, undo

`/changes` — every staged set, newest first, with *staged* or *applied* chips.

For the selected set you see:

* **Files** — *new* / *edit*, `+added −removed` lines and a note; click a file for its coloured diff.
* **Notes** — important facts (e.g. "Restart the server after applying…").
* **Validation** — runs automatically and with **Re-validate**:
  1. canonical JSON formatting (byte-identical to what `nwn_gff` writes, so diffs only show real changes);
  2. structure and cross-reference checks (blueprints exist, group markers exist, `cr` set, quest tag length and journal entries, dialog graph integrity, scripts exist, …);
  3. a real **`nwn_gff` JSON → GFF → JSON round trip** (proves the toolset/engine can load the files);
  4. **`nwnsc` compile** of every generated script (with a time limit — nwnsc can hang on some syntax errors).

  Messages are *error* (blocks Apply unless forced), *warning*, or *info* (including "SKIP: tool not found"). Problems that were **already in a file before your change**
  are listed as *(pre-existing)* warnings and do not block.
* **Apply to TFN…** → confirm. Apply **refuses** files that have uncommitted git changes (you may choose **Apply anyway**) and files that changed since you staged
  (stage again). It writes only inside `<TFN>/src/` and keeps an **undo record**.
* **Undo apply** restores the files exactly as they were before.
* **Discard** deletes the staged set (applied files are not touched).

---

## 11. After Apply: build, restart, test

Apply only changes source files. To see the result in game, build and run the module as usual. TFN documents these routes
(see TFN's `docs/TEST_PLAN.md`, `CHANGES_AND_TEST_PLAN.md`, `BUGFIX_TESTING.md`):

* **Pack only (routine rebuild; does not touch databases)** — nasher from TFN's bundled tools, e.g. on Linux:
  ```bash
  cd ~/git/the-frozen-north
  ./tools/linux/nasher/nasher pack -y \
    --erfUtil:"$PWD/tools/linux/neverwinter/nwn_erf" --gffUtil:"$PWD/tools/linux/neverwinter/nwn_gff" \
    --tlkUtil:"$PWD/tools/linux/neverwinter/nwn_tlk" --nssCompiler:"$PWD/tools/linux/nwnsc/nwnsc" \
    --nssFlags:"-lowqey -i $PWD/.build/include-shims -i $PWD/nwn-base-scripts"
  ```
  On a Mac use `tools/macos_arm64/…` (compare the flags in `macos_nasher_install.sh`; macOS file names are case-insensitive, so the include-shims folder is not needed).
  The result is `.build/modules/TFN.mod`.
* **Full install script** (`linux_nasher_install.sh` / `macos_nasher_install.sh` / `win_nasher_install.bat`) additionally **wipes and reseeds the campaign databases** and deletes
  `.build/modules` — don't use it for a routine rebuild.
* **swamp** users: from `~/git` (not inside the TFN repo) `swamp model method run thefrozennorth-build build`.
* **Restart the dev server** (`./linux_run_server_dev.sh` / `./macos_run_server_dev.sh` / the `win_` equivalent) or deploy the new `TFN.mod` to the server you test on.

In game:

* **Camps/spawns:** the area's spawn refresh creates the group; hand-placed creatures and `plx_` props reappear at their spots each refresh. See `SPAWN_SYSTEM.md` for timing, `cr`, markers and events.
* **Quests:** talk to the giver, check the journal after each stage, finish the quest. Quest NPCs are registered at module load by `area_init`.
* Check **object heights** if the NWN install was not available when you staged (Z was inferred from neighbours).

---

## 12. Command line reference

Everything the web pages do is also available (and scriptable) from the terminal. `--tfn PATH` can be placed anywhere on the line.

| Command | What it does |
|---|---|
| `doctor [--port N]` | environment check (works even if the TFN checkout cannot be found) |
| `manual [--open]` | print where `MANUAL.html` is (needs no checkout or tools); `--open` shows it in your browser |
| `serve [--port N] [--host H] [--open]` | start the web UI |
| `status` | checkout, branch, tools, counts, staged changes (JSON) |
| `index` | build/refresh the content indexes |
| `areas [--filter TEXT]` / `area RESREF [--objects]` | list areas / show one area (spawn groups, cr, optionally every object) |
| `prefabs` | list camp prefabs |
| `camp stamp PLAN PREFAB --x X --y Y [--area A] [--title T] [--rotation DEG] [--cr N] [--group-map 1=4,2=5]` | create `specs/camps/PLAN.json` from a prefab |
| `camp stamp PLAN PREFAB … --random-camp [--spot X,Y[,DEG] …] [--include-here] [--weight N] [--replaces-group N] [--replace-radius M] [--event-chance PCT] [--script NAME]` | stamp the prefab as a **random camp**: built at one of the `--spot` places (repeatable) when the area refreshes |
| `camp spots PLAN [--count N] [--seed S] [--add]` | suggest open spots for a plan's random camp (needs the NWN install); `--add` appends them to the plan file |
| `camp stage SPEC [--no-validate]` | build a change set from a camp plan (`SPEC` = name in `specs/camps/` or a path) |
| `ute stage SPEC [--no-validate]` | build a change set from an encounter spec (`specs/utes/`) |
| `quest describe SPEC` | print the stage → mechanism plan |
| `quest stage SPEC [--no-validate]` | build a change set from a quest spec (`specs/quests/TAG.json`) |
| `quest convert [--check] [--dialog RESREF …] [--no-validate]` | convert older numbered quest scripts in dialogs to parameters (§9.5); `--check` = dry run, otherwise stages a change set |
| `changes list` / `show ID [--diff]` / `validate ID` | inspect staged sets |
| `changes apply ID [--allow-dirty] [--force]` | write a set into TFN (`--allow-dirty`: even if files have uncommitted changes; `--force`: despite validation errors/conflicts) |
| `changes undo ID [--force]` / `changes discard ID` | restore the files / delete the staged set |
| global `--json` | machine-readable output where supported |

Typical scripted run:

```bash
./bin/tfn-studio camp stamp wolf_den hunter_camp --area mantle --x 70 --y 70 --rotation 30 --cr 4 --group-map 1=4
./bin/tfn-studio camp stage wolf_den
./bin/tfn-studio changes show <id> --diff | less
./bin/tfn-studio changes apply <id>
```

A random camp from the terminal (the camp appears at one of three places in `mantle`, turned the way each `X,Y,DEGREES` says — use your own spots, or let `camp spots` find them):

```bash
./bin/tfn-studio camp stamp hunters hunter_camp --area mantle --x 70 --y 70 --random-camp --spot 14.5,75.5,90 --spot 134.5,64.5,270 --spot 91.5,128.5,0
./bin/tfn-studio camp spots hunters --count 3 --add        # or let the studio find open ground for more spots
./bin/tfn-studio camp stage hunters
```

**Specs** are plain JSON, declarative and re-appliable. Shipped examples: `specs/camps/example_bandit_camp.json`, `specs/camps/example_random_camp.json`, `specs/quests/q_example_wolves.json`.
A camp spec lists `objects` (`kind`: placeable / creature / marker / waypoint, `resref`, `x`, `y`, `facing`, optional `z`, `tag`, `group`), `groups` (`n`, `ute`, `spawns`, `script`),
`events`, `event_chance`, `cr`, `new_utes`, and optionally `camp_event` (`script`, `weight`, `origin` {x, y, facing}, `spots` [{x, y, facing}], `include_origin`, `replaces_group`, `replace_radius`)
to make its placeables and creatures a random camp. A quest spec lists `tag`, `name`, `priority`, `giver`, `script_style` (`modern` or `legacy`; absent = legacy, see §9.3), and `stages` (each with `via`: talk / kill / pickup / explore).

---

## 13. Where things live

| Path | Contents |
|---|---|
| `<studio>/bin/tfn-studio` | the launcher |
| `<studio>/MANUAL.md`, `MANUAL.html` | this manual: the Markdown source and the single-file browser version (after editing the Markdown run `python3 scripts/build_manual.py` to regenerate the HTML) |
| `<studio>/specs/{camps,quests,utes}/` | your saved plans/drafts (commit these) |
| `<studio>/prefabs/` | camp prefabs (10 shipped; *Save as prefab…* adds more) |
| `<studio>/.studio/changes/<id>/` | staged change sets |
| `<studio>/.studio/applied/<id>/` | undo records of applied sets |
| `<studio>/.studio/cache/`, `.studio/gamedata/` | content index cache; tilesets/walkmeshes extracted from the NWN install (all safe to delete) |
| `<TFN>/src/**` | **only here** does Apply write: `git` (area objects/variables), `utc`, `utp`, `ute`, `uti`, `dlg`, `jrl/module.jrl.json`, `nss` (the small generic scripts and the random-camp event/gate scripts) |

What each builder generates:

* **Camps/spawns:** props → `Placeable List` instances; creatures → `Creature List` instances (the blueprint's variables are copied, as the toolset does);
  spawn markers → creatures with resref `random1…random9`; area variables `randomN`, `randomN_spawns`, `randomN_spawn_script`, `cr`, `eventN`, `event_chance`;
  event waypoints (`_wp_event`); new encounters → `src/ute/<resref>.ute.json`. Every generated instance carries the local variable `studio_plan = <plan id>`.
* **Random camps:** the props and creatures are *not* written to the area; instead `src/nss/eve_<id>.nss` (builds the camp at a random spot), optionally `src/nss/spw_<…>.nss`
  (removes a replaced spawn group's creatures while the camp stands), the area's `eventN` / `randomN_spawn_script` variables, and a `_wp_event` waypoint when the area has none.
* **Quests:** journal category in `src/jrl/module.jrl.json`; giver blueprint (cloned, `Plot=1`) and dialog (TFN's generic `dlg_q_chk_eli` / `dlg_q_adv` scripts plus `dlg_q_chk_at` — or `dlg_q_chk_atcN` in the Older style, §9.3 — or merged into an existing dialog);
  `questK = "NN_<tag>"` plus `questK_reward_*` on the NPC (blueprint **and** placed instances), `quest_kill` on kill targets, a `quest`-tagged item for pickups, `questK` + `enter_script` on explore areas.

---

## 14. Safety model and good habits

* Generators write only to **staging**. *Apply* is the only step that touches TFN, and only inside `<TFN>/src/`.
* Apply refuses files with **uncommitted git changes** and files **changed since staging**; every Apply keeps an **undo record**.
* Names are validated (`a-z 0-9 _`, ≤16 chars for new resrefs). Existing dialogs are merged, not overwritten.
* The server listens on **127.0.0.1 only**, checks the `Host` header, requires a per-run token and same-origin `Origin` on every change request, and sends no CORS headers.
  It has **no login** — never bind it to a LAN address or forward its port.
* Generated scripts (random camps) carry a header naming their plan, and **only scripts with that header are ever overwritten** — TFN's own scripts, scripts of other plans and base-game script names are refused.
* The studio **never commits, pushes or builds** anything.

Good habits: work on a **git branch** in TFN; keep TFN's working tree clean before Apply (so the dirty-guard stays useful); **commit after each Apply** so each studio change is one
reviewable commit; keep your `specs/` and `prefabs/` in the studio repo; rebuild and restart before judging a change in game.

---

## 15. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `error: … is not a TFN checkout` (older versions: `… does not look like a TFN checkout (missing src/git or src/are)`) | The path the studio used has no `src/git` and `src/are`. It says where the path came from (`--tfn`, `TFN_ROOT` or the default `~/git/the-frozen-north`) and suggests nearby checkouts. Fix: `./bin/tfn-studio --tfn "/real/path" …` or `export TFN_ROOT=…` (see [Quick start](#1-quick-start)). Check with `ls /real/path/src/are \| head -3`. `./bin/tfn-studio doctor` shows everything at once. |
| `permission denied: ./bin/tfn-studio` | `chmod +x bin/tfn-studio`, or run `python3 bin/tfn-studio …`. |
| `python3: command not found` / developer-tools dialog | `xcode-select --install` or `brew install python`. |
| `tfn-studio needs Python 3.9 or newer` | Install a newer Python and start with that: `python3.12 bin/tfn-studio serve`. |
| `TypeError: unsupported operand type(s) for \|` on Python 3.9 | You have a copy from before 2026-10-02. Update the studio ([section 17](#17-updating-moving-and-removing)). |
| `cannot listen on 127.0.0.1:8350 … Is another studio already running?` | Stop the other one (Ctrl+C in its terminal) or use `--port 8351`. |
| Browser shows *forbidden* / the page does not load | Use exactly `http://127.0.0.1:PORT/` (or `localhost`). Host names, LAN addresses and tunnels are refused on purpose. |
| Dashboard: tool *missing*; validation says `SKIP: … not found` | See [3.5](#35-tools-nwn_gff-nwnsc-nwn_resman_extract). Check `./bin/tfn-studio doctor`; set `NWN_TOOLS` or `NWN_GFF` / `NWNSC`. |
| `SKIP: … cannot run on this machine` | The tool is for another OS/CPU (e.g. Linux or Apple-silicon binary on an Intel Mac). Point `NWN_GFF` / `NWNSC` at a build for your machine. |
| macOS: *"nwn_gff" cannot be opened because the developer cannot be verified* | `xattr -dr com.apple.quarantine <TFN>/tools` and `chmod +x <TFN>/tools/macos_arm64/*/*`. |
| Dashboard: *walkmesh unavailable*; no walkable overlay | NWN install not found. `export NWN_ROOT="…/Neverwinter Nights"` (the folder containing `data/nwn_base.key`) and make sure `nwn_resman_extract` is found. Delete `.studio/gamedata/` if you changed installs. |
| Index stuck on *building…* or shows an error | Press **Refresh index**; if it persists delete `.studio/cache/` and restart. Check the terminal for the Python error. |
| Lists (areas, creatures, props) are empty | The index is still building, or the checkout is incomplete (`src/utc`, `src/utp` missing → `doctor` warns). |
| Apply refused: *uncommitted changes* | Commit or stash your changes in those TFN files, or choose **Apply anyway** if you accept mixing them with generated edits. |
| Apply refused: *changed since staging* | A file was edited after you staged. Stage again. |
| Validation *error*: round trip / `TemplateResRef does not match file name` / missing blueprint | Read the message — it names the file. Usually a typo in a resref or a blueprint that is not in TFN. Fix in the builder and stage again (re-staging replaces the old set's output). |
| `compiler timed out` | nwnsc hangs on some syntax errors; the studio gives up after 30 s. Check the generated script for typos (only the tiny generic enter-script is generated). |
| Nothing changed in game | The module was not rebuilt/redeployed, or the server was not restarted (`area_init` runs at module load). Spawns also need a `cr` on the area. |
| Random camp never shows up | It is a *chance* (see the info card: often 5 % or less per refresh). Events also need a `_wp_event` waypoint in the area and the area's event list must have no gap (the Changes page warns about both). Test with `event_chance` 100 and 4 event slots, then restore them. |
| Random camp: *not enough free event slots* | The area already uses all nine `eventN` slots. Remove or merge one of its events, or lower the camp's *Event slots*. |
| Random camp: *… already exists and belongs to another tool or plan* | The script name is taken by a script the studio did not generate for this plan. Pick another name under **Event script**. |
| Random camp: *objects would fall outside the area* | A spot is too close to the edge for the camp's size (or turned so that it sticks out). Move the spot inwards or use **Suggest**. |
| Camp objects float or sink | Heights were inferred (no NWN install). Install/point `NWN_ROOT`, restage; or fix heights in the toolset. |
| Quest giver does not react | Quest NPCs must exist at module load; restart the server. Existing NPC? Make sure its conversation was merged (see the file list on the Changes page). |
| "Staged, but validation found errors" toast | The set exists but has errors; open **Changes**, read them, fix, stage again. |

If something else goes wrong, run `./bin/tfn-studio doctor` and look at the terminal where `serve` is running — Python errors appear there.

---

## 16. Reference

**Environment variables**

| Variable | Meaning |
|---|---|
| `TFN_ROOT` | TFN checkout (same as `--tfn`; the flag wins) |
| `NWN_ROOT` | NWN:EE install folder (contains `data/`); auto-detected at the usual places |
| `NWN_USER` | NWN user folder (optional; only passed to the extractor if it exists) |
| `NWN_TOOLS` | extra folder that contains `<platform>/neverwinter`, `nwnsc`, `nasher` |
| `NWN_GFF`, `NWNSC`, `NASHER`, `NWN_RESMAN_EXTRACT` | exact path to one program (wins over all lookups) |

**Ports and addresses:** web UI `http://127.0.0.1:8350/` (`--port`). Nothing else is opened.

**Limits:** creature/prop blueprints must exist in TFN (`src/utc`, `src/utp`) or already be placed somewhere in a TFN area (the studio then reuses a real instance;
this covers ~1,100 base-game props and ~470 base-game creatures). Base-game blueprints TFN never uses are not available. Quest targets/NPCs can only be cloned from `src/utc`
blueprints. Creature instances keep the blueprint's reference-form equipment — verify one plot NPC in game.

**Glossary**

| Term | Meaning |
|---|---|
| resref | resource name (≤16 chars, lowercase `a-z 0-9 _`) of a blueprint or script |
| `.ute` | encounter blueprint: the creature pools behind a random spawn group |
| event script | one of the area's `event1…event9` scripts; one is picked at random when an area refreshes and an `event_chance` roll succeeds |
| random camp | a camp built by a generated event script at one of several spots, only sometimes (see [7.5](#75-random-camp-a-camp-that-appears-only-sometimes)) |
| spot / pivot | a place (x, y) and a direction where a random camp may appear / the point of the camp that is moved onto the spot and turned about |
| spawn marker | creature with resref `random1…random9`; marks where group *N* may spawn; removed by `area_init` |
| `cr` | area variable: challenge rating used by spawns, loot and XP |
| change set | one staged bundle of file changes (new/edit) with notes and validation |
| plan id | name of a camp plan; re-staging the same id replaces its generated objects |
| nasher | the tool that packs `src/` into `TFN.mod` |

---

## 17. Updating, moving and removing

* **Update:** replace the studio folder's code with the newer version (same methods as [3.2](#32-getting-the-studio-onto-the-machine)), keeping your `specs/`, `prefabs/` and `.studio/`
  if you want to keep drafts and staged sets. With git: `git pull`. Then `./bin/tfn-studio doctor`.
* **Move to another computer:** copy the folder (without `.studio/` unless you need the staged sets) and install the TFN checkout there; run `doctor`.
* **Remove:** delete the studio folder. Nothing is installed elsewhere; TFN is never modified except by Apply (undo any applied set from its Changes page first, or use `git` in TFN).

---

*Cheat sheet:* `./bin/tfn-studio doctor` → `./bin/tfn-studio --tfn PATH serve --open` → build → **Stage** → **Changes** → **Apply** → build module → restart server → test.

---

## 18. Using the studio with any module (nwn-manager)

The studio is part of **nwn-manager** (`studio/` in that repository). Besides The Frozen North it works on **any module project that nwn-manager manages**,
including a brand-new one. The studio tells the two apart by itself:

| | Frozen North ("tfn" profile) | Any other module ("generic" profile) |
|---|---|---|
| Folder layout | `src/<type>/<resref>.<type>.json` (nasher, one folder per type) | nwn-manager project: everything side by side in `unpacked/` (flat) |
| Quest scripts | TFN's own (`inc_quest`, `dlg_q_*`, `ai_ondeath`, `area_init`) | the studio installs a small set of its own (below) |
| Quest Builder | all features, Older/Modern script style | all features, Modern style only |
| Camp Builder | plain and random camps | plain camps (props and fixed creatures) |
| Spawn Designer | yes | not shown (needs TFN's spawn engine) |
| Staging area, undo log | next to the studio (`studio/.studio/`) | inside the project (`.studio/`, git-ignored) |
| Your quest/camp drafts | `studio/specs/` | inside the project (`studio-specs/`, commit them) |

### 18.1 Quick start on a module project

```
cd ~/GIT/my_module                      # a project made by `nwn-manager init`
nwn-manager studio doctor               # checks the project, tools and NWN install
nwn-manager studio                      # the web UI for THIS project (http://127.0.0.1:8350)
```

Design a quest in **Quest Builder**, press **Stage changes**, review it on **Changes**, **Apply**, then `nwn-manager repack` to build the `.mod`.
Everything else in this manual (sections 5-11) applies unchanged; the studio finds the project from the folder you are in (the nearest `nasher.cfg`),
or from `--module PATH` / `$MODULE_ROOT`.

The same commands work without the web UI: `nwn-manager studio quest stage <tag>`, `studio changes list|show|apply|undo`, `studio setup`.

### 18.2 What the first quest installs

A module such as Frozen North already has the scripts quests need. A fresh module has none, so **the first quest you stage also stages the studio's quest runtime**
into the same change set (you can see it on the Changes page, and install it alone with `nwn-manager studio setup`; `setup --check` only reports):

| File (in `unpacked/`) | What it does, in plain words |
|---|---|
| `inc_quest.nss` | The quest "brain". Reads the notes on an NPC/creature/item/area (`quest1`, `quest2`, …), checks whether a player may take the next stage, records progress, and gives the reward. |
| `dlg_q_adv.nss`, `dlg_q_chk_eli.nss`, `dlg_q_chk_atp.nss`, `dlg_q_chk_at.nss` | Small dialog scripts. Each one is told **which slot** to look at through a dialog parameter (`target = 3`), so four scripts serve every quest (see 9.3). |
| `enter_quest_adv.nss` | Runs when a player enters an area; advances "enter an area" stages. The area's OnEnter script is set to it. |
| `qs_ondeath.nss` | Creature OnDeath script: credits a "kill" stage to the killer's whole party, then runs the standard death script. Set on kill targets whose death script is empty or the standard one. |
| `qs_acquire.nss` | Module OnAcquireItem script for "pick up an item" stages. The studio sets it in `module.ifo` when that slot is empty; otherwise it tells you what to add to your own script. |
| `qs_npc.utc.json`, `qs_questitem.uti.json` | Plain template NPC and item to clone quest NPCs and quest items from, so a module with no creatures yet can still make a quest giver. |

How a player's progress is kept: as a whole number on the player character named after the quest (so it is saved with the character), plus the normal journal entry.
Quest NPCs, kill targets, items and areas carry the same `questK = "NN_<tag>"` notes as in Frozen North, so everything in sections 9.1-9.4 holds
(19 slots per object, 99 stages per quest, tags up to 27 characters).

The XP rule of this runtime is *tier base (50/100/200/400) x level / 5, never less than the base*. Edit `AdvanceQuest` in `unpacked/inc_quest.nss` to change it.

The studio never overwrites a script of yours: if the module already has a script with one of these names that is not the studio's, the quest is refused
with a message that names it. Rename yours, or write the quest scripts by hand.

### 18.3 What is not available in a generic module

* **Spawn groups, markers and random camps** (Spawn Designer, the Random camp panel, encounter blueprints): they need Frozen North's own spawn engine
  (`area_init`). The studio refuses them with a clear message instead of writing files that would do nothing.
* **The Older script style and `quest convert`**: the numbered scripts exist only in Frozen North.
* **Repeatable bounties** (`b_` tags): the generic runtime treats them like other quests (finish once).
* **Base-game creatures as templates**: clone from your own module's creatures, or from the template NPC `qs_npc`. (Extracting base-game blueprints needs
  `nwn_resman_extract`, which is not bundled for macOS.)
* The runtime needs **NWN:EE** (it uses `GetScriptParam`).

### 18.4 Notes for nwn-manager users

* `nwn-manager init` now git-ignores `.studio/`. For an existing project add the line `/.studio/` to its `.gitignore` yourself.
* The studio uses the tools nwn-manager already bundles (`nwn_gff`, `nwnsc`, `nasher`, the base-game scripts); nothing extra to install.
* `nwn-manager studio` runs the studio from source with `python3`. A compiled `nwn-pytools` built before the studio existed does not know the command, so
  it is skipped for this subcommand until the binary is rebuilt (`build/nwn-pytools.spec` now bundles the studio).

