# NWN logic-bug catalog

Eight recurring bug classes, each with the mechanism, a detection recipe, and
a real example from these persistent-world modules. Match a symptom to a class
and the recipe usually points at the line. Treat the examples as *patterns to
re-verify against current code*, not live facts — `file:line` citations drift.

---

## 1. Silent `ExecuteScript` no-op / missing NCS

**Mechanism.** `ExecuteScript("foo", oTarget)` on a script whose compiled
`.ncs` is absent from the module (and any loaded hak/override) does **nothing**
— no error, no log, no player message. A whole subsystem's setup can simply
never run. Same trap: `ActionStartConversation` on a missing dialog,
`CreateObject` on a missing blueprint.

**Detect.**
- List what's actually shipped: `nwn_erf -t -f module.mod | grep foo`. Source
  present in the repo ≠ NCS present in the `.mod`.
- `find_orphans` / `validate_module` flag references with no target.
- Grep the caller chain for `ExecuteScript(` and confirm each callee exists as
  an `.ncs` in the packed module, especially module-only scripts that live in
  no hak.

**Real example.** `rts_load_mod.ncs` was missing from the base module.
`generic_loadmod.ncs` did `ExecuteScript("rts_load_mod")` → no-op →
`rts_set_defaults` never ran on a fresh game → `nMaxUnits` stayed 0 → the unit
tool reported "maximum number of units … You have 0 units." Source was fine;
the shipped binary was missing. (See also §6.)

---

## 2. Magic-number parameter mixup

**Mechanism.** A bare int passed as a mode/resource selector, with no shared
named constant, gets its two meanings swapped at one call site. Compiles
perfectly; routes behavior to the wrong branch.

**Detect.**
- Find selector ints (`nParm`, `nMode`, `nType`) passed as raw literals; trace
  every producer and consumer and confirm the number→meaning mapping agrees on
  both ends.
- The global rule "extract magic numbers into named constants" is a *bug
  preventer here, not style* — introducing `RAID_RESOURCE_MANA`/`_GOLD` makes a
  swap impossible to write.

**Real example.** `ai_raid_v2.nss` "return to lair" passed `nParm==2` (mana)
and `nParm==3` (gold) swapped vs. `rts_raid_mana.nss`/`rts_raid_gold.nss`, so
mana raiders deposited into the gold vault and gold raiders hit a mana-vault
no-op. Nothing named the 2/3, so nothing caught it.

---

## 3. Save/load key asymmetry

**Mechanism.** State persisted under one local-variable name but read under a
different one, or a store that's skipped on an early-return path the loader
still expects to have run. The value silently reads back as 0/"".

**Detect.**
- For each persisted local, grep every `Set*Local*`/`Get*Local*` with that key
  and confirm the **exact** string matches on both sides (typos, casing,
  suffixes).
- Check early-return branches: does any path skip the `Set` the loader depends
  on? Track the "last known" value on *all* return paths, not just the happy
  one.

**Real example (pattern).** Legacy PW modules persist state as delimiter-
encoded strings in one generic key/value table; a field written with one
delimiter layout and parsed with another reads as empty. Centralize the
delimiters and use `Between`/`EncodedField`-style helpers so writer and reader
can't disagree.

---

## 4. Self-perpetuating `DelayCommand` loop

**Mechanism.** A script re-queues itself with `DelayCommand(t,
ExecuteScript(self, OBJECT_SELF))` at the end of `main()`. Once running, the
loop is **independent of the creature's heartbeat event** — swapping
`ON_HEARTBEAT` with `SetEventScript` does not stop the in-flight chain.

**Detect.**
- If "changing the heartbeat didn't stop the behavior," grep the running
  script for `DelayCommand(...ExecuteScript(` of itself.
- To actually stop it, add an early-return flag as the **first** statement of
  the loop's `main()` and set that flag.

**Real example.** `rts_unit_ai.nss` re-queues itself every tick. The henchman
feature swapped a recruited unit's heartbeat to vanilla associate AI, but the
unit kept following via the leftover RTS loop until
`if (GetLocalInt(OBJECT_SELF,"bHHenchman")) return;` was added at the top. A
separate "kicker" (`rts_default1`) also relaunches stalled loops — account for
re-kickers when disabling a loop.

---

## 5. Duplicate tag / ambiguous target

**Mechanism.** `GetObjectByTag(sTag)` returns the *first* object with that tag;
`LinkedTo` transitions resolve by tag too. Two objects sharing a tag → the
engine may pick the wrong one, and which one is fragile across saves/spawns.

**Detect.**
- `search_by_tag` and `visualize_area`'s object list; treat any repeated tag
  across placed objects as a warning worth flagging even when unasked.
- The wiki module-index `duplicate_destination_tags.json` /
  `*_tag_conflicts.json` findings pre-compute these.
- For transitions: confirm each door/trigger `LinkedTo` resolves to exactly one
  target of the expected type (door-tag vs waypoint-tag flag).

**Real example.** Area/creature tag-conflict and duplicate-destination-tag
findings in this module's wiki index; a `plan_unc`/`plan_dwf` area-tag swap was
a live instance where a transition/lookup landed on the wrong area.

---

## 6. Stale build artifact / base-mod contamination

**Mechanism.** The shipped `.mod` carries an **old** compiled NCS for a source
that was later reverted, or is missing a module-only NCS entirely. Reading the
current source misleads you; the binary in the module is what runs.

**Detect.**
- Extract and inspect the shipped NCS (or its embedded string constants) rather
  than trusting source — e.g. an NCS still containing a reverted era's SQL.
- Check incremental-build logic: a git-diff-since-base overlay **misses**
  scripts whose source never changed but whose base NCS is stale/absent.

**Real example.** After "Remove all module NCS overrides," module-only scripts
that belonged in the module (not a hak) went missing, and `rtsunit_creation`'s
base NCS was a since-reverted SQLite-era build. Fix: a `--full` build that
recompiles every tracked source and overlays, plus an always-compiled CRITICAL
list (`generic_loadmod rts_load_mod rts_set_defaults rts_default1 rts_default9
rts_unit_ai rtsunit_creation`) so stale/missing base NCS can't survive a build.
Note a fix stranded on a long-diverged branch (`origin/Henchmen`) inside a
mislabeled commit was invisible to `git log --grep` and only found by per-file
diff (`git diff master <branch> -- <file>`).

---

## 7. Uncompilable include chain

**Mechanism.** A script whose `#include` chain isn't fully in the repo can't be
rebuilt locally. A tolerant build **keeps its stale base NCS** and lists it as
a failure — so edits to that script (or its includes) silently never take
effect in the built module.

**Detect.**
- After a build, read the "kept base-module NCS (compile failed)" list; if the
  script you just edited is on it, your change did **not** ship.
- Known in these modules: the `hos_chat`/NPC-Activities (`npcactivitiesh`)
  chain and ~6 others. Hook the desired behavior on a script that *does*
  compile (e.g. the unit/heartbeat side) instead.

**Real example.** `hos_chat.nss` can't be recompiled in-repo (npcactivitiesh
include chain untracked); intended behavior was hooked on the unit side rather
than edited into hos_chat, whose base NCS would have persisted unchanged.

---

## 8. Boolean vs engine-TRUE / faction pitfalls

**Mechanism.** `if (f(x) == TRUE)` breaks when `f` returns a non-1 truthy int;
and reputation/faction assumptions (`GetIsReactionTypeHostile`,
`ChangeToStandardFaction`) can silently not hold after respawns or cross-faction
blueprint drift.

**Detect.**
- Drop `== TRUE/FALSE` only for engine functions documented to return exactly
  1/0; for custom functions, read the return contract first.
- `cross_faction_creatures.json` / `faction_bp_instance_discrepancies.json`
  wiki findings flag blueprint-vs-instance faction mismatches.
- Always `GetIsObjectValid()` before acting on a possibly-stale object ref
  (`DestroyObject`, `ApplyEffectToObject`, `ChangeToStandardFaction`).

**Real example (pattern).** Cross-faction creature and faction blueprint/
instance discrepancies surfaced by the module-index audit — instances whose
faction differs from their blueprint, which makes hostility checks behave
inconsistently depending on which record the engine used.

---

## Quick reference: symptom → likely class

| Symptom | Start with class |
|---|---|
| A value stays 0 / setup never ran | §1 missing NCS, §6 stale build |
| Right action, wrong target (vault/area/object) | §2 magic number, §5 dup tag |
| Persisted value reads back empty | §3 save/load asymmetry |
| Behavior won't stop after you disabled it | §4 self-loop |
| Edited a script but nothing changed in-game | §7 uncompilable, §6 stale, save embeds scripts |
| Friend/enemy logic inconsistent | §8 faction |
| "It used to work" | §6 stale build / diverged-branch fix |
