# TEST.md — cli-anything-ramus

Test plan written before the test code, with the results appended after the run.

## Test environment

The end-to-end suites are not optional and they do not degrade gracefully. They
require a real Ramus build, because the CLI is an interface to Ramus rather than
a reimplementation of it. Without `ramus.jar` the E2E tests fail; they never skip
and never fake a result.

```bash
export RAMUS_JAR=/path/to/ramus.jar     # or RAMUS_HOME, or run inside a built checkout
CLI_ANYTHING_FORCE_INSTALLED=1 python3 -m pytest cli_anything/ramus/tests/ -v -s
```

`-s` shows the `[_resolve_cli]` line proving which command the subprocess tests
drove, and prints the path of every artifact so a human can open them.

---

## Part 1 — Test plan

### Test inventory

| File | Kind | Requires Ramus | Planned tests |
|------|------|----------------|---------------|
| `test_core.py` | Unit — synthetic data, no external process | no | ~45 planned, 88 written |
| `test_full_e2e.py` | E2E — real engine, real files, subprocess CLI | yes | ~45 planned, 94 written |

### Unit test plan (`test_core.py`)

Everything here runs without a JVM. It covers the logic that lives in Python:
argument validation, output verification, formatting, and session bookkeeping.

**`core/export.py` — output verification (the most safety-critical unit)**
- `verify_output` accepts a correct PNG, JPEG, BMP, PDF, SVG, EMF, IDL and RSF.
- Rejects each of those when the leading bytes belong to a different format —
  this is what stops "the command exited 0" from being mistaken for "the render
  worked".
- Rejects a missing file and a zero-byte file, with a distinguishable `detail`.
- Reports an unknown extension rather than claiming validity.
- `human_size` formats bytes, kilobytes and megabytes.
- `export_diagram` rejects a format the painter cannot produce, and rejects
  `pdf` with a pointer to the dedicated command.
- `export_all` rejects an unknown format.

**`core/model.py`**
- `render_tree` draws a single root, a flat list, and a nested tree, with the
  last child getting the closing connector at every depth (a regression this
  suite caught during development).
- `create_model` rejects an unknown diagram type before touching the engine.
- `set_options` refuses a call that would change nothing.

**`core/function.py`**
- `add_function` / `set_type` reject unknown activity types.
- `move`, `resize`, `set_color`, `set_font` refuse no-op calls.
- `decompose` rejects an empty child list.

**`core/arrow.py`**
- `add_arrow` rejects unknown side words on either end.
- `add_arrow` rejects border-to-border, which carries nothing.
- `describe_endpoint` renders function, border and unset endpoints.
- Every IDEF0 side alias is accepted.

**`core/classifier.py`**
- `render_elements` renders a flat list and a nested tree with indentation.

**`core/session.py`**
- `session_id_for` is stable for the same path, differs across paths, and
  survives a relative path.
- `_locked_save_json` writes valid JSON, overwrites a longer previous file
  completely (the truncation-inside-the-lock behaviour), and creates missing
  parent directories.
- A fresh `Session` reports no project and raises a clear error when a command
  needs one.
- `Session.list_sessions` tolerates a corrupt state file.

**`utils/ramus_backend.py`**
- `find_ramus_jar` honours `RAMUS_JAR`, honours `RAMUS_HOME`, and raises
  `RamusNotFound` carrying install instructions when neither points anywhere.
- A `RAMUS_JAR` that does not exist is rejected rather than passed along.
- `backend_info` reports a problem instead of raising.
- `BridgeError` keeps its Java trace.

**`core/preview.py`**
- `list_recipes` returns the documented recipes and declares the protocol
  version.
- `capture` rejects an unknown recipe.

**CLI surface (`ramus_cli.py`, via `click.testing.CliRunner`)**
- `--help` lists every command group.
- `--version` prints the version.
- Each group's `--help` works.
- `--json` is accepted globally.

### E2E test plan (`test_full_e2e.py`)

Every test drives the real Ramus engine and inspects the files it produces.

**Project lifecycle**
- `project new` writes a file that starts with the ZIP header a `.rsf` must
  have, and contains the model, author and classifiers that were asked for.
- Reopening the file in a fresh engine returns the same model.
- `save-as` writes a second working file.
- `validate` accepts the file and reports its counts.
- Creating over an existing file fails without `--overwrite`.

**Models**
- Create IDEF0, DFD and DFDS models; each reports its own notation back.
- List, rename, delete.
- `set-options` values survive a save/reopen round trip.
- Selecting a model by id and by name both work; an ambiguous omission gives a
  message naming the candidates.

**Functions**
- Add boxes; they receive IDEF0 node numbers A1, A2, A3 in order.
- Decompose a box; its children become A11, A12, A13 and the parent reports
  itself as decomposed.
- Rename, move, resize, recolour, refont, retype — each verified by reading the
  value back out of the engine.
- Renaming A0 renames the model, matching the GUI.
- Deleting the base function is refused with an explanatory message.
- Delete removes the box and its subtree.
- Bounds survive a save/reopen round trip.

**Arrows**
- Box-to-box arrow, verified by endpoint, side and label.
- Arrow from the diagram border into a box (an IDEF0 input).
- Arrow from a box out to the border (an output).
- Arrow into the control (top) side.
- Rename an arrow; the new label appears in the model's arrow dictionary.
- Delete an arrow; the remaining arrows still resolve.
- Connecting boxes that are not on the same diagram is refused.
- Arrows survive a save/reopen round trip with both endpoints intact.

**Rendering — this is where "it ran" is not enough**
- PNG, JPEG, BMP and SVG each render and pass magic-byte verification.
- EMF is tested separately: see "What the run changed about the plan" below.
- The PNG is decoded and checked to be a real image of plausible size, mostly
  white (an IDEF0 diagram on white paper) but not blank — a fully uniform image
  would mean the painter drew nothing.
- Adding a box makes the rendered PNG change: byte-identical output would mean
  the render ignored the edit. This is the rendering-gap check.
- Colouring a box changes the pixels it occupies, proving box attributes reach
  the painter and are not merely stored.
- SVG output contains drawing elements, not just a header.
- PDF starts with `%PDF-`, and a two-diagram model produces a two-page PDF while
  a one-diagram export produces one page.
- `export all` writes one file per decomposed diagram, named by node number,
  and every one passes verification.
- Rendering a box that has no children is refused with an explanation, rather
  than silently writing an empty page.
- Every artifact path is printed for manual inspection.

**Interchange (IDL)**
- Exporting a model whose arrows carry no label produces a file with the IDL
  header.
- Exporting a model whose arrows do carry labels fails with the CLI's
  explanation of the upstream Ramus defect — asserted so the suite notices if a
  future Ramus fixes it.
- Importing an IDL file whose context section is named `A-0` succeeds and
  creates a model with the expected functions.
- Importing Ramus's own export fails with the CLI's explanation of the
  exporter/importer mismatch — again asserted, not skipped.

**Undo / redo**
- Undo removes the last box and rewrites the project file on disk.
- Redo restores it.
- Undo across separate processes works, because history is keyed by project
  path — the property that makes undo usable from one-shot commands.
- Undo with an empty history reports "Nothing to undo".

**Previews**
- `preview capture` publishes a `preview-bundle/v1` bundle whose manifest,
  summary and artifacts all exist on disk and verify.
- Capturing again with nothing changed reuses the bundle instead of
  re-rendering; `--force` re-renders.
- `preview latest` returns the newest bundle without rendering.
- `preview diff` against a copied baseline reports the structural change.
- The `tree` recipe publishes inspection JSON and no images.

**Realistic workflow scenarios**

1. **Order fulfilment model, built and published.** Simulates an analyst
   modelling a business process from nothing.
   *Operations:* create project with author and classifiers → add three
   top-level activities → wire an input from the border, two internal flows and
   an output to the border → decompose the middle activity into three
   sub-activities → wire the sub-diagram → set the title-block options → render
   every diagram to PNG → render the whole model to PDF.
   *Verified:* the tree has the expected shape and node numbers; every arrow
   resolves to the right endpoints and sides; the PDF has one page per diagram
   and starts with `%PDF-`; each PNG is a real, non-blank image; the saved
   project reopens with everything intact.

2. **Iterative refinement.** Simulates the edit-look-edit loop an agent runs.
   *Operations:* build a small model → capture a preview → add a box → capture
   again → undo → capture again.
   *Verified:* the middle bundle differs from the first; after the undo the
   model is back to its earlier counts and the render matches the first one
   again.

3. **Review pass over an existing project.** Simulates picking up someone
   else's file.
   *Operations:* open a saved project in a fresh session → validate → list
   models, functions, arrows and classifiers → export the top diagram.
   *Verified:* nothing needed to be created, the counts match what was saved,
   and the render succeeds from a cold start.

4. **Multi-model project.** Simulates a project holding several notations.
   *Operations:* one project with an IDEF0 model, a DFD model and two
   classifiers with nested elements → populate all of them → render one diagram
   per model.
   *Verified:* each model keeps its own notation and box set; classifier
   elements nest correctly; models are addressable by both name and id.

5. **Heavy undo stress.** Simulates an agent backing out of a wrong direction.
   *Operations:* twelve successive mutations, then eight undos, then four redos.
   *Verified:* counts track exactly at each stage and the file on disk matches
   the reported state at the end.

**CLI subprocess tests (`TestCLISubprocess`)**

These invoke the installed `cli-anything-ramus` command through `_resolve_cli`,
with no `cwd` set, so they prove the packaged command works from anywhere.

- `--help` and `--version`.
- `doctor` reports the backend as ready and names the jar.
- `--json project new` emits parseable JSON with the created path.
- A full workflow — new → add boxes → add arrows → decompose → export PNG →
  export PDF — driven entirely through the installed command, with the output
  files verified afterwards.
- `--json` output parses for every command in that workflow.
- A bad argument exits non-zero and puts a JSON error object on stderr.
- `--dry-run` leaves the project file byte-identical.
- Auto-save means a mutation in one process is visible to the next.

### What the run changed about the plan

Two planned assertions turned out to be wrong about the software rather than
about the CLI, and the tests were corrected to state what is actually true.

1. **EMF cannot be exported headlessly.** The plan grouped EMF with the other
   image formats. It is not: Ramus writes EMF through FreeHEP, whose
   `EMFGraphics2D.writeHeader` asks the toolkit for the screen size, which
   throws `HeadlessException` in any headless JVM. The CLI now reports that
   precisely, `export formats` lists EMF under `needs_display`, and the test
   asserts the explanation appears — so the suite will notice if a future
   FreeHEP drops that call. With `CLI_ANYTHING_RAMUS_HEADLESS=0` and a real
   display, the same test renders and verifies an EMF instead.

2. **Undo does not reproduce a byte-identical project file.** The iterative
   refinement workflow originally asserted that capturing a preview after an
   undo would reuse the pre-edit bundle. It does not, because Ramus stamps a
   fresh revision date whenever it saves, so the `.rsf` content hash differs
   even when the model is identical. The test now asserts the thing that
   actually matters and is actually true: after the undo the **rendered PNG is
   byte-identical** to the pre-edit render, and the model's contents match.

Both are properties of Ramus, not of the harness, and both are documented in
README.md and SKILL.md rather than hidden.

---

## Part 2 — Test results

Run on Linux with OpenJDK 21, Python 3.12, against a Ramus build produced by
`./gradlew :local-client:shadowJar`, with the CLI installed via `pip install -e .`
and `CLI_ANYTHING_FORCE_INSTALLED=1` so the subprocess tests drove the real
installed command.

```
CLI_ANYTHING_FORCE_INSTALLED=1 python3 -m pytest cli_anything/ramus/tests/ -v --tb=no
```

### Summary

| | |
|---|---|
| Total tests | **182** |
| Passed | **182** |
| Failed | 0 |
| Skipped | 0 |
| Pass rate | **100%** |
| Wall time | 163.70s |
| Unit tests (`test_core.py`) | 88 |
| End-to-end tests (`test_full_e2e.py`) | 94 |
| Of which drove the installed command via subprocess | 11 |

### Full output

```
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.0.3, pluggy-1.6.0 -- /usr/bin/python3
rootdir: <agent-harness>
plugins: anyio-4.12.0, Faker-40.4.0, requests-mock-1.12.1
collecting ... collected 182 items
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_real_png PASSED [  0%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_real_jpeg PASSED [  1%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_real_bmp PASSED [  1%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_real_pdf PASSED [  2%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_svg PASSED [  2%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_emf PASSED [  3%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_idl PASSED [  3%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_accepts_rsf PASSED [  4%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_png_that_is_really_a_pdf PASSED [  4%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_pdf_that_is_really_html PASSED [  5%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_svg_without_svg_element PASSED [  6%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_emf_without_signature PASSED [  6%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_missing_file PASSED [  7%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_rejects_empty_file PASSED [  7%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_unknown_extension_is_not_claimed_valid PASSED [  8%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_jpeg_extension_is_normalised PASSED [  8%]
cli_anything/ramus/tests/test_core.py::TestVerifyOutput::test_explicit_format_overrides_extension PASSED [  9%]
cli_anything/ramus/tests/test_core.py::TestHumanSize::test_bytes PASSED  [  9%]
cli_anything/ramus/tests/test_core.py::TestHumanSize::test_kilobytes PASSED [ 10%]
cli_anything/ramus/tests/test_core.py::TestHumanSize::test_megabytes PASSED [ 10%]
cli_anything/ramus/tests/test_core.py::TestExportValidation::test_rejects_unknown_image_format PASSED [ 11%]
cli_anything/ramus/tests/test_core.py::TestExportValidation::test_points_pdf_at_its_own_command PASSED [ 12%]
cli_anything/ramus/tests/test_core.py::TestExportValidation::test_export_all_rejects_unknown_format PASSED [ 12%]
cli_anything/ramus/tests/test_core.py::TestRenderTree::test_single_root PASSED [ 13%]
cli_anything/ramus/tests/test_core.py::TestRenderTree::test_flat_children_close_the_branch PASSED [ 13%]
cli_anything/ramus/tests/test_core.py::TestRenderTree::test_nested_children_are_indented_under_their_parent PASSED [ 14%]
cli_anything/ramus/tests/test_core.py::TestRenderTree::test_last_child_at_every_depth_gets_the_closing_connector PASSED [ 14%]
cli_anything/ramus/tests/test_core.py::TestModelValidation::test_rejects_unknown_diagram_type PASSED [ 15%]
cli_anything/ramus/tests/test_core.py::TestModelValidation::test_set_options_refuses_a_no_op PASSED [ 15%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_add_rejects_unknown_type PASSED [ 16%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_set_type_rejects_unknown_type PASSED [ 17%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_move_refuses_a_no_op PASSED [ 17%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_resize_refuses_a_no_op PASSED [ 18%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_set_color_refuses_a_no_op PASSED [ 18%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_set_font_refuses_a_no_op PASSED [ 19%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_decompose_rejects_an_empty_child_list PASSED [ 19%]
cli_anything/ramus/tests/test_core.py::TestFunctionValidation::test_every_documented_type_is_accepted PASSED [ 20%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_rejects_unknown_from_side PASSED [ 20%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_rejects_unknown_to_side PASSED [ 21%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_rejects_border_to_border PASSED [ 21%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_border_is_case_insensitive_in_the_check PASSED [ 22%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_idef0_side_names_are_all_available PASSED [ 23%]
cli_anything/ramus/tests/test_core.py::TestArrowValidation::test_geometric_side_aliases_are_available PASSED [ 23%]
cli_anything/ramus/tests/test_core.py::TestDescribeEndpoint::test_function_endpoint PASSED [ 24%]
cli_anything/ramus/tests/test_core.py::TestDescribeEndpoint::test_border_endpoint PASSED [ 24%]
cli_anything/ramus/tests/test_core.py::TestDescribeEndpoint::test_unset_endpoint PASSED [ 25%]
cli_anything/ramus/tests/test_core.py::TestRenderElements::test_flat_list PASSED [ 25%]
cli_anything/ramus/tests/test_core.py::TestRenderElements::test_nested_elements_are_indented PASSED [ 26%]
cli_anything/ramus/tests/test_core.py::TestRenderElements::test_empty_list PASSED [ 26%]
cli_anything/ramus/tests/test_core.py::TestSessionId::test_is_stable_for_the_same_path PASSED [ 27%]
cli_anything/ramus/tests/test_core.py::TestSessionId::test_differs_across_paths PASSED [ 28%]
cli_anything/ramus/tests/test_core.py::TestSessionId::test_relative_and_absolute_paths_agree PASSED [ 28%]
cli_anything/ramus/tests/test_core.py::TestSessionId::test_id_is_filesystem_safe PASSED [ 29%]
cli_anything/ramus/tests/test_core.py::TestLockedSaveJson::test_writes_valid_json PASSED [ 29%]
cli_anything/ramus/tests/test_core.py::TestLockedSaveJson::test_overwrites_a_longer_previous_file_completely PASSED [ 30%]
cli_anything/ramus/tests/test_core.py::TestLockedSaveJson::test_creates_missing_parent_directories PASSED [ 30%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_new_session_has_no_project PASSED [ 31%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_require_project_explains_what_to_do PASSED [ 31%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_directory_needs_an_id PASSED [ 32%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_status_of_an_empty_session PASSED [ 32%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_dry_run_defaults_to_off PASSED [ 33%]
cli_anything/ramus/tests/test_core.py::TestSessionState::test_list_sessions_tolerates_a_corrupt_state_file PASSED [ 34%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_env_jar_wins PASSED [ 34%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_env_jar_that_does_not_exist_is_rejected PASSED [ 35%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_ramus_home_is_searched PASSED [ 35%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_empty_ramus_home_is_reported PASSED [ 36%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_missing_ramus_gives_install_instructions PASSED [ 36%]
cli_anything/ramus/tests/test_core.py::TestJarDiscovery::test_backend_info_reports_rather_than_raises PASSED [ 37%]
cli_anything/ramus/tests/test_core.py::TestBridgeError::test_keeps_the_java_trace PASSED [ 37%]
cli_anything/ramus/tests/test_core.py::TestPreviewRecipes::test_lists_the_documented_recipes PASSED [ 38%]
cli_anything/ramus/tests/test_core.py::TestPreviewRecipes::test_declares_the_bundle_protocol PASSED [ 39%]
cli_anything/ramus/tests/test_core.py::TestPreviewRecipes::test_says_live_mode_is_unsupported_and_why PASSED [ 39%]
cli_anything/ramus/tests/test_core.py::TestPreviewRecipes::test_capture_rejects_an_unknown_recipe PASSED [ 40%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_help_lists_every_group PASSED [ 40%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_version PASSED [ 41%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[project] PASSED [ 41%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[model] PASSED [ 42%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[function] PASSED [ 42%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[arrow] PASSED [ 43%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[classifier] PASSED [ 43%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[element] PASSED [ 44%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[export] PASSED [ 45%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[import] PASSED [ 45%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[preview] PASSED [ 46%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_group_help[session] PASSED [ 46%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_json_flag_is_accepted PASSED [ 47%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_dry_run_flag_is_documented PASSED [ 47%]
cli_anything/ramus/tests/test_core.py::TestCliSurface::test_arrow_add_help_documents_idef0_sides PASSED [ 48%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_new_project_writes_a_real_rsf PASSED [ 48%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_new_project_contains_what_was_asked_for PASSED [ 49%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_reopening_in_a_fresh_engine_returns_the_same_model PASSED [ 50%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_save_as_writes_a_second_working_file PASSED [ 50%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_validate_accepts_a_real_project PASSED [ 51%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_creating_over_an_existing_file_is_refused PASSED [ 51%]
cli_anything/ramus/tests/test_full_e2e.py::TestProjectLifecycle::test_project_info_counts_everything PASSED [ 52%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_create_each_notation PASSED [ 52%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_notation_survives_a_round_trip PASSED [ 53%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_rename PASSED [ 53%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_delete PASSED [ 54%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_options_survive_a_round_trip PASSED [ 54%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_selectable_by_id_and_by_name PASSED [ 55%]
cli_anything/ramus/tests/test_full_e2e.py::TestModels::test_ambiguous_selection_names_the_candidates PASSED [ 56%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_boxes_get_idef0_node_numbers_in_order PASSED [ 56%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_decompose_numbers_children_under_their_parent PASSED [ 57%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_default_layout_keeps_six_boxes_on_the_page PASSED [ 57%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_rename PASSED [ 58%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_renaming_a0_renames_the_model PASSED [ 58%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_move_and_resize_are_read_back PASSED [ 59%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_bounds_survive_a_round_trip PASSED [ 59%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_colours_are_read_back PASSED [ 60%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_font_is_read_back PASSED [ 60%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_type_is_read_back PASSED [ 61%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_delete_removes_the_box PASSED [ 62%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_delete_removes_the_subtree PASSED [ 62%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_deleting_the_base_function_is_refused PASSED [ 63%]
cli_anything/ramus/tests/test_full_e2e.py::TestFunctions::test_selectable_by_id_node_and_name PASSED [ 63%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_box_to_box PASSED [ 64%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_border_into_a_box_is_an_input PASSED [ 64%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_box_out_to_the_border_is_an_output PASSED [ 65%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_control_arrives_on_the_top_side PASSED [ 65%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_mechanism_arrives_on_the_bottom_side PASSED [ 66%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_rename_updates_the_arrow_dictionary PASSED [ 67%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_delete_leaves_the_others_resolvable PASSED [ 67%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_connecting_boxes_from_different_diagrams_is_refused PASSED [ 68%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_arrows_survive_a_round_trip PASSED [ 68%]
cli_anything/ramus/tests/test_full_e2e.py::TestArrows::test_arrows_are_listable_per_diagram PASSED [ 69%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_every_image_format_renders_and_verifies[png] PASSED [ 69%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_every_image_format_renders_and_verifies[jpg] PASSED [ 70%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_every_image_format_renders_and_verifies[bmp] PASSED [ 70%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_every_image_format_renders_and_verifies[svg] PASSED [ 71%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_emf_reports_that_it_needs_a_display PASSED [ 71%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_formats_flags_emf_as_display_only PASSED [ 72%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_png_is_a_real_diagram_not_a_blank_page PASSED [ 73%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_adding_a_box_changes_the_render PASSED [ 73%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_box_colour_reaches_the_painter PASSED [ 74%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_svg_contains_drawing_elements PASSED [ 74%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_render_size_is_honoured PASSED [ 75%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_pdf_has_one_page_per_diagram PASSED [ 75%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_pdf_of_a_single_diagram_has_one_page PASSED [ 76%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_export_all_writes_one_file_per_diagram PASSED [ 76%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_rendering_a_leaf_box_is_refused_with_advice PASSED [ 77%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_overwrite_is_required_to_replace_a_file PASSED [ 78%]
cli_anything/ramus/tests/test_full_e2e.py::TestRendering::test_formats_names_the_real_renderer PASSED [ 78%]
cli_anything/ramus/tests/test_full_e2e.py::TestIdl::test_export_of_an_unlabelled_model_succeeds PASSED [ 79%]
cli_anything/ramus/tests/test_full_e2e.py::TestIdl::test_export_of_a_labelled_model_reports_the_upstream_defect PASSED [ 79%]
cli_anything/ramus/tests/test_full_e2e.py::TestIdl::test_import_of_a_context_named_file_succeeds PASSED [ 80%]
cli_anything/ramus/tests/test_full_e2e.py::TestIdl::test_import_of_ramus_own_export_reports_the_mismatch PASSED [ 80%]
cli_anything/ramus/tests/test_full_e2e.py::TestUndoRedo::test_undo_removes_the_last_change_from_disk PASSED [ 81%]
cli_anything/ramus/tests/test_full_e2e.py::TestUndoRedo::test_redo_restores_it PASSED [ 81%]
cli_anything/ramus/tests/test_full_e2e.py::TestUndoRedo::test_history_is_shared_across_sessions_for_the_same_file PASSED [ 82%]
cli_anything/ramus/tests/test_full_e2e.py::TestUndoRedo::test_undo_with_no_history_says_so PASSED [ 82%]
cli_anything/ramus/tests/test_full_e2e.py::TestUndoRedo::test_history_lists_real_snapshot_files PASSED [ 83%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_capture_publishes_a_valid_bundle PASSED [ 84%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_capture_reuses_a_bundle_when_nothing_changed PASSED [ 84%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_force_renders_a_new_bundle PASSED [ 85%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_editing_the_model_produces_a_new_bundle PASSED [ 85%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_latest_returns_the_newest_without_rendering PASSED [ 86%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_model_recipe_renders_every_diagram PASSED [ 86%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_tree_recipe_publishes_inspection_only PASSED [ 87%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_diff_reports_the_structural_change PASSED [ 87%]
cli_anything/ramus/tests/test_full_e2e.py::TestPreviews::test_recipes_are_all_capturable PASSED [ 88%]
cli_anything/ramus/tests/test_full_e2e.py::TestClassifiers::test_create_and_list PASSED [ 89%]
cli_anything/ramus/tests/test_full_e2e.py::TestClassifiers::test_elements_nest PASSED [ 89%]
cli_anything/ramus/tests/test_full_e2e.py::TestClassifiers::test_elements_survive_a_round_trip PASSED [ 90%]
cli_anything/ramus/tests/test_full_e2e.py::TestClassifiers::test_rename_and_delete PASSED [ 90%]
cli_anything/ramus/tests/test_full_e2e.py::TestClassifiers::test_duplicate_classifier_name_is_refused PASSED [ 91%]
cli_anything/ramus/tests/test_full_e2e.py::TestWorkflows::test_order_fulfilment_model_built_and_published PASSED [ 91%]
cli_anything/ramus/tests/test_full_e2e.py::TestWorkflows::test_iterative_refinement_loop PASSED [ 92%]
cli_anything/ramus/tests/test_full_e2e.py::TestWorkflows::test_review_pass_over_an_existing_project PASSED [ 92%]
cli_anything/ramus/tests/test_full_e2e.py::TestWorkflows::test_multi_model_project PASSED [ 93%]
cli_anything/ramus/tests/test_full_e2e.py::TestWorkflows::test_heavy_undo_stress PASSED [ 93%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_help PASSED [ 94%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_version PASSED [ 95%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_doctor_reports_the_backend PASSED [ 95%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_project_new_json PASSED [ 96%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_full_workflow_through_the_installed_command PASSED [ 96%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_auto_save_makes_changes_visible_to_the_next_process PASSED [ 97%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_dry_run_leaves_the_file_untouched PASSED [ 97%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_bad_argument_exits_non_zero_with_a_json_error PASSED [ 98%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_missing_project_is_reported_clearly PASSED [ 98%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_session_status_json PASSED [ 99%]
cli_anything/ramus/tests/test_full_e2e.py::TestCLISubprocess::test_preview_capture_through_the_cli PASSED [100%]
======================= 182 passed in 163.70s (0:02:43) ========================
```

