# Test case spec — gap items 1, 2, 8, 9

Test specification for the editing capabilities added to close the four
coverage gaps that neither Q-nwn-manager nor `nwn-mcp` previously filled:

| Item | Capability | Implemented in |
|---|---|---|
| 9 | `.are` display `Name` + area-type `Flags` | `bin/nwn-area-editor` |
| 2 | `.utc`/`.bic` `SkillList` ranks | both editors |
| 8 | `.ifo` start location / calendar / rules | `bin/nwn-area-editor` |
| 1 | `.bic` depth + level-history integrity check | `nwn_web_editor.py` |

**Suite total: 77 new cases across 4 files** (152 including the pre-existing
suite, all passing).

```bash
for t in tests/test_*.py; do python3 "$t"; done      # everything
python3 tests/test_bic_integrity.py                  # one file
python3 -m unittest tests.test_bic_integrity.IntegrityTests.test_clean_character_reports_nothing
```

## Conventions

Following `tests/test_remove_objects.py`, the pattern all of these inherit:

- Modules are loaded with `SourceFileLoader` — `bin/nwn-area-editor` has no
  `.py` extension, and `nwn_web_editor.py` isn't on the import path.
- Fixtures are built in-process and mirror the field shapes real `nwn_gff`
  output uses. No module checkout, network, or `nwn_gff` binary is required,
  so the suite runs in well under a second.
- Each file that touches HTTP routes carries one live round-trip test through
  a real socket, which is what catches a routing/dispatch typo that
  direct function calls can't see.

## Risk model

The cases below are weighted toward four specific ways these features can
corrupt data, rather than spread evenly over the happy path:

1. **Silent flag clearing.** HTML checkboxes only submit when ticked, so a
   naive read of the form treats "no flag controls present" identically to
   "user unticked everything."
2. **Positional list drift.** `SkillList` entry *N* is row *N* of `skills.2da`
   and carries nothing but a `Rank`, so the index *is* the skill identity. Any
   append, truncation, or reorder silently reassigns every skill.
3. **Creating fields that didn't exist.** `.ifo` field sets vary by toolset
   build. Writing a field the module never carried is a behaviour change, not
   an edit.
4. **Level-history desync.** `LvlStatList` is the engine's own audit trail of
   how a character was built. Rewriting it to match an edit is how you produce
   a character the client refuses to load.

---

## `tests/test_area_name_flags.py` — item 9 (12 cases)

Targets `render_tags_form` / `apply_tags`.

### Name

| Case | Asserts |
|---|---|
| `test_name_is_written` | A submitted name reaches the `cexolocstring` |
| `test_blank_name_leaves_it_unchanged` | Blank means unchanged, matching the existing Tag convention; a sibling Tag edit still lands |
| `test_name_edit_alone_still_marks_the_area_changed` | Result page counts the area as changed |

### Flags — risk 1

| Case | Asserts |
|---|---|
| `test_flag_bits_set_from_checkboxes` | Ticked boxes OR into the dword |
| `test_unticked_boxes_clear_their_bits_when_the_marker_is_present` | With the marker, unticked genuinely clears |
| **`test_missing_marker_leaves_flags_completely_alone`** | **Risk 1.** No `flags_present_<res>` marker leaves `Flags` untouched while an unrelated name edit still applies |
| **`test_unknown_flag_bits_survive_a_save`** | Bit `0x100` (meaning unconfirmed) round-trips while the three known bits are rewritten |
| `test_no_change_form_is_a_no_op` | Resubmitting current values leaves the file byte-identical and reports `Changed 0 of 1` |
| `test_each_area_gets_its_own_flags` | Per-area field names don't bleed across a multi-area bulk edit |
| `test_flag_edit_survives_a_resref_rename` | Flags land in the renamed file, alongside the rewritten `ResRef` |

### Rendering + routing

| Case | Asserts |
|---|---|
| `test_form_prefills_name_and_checks_current_flags` | Current name prefilled; set bit rendered `checked`, unset bit not |
| `test_full_http_round_trip` | `GET /areas/edit?action=tags` → `POST /areas/tags/apply` over a socket |

## `tests/test_skill_ranks.py` — item 2 (17 cases)

Covers **both** editors, since the logic is duplicated between them.

### Writing — risk 2

| Case | Asserts |
|---|---|
| `test_rank_written_at_the_right_index` | Correct index changes *and* the total confirms nothing else did |
| `test_blank_leaves_a_rank_unchanged` | Blank is unchanged, not zero |
| `test_rank_can_be_zeroed` | An explicit `0` is distinguishable from blank |
| `test_unchanged_value_does_not_report_a_change` | Idempotent — no spurious file write |
| **`test_list_length_and_order_are_preserved`** | 28 entries in, 28 out, exactly one differing |
| **`test_out_of_range_index_never_grows_the_list`** | A hak-extended `skills.2da` on the render side can't append entries |
| **`test_short_skill_list_is_not_extended`** | A 4-entry list stays 4 entries |
| `test_missing_skill_list_is_left_absent` | Absent `SkillList` is never created |
| `test_struct_id_is_preserved` | `__struct_id` survives a rank write |

### Name lookup

| Case | Asserts |
|---|---|
| `test_stock_rows_resolve_to_names_in_both_editors` | Rows 0/1/3 resolve identically in both editors — guards the web editor's separately-derived `bin/wiki_data` path |
| `test_unknown_row_falls_back_to_the_raw_index` | Unknown row degrades to `skill 999`, never raises |

### Rendering

| Case | Asserts |
|---|---|
| `test_console_renders_one_input_per_entry_in_file_order` | 28 inputs, named rows present, **file order not alphabetical** |
| `test_web_editor_renders_the_same_field_names` | Both editors emit the same `skill_<N>` names |
| `test_absent_skill_list_renders_an_explanation_not_inputs` | No inputs, explanatory text instead |
| `test_current_ranks_are_prefilled` | Existing rank shows in the input |

### Web-editor apply path

`test_ranks_apply_in_place`, `test_out_of_range_index_ignored` — the duplicated
apply logic gets its own coverage rather than relying on the console's.

## `tests/test_module_settings.py` — item 8 (17 cases)

Targets `render_module_form` / `apply_module`.

### Writing

| Case | Asserts |
|---|---|
| `test_start_location_fields_are_written` | `Mod_Entry_X` / `Mod_Entry_Dir_Y` land as floats |
| `test_calendar_and_rule_fields_are_written` | `Mod_StartYear`, `Mod_DawnHour`, `Mod_XPScale` |
| `test_declared_gff_types_are_preserved` | `dword` stays `dword`, `float` stays `float` and stays a Python float |
| `test_resref_fields_are_lowercased` | `NewStart` → `newstart` (resrefs are lowercase) |
| `test_name_and_description_still_work` | The pre-existing two fields aren't regressed |

### Leaving things alone — risk 3

| Case | Asserts |
|---|---|
| `test_blank_leaves_a_field_unchanged` | Blank and whitespace-only both mean unchanged |
| **`test_untouched_form_is_a_byte_identical_no_op`** | Empty form doesn't rewrite the file at all |
| **`test_absent_fields_are_never_created`** | Submitting `Mod_XPScale` for a module that lacks it is a no-op, and the key stays absent |
| **`test_hak_list_and_custom_tlk_are_untouched`** | Deferred by design — submitting them changes nothing |

### Warnings

| Case | Asserts |
|---|---|
| `test_missing_start_area_warns_but_still_saves` | Nonexistent start area warns but doesn't block the save (the area may legitimately not be unpacked) |
| `test_existing_start_area_produces_no_warning` | No false positive |

### Rendering + routing

`test_form_renders_every_present_editable_field`,
`test_form_omits_absent_fields_and_hak_controls`,
`test_empty_group_renders_no_fieldset` (a bare `.ifo` shows no empty Start
location / Rules boxes), `test_current_values_are_prefilled`,
`test_full_http_round_trip`, `test_missing_start_area_warning_reaches_the_page`.

## `tests/test_bic_integrity.py` — item 1 (31 cases)

Fixture: a consistent 3rd-level fighter whose per-level skill gains and feat
grants sum exactly to the character's totals.

### `check_bic_integrity` — risk 4 (11 cases)

| Case | Asserts |
|---|---|
| **`test_clean_character_reports_nothing`** | **The negative control.** If a valid character produces findings, every other case here is meaningless. Also verified manually against a real `.bic` (`hos1/bics/theranifoecrush17.bic` → clean) |
| `test_class_level_mismatch_is_reported` | `ClassList` level vs recorded level-ups |
| `test_skill_rank_mismatch_is_reported` | Per-level rank gains vs current ranks, named per skill |
| `test_orphan_top_level_feat_is_reported` | Feat on the character, never granted — this is what the existing "add feat" control produces |
| `test_feat_granted_but_missing_is_reported` | The reverse direction |
| `test_class_absent_from_class_list_is_reported` | Level-ups for a class not in `ClassList` |
| `test_multiclass_character_is_clean` | Fighter 2 / Sorcerer 1 with matching history — guards against false positives on legitimate multiclassing |
| **`test_check_never_mutates_the_character`** | Deep-equality before/after on an *inconsistent* character — the check reports, never repairs |
| `test_file_without_level_history_is_skipped` | A `.utc` has no `LvlStatList`; that isn't an inconsistency |
| `test_findings_render_as_warnings`, `test_clean_character_renders_an_ok_message` | Rendering of both states |

### `apply_bic_edits` (14 cases)

| Case | Asserts |
|---|---|
| `test_class_id_and_level_are_written` | Per-index class edits |
| `test_class_known_spells_are_left_alone` | `KnownList0` on the same struct survives a level edit |
| `test_blank_class_field_leaves_it_unchanged` | Blank convention holds |
| `test_alignment_is_written_through_apply_char_edits` | `GoodEvil` / `LawfulChaotic` |
| `test_alignment_is_not_offered_for_a_utc` | `.bic`-only fields don't leak into blueprint editing |
| `test_deity_and_description_are_written` | `cexostring` and `cexolocstring` paths |
| `test_absent_text_field_is_never_created` | Risk 3 again, on the `.bic` side |
| `test_carried_items_are_removed_by_index` | Correct item removed |
| **`test_removing_several_items_uses_original_indices`** | Multi-removal doesn't shift indices mid-pass |
| `test_clear_quickbar_empties_slots_but_keeps_the_length` | 36 slots stay 36 — the engine expects fixed length |
| `test_clear_quickbar_is_idempotent` | Second clear reports no change |
| **`test_cleared_slots_are_independent_objects`** | Slots are deep-copied; mutating slot 0 doesn't change slot 1 (a shared-dict bug would be invisible until a later edit) |
| `test_untouched_form_is_a_no_op` | Deep-equality on an empty form |
| **`test_level_history_is_never_written`** | Four simultaneous edits leave `LvlStatList` deep-equal |

### Rendering (6 cases)

| Case | Asserts |
|---|---|
| `test_level_table_is_read_only` | **No `<input>` anywhere** in the level table |
| `test_level_table_names_skills_and_feats_gained` | 2DA lookups resolve (`Concentration`, `Power Attack`) |
| `test_bic_form_includes_the_bic_only_sections` | All eight `.bic` markers present |
| `test_utc_form_omits_them` | Blueprint form has no level history/quickbar, but does have skills |
| `test_classes_table_prefills_current_values` | Class id, level, and resolved name |
| `test_inventory_lists_carried_items_only` | `Equip_ItemList` deliberately excluded — unequipping by file surgery leaves slots the client handles badly |

---

## Not covered by automated tests

Deliberate gaps, and why:

- **Binary GFF round-tripping.** The web editor's `gff_load`/`gff_save` shell
  out to `nwn_gff`. Tests operate on parsed dicts, so a regression in the
  subprocess plumbing wouldn't be caught here. Covered by the manual checks
  below instead.
- **In-game validity.** No test can confirm the NWN client accepts an edited
  character or that an area's flags produce the intended lighting. The
  integrity check narrows the risk; it doesn't eliminate it.
- **The web editor's HTTP routes.** Only the console has socket-level tests.
  The web editor's `/bic` and `/bic/apply` routes are exercised through their
  underlying functions.

## Manual verification

1. `bin/nwn-manager console --projects-dir …` — edit an area's Name and flags,
   confirm the area-list flag filter reflects the edit; set a module start
   location; `nwn-manager repack` and confirm `nwn_gff` round-trips clean.
2. Run the web editor against a **copy** of a servervault (it writes a one-time
   `.bak` per file), confirm integrity findings on a real character, edit skill
   ranks, and re-open the character in the NWN client to confirm it loads.
