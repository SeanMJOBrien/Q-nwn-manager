---
name: nwn-logic-debug
description: Use this skill to survey an NWN:EE module's logic and hunt logic bugs — silent misbehavior where scripts compile and the game runs but something is wrong (an action never happens, a value stays 0, a unit won't stop, gold lands in the wrong vault, a trigger points at the wrong object). Trigger on "why isn't X working", "debug this", "find the bug", "survey the module", "trace this logic", "this used to work", or any report of behavior that contradicts the code's apparent intent. Pairs with module-explorer (the survey/analysis tool reference) and the project build tooling.
---

# NWN Logic-Bug Hunting

Logic bugs in an NWN module rarely announce themselves: NWScript has no
runtime exceptions surfaced to the player, `ExecuteScript` on a missing
resource is a **silent no-op**, and a mislabeled magic number compiles
perfectly. The work is turning "it doesn't do the thing" into a specific
`file:line` and a named cause. This skill is the method plus a catalog of the
bug classes that actually bite in these modules.

## Two modes

- **Survey** — build a map of what wires to what, before (or instead of) a
  specific bug. Inventory scripts, variables, tags, transitions, factions,
  and broken references so latent bugs surface on their own.
- **Debug** — chase one reported misbehavior to root cause.

They share tools; start with whichever the request calls for.

## Survey workflow

1. **Load and orient.** `load_module` (absolute path for repo modules) →
   `get_module_summary`. See the `module-explorer` skill for the full
   analysis-tool set; the high-value ones for surveying wiring:
   - `validate_module` / `find_orphans` — dangling script/dialog/item/door
     references across the whole module. Run this first; broken refs are
     bugs-in-waiting.
   - `get_dependency_graph`, `list_script_references`, `find_variable_usage`,
     `find_strref_usage`, `find_dialog_scripts` — what touches a script,
     local var, or STRREF **before** you reason about changing it.
   - `search_by_tag` / duplicate-tag detection — `GetObjectByTag` hitting the
     wrong object is a classic silent bug (see bug-patterns §5).
   - `check_area_connectivity`, `visualize_area` — transition/pathing logic.
2. **Mine the wiki module-index.** If the project uses `nwn-manager`, its
   generated `module-index/*.json` findings (duplicate_destination_tags,
   area_tag_conflicts, cross_faction_creatures, creature_tag_conflicts,
   faction_bp_instance_discrepancies, duplicate_conversations, orphans) are a
   pre-computed survey — read those before hand-searching.
3. **Diff against intent.** Extract magic numbers and confirm their meaning
   from surrounding logic/in-game behavior; a raw `2`/`3` with no named
   constant is where swapped-parameter bugs hide (bug-patterns §2).

## Debug workflow

1. **Pin the symptom.** Exact observable: what happened, what should have,
   which player/team/area/state. "0 units," "gold not deposited," "unit keeps
   following after dismiss."
2. **Find the code that should run.** Trace from the event: which script is
   the handler (module/area/creature event, dialog action, item activation)?
   Follow `ExecuteScript`/`ActionDoCommand`/`DelayCommand` chains — control
   often hops scripts. `list_script_references` and grep for the tag/var name.
3. **Classify against the catalog** (`references/bug-patterns.md`). Most real
   bugs here fall into one of eight recurring classes; each has a detection
   recipe. Matching the class usually points straight at the line.
4. **Confirm the mechanism**, don't guess: read the actual values (2DA row,
   STRREF, blueprint), check save-vs-load key symmetry, check whether the NCS
   even exists in the shipped module (extract and list it).
5. **Fix minimally**, then verify (below). Prefer a named constant over a bare
   number when the bug was a magic-number mixup — it prevents the reoccurrence.

## The bug-class catalog

Full detail, real examples, and per-class detection recipes are in
`references/bug-patterns.md`. The classes:

1. **Silent `ExecuteScript` no-op / missing NCS** — the called script isn't in
   the shipped `.mod` or hak; the call vanishes. Root of the "0 units" bug.
2. **Magic-number parameter mixup** — an un-named `nParm`/mode int passed with
   two meanings swapped (mana↔gold vault). Compiles clean, routes wrong.
3. **Save/load key asymmetry** — a value stored under one local name and read
   under another (or reset on a code path that skips the store).
4. **Self-perpetuating `DelayCommand` loops** — `rts_unit_ai` re-queues itself;
   swapping the heartbeat does NOT stop it. Loops must bail out themselves.
5. **Duplicate tag / ambiguous target** — `GetObjectByTag` / `LinkedTo` hitting
   the wrong one of several same-tag objects. Transition & champion bugs.
6. **Stale build artifact / base-mod contamination** — the module ships an old
   NCS for a since-reverted source, or is missing a module-only NCS. Source
   looks right; the shipped binary is wrong.
7. **Uncompilable include chain** — a script that can't be rebuilt in-repo
   silently keeps its stale base NCS on every build; edits never take effect.
8. **Boolean vs engine-TRUE / faction pitfalls** — `== TRUE` on a function that
   returns non-1 truthy, or reputation/faction assumptions that don't hold.

## Verification (every fix)

- **Compile** the changed `.nss` with the project's `nwnsc` invocation before
  building — catch errors and the known-benign warnings separately.
- **Build** with the project's tooling; for these modules `build_module.sh
  --full` recompiles every tracked source so a stale base NCS can't survive a
  fix (see bug-patterns §6). Confirm your changed script is NOT in the
  "kept base NCS" failure list.
- **Extract-and-verify** when the bug was a missing/stale NCS: list the packed
  module (`nwn_erf -t`) and confirm the fresh NCS is present.
- **In-game / test server** is the only real validator — there is no unit-test
  framework. And note: **NWN:EE save games embed the module's scripts**, so a
  fix only reaches games started fresh on the new build; an old save chain
  reproduces the old bug regardless of the installed `.mod`.
- **GFF diff** for data edits: convert old vs new to JSON via `nwn_gff` and
  diff, to prove only the intended field changed.

## Recording findings

When a hunt lands on a non-obvious root cause (a stale artifact, a stranded
fix on a diverged branch, a class of magic-number risk), write it to project
memory or the repo's CODE_REVIEW notes with the symptom → mechanism → how it
was found, so the next session doesn't re-derive it. The catalog in this skill
grew from exactly those write-ups.
