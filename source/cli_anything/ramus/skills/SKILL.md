---
name: >-
  cli-anything-ramus
description: >-
  Build, edit and render IDEF0, DFD and DFDS business-process models from the
  command line by driving the real Ramus desktop application headlessly. Use for
  process modelling, activity decomposition, arrow/flow modelling, and exporting
  diagrams to PNG, JPEG, BMP, SVG or PDF from .rsf project files.
---

# cli-anything-ramus

A command-line interface to [Ramus](https://github.com/Vitaliy-Yakovchuk/ramus),
a Java desktop modeller for IDEF0, DFD and DFDS business-process diagrams.

This drives the real application: model edits go through Ramus's own engine and
every rendered diagram comes from `PIDEF0painter`, the painter the Ramus GUI uses
for its own export and printing. Files written here open in the GUI and vice
versa.

## Installation

Check first — it may already be installed:

```bash
cli-anything-ramus --json doctor      # {"available": true, "ramus_jar": "..."}
```

If the command is missing or `available` is false, install from the
`cli-anything-ramus` bundle by running its `install.sh`, which sets up the CLI,
the Ramus engine and this skill, then verifies them. The bundle's
`AGENT_INSTALL.md` describes every step.

**Prerequisites:**

- Python 3.10+
- A **JDK 11 or newer** (`java` *and* `javac`; a JRE is not enough — the CLI
  compiles a small bridge against `ramus.jar` on first use)
- **`ramus.jar`** — shipped in the bundle and installed to
  `~/.local/share/ramus/ramus.jar`, where the CLI finds it without any
  environment variable. To use another build, set `RAMUS_JAR`.

If `doctor` reports `available: false`, the `problem` field contains the exact
fix. Do not attempt other commands until it is true.

## Basic usage

```bash
cli-anything-ramus --help                          # command reference
cli-anything-ramus                                 # interactive REPL
cli-anything-ramus --json <command>                # machine-readable output
cli-anything-ramus --project model.rsf <command>   # act on a project
cli-anything-ramus --dry-run --project m.rsf ...   # run without saving
```

One-shot commands auto-save on success. `--dry-run` runs the command, prints the
result, and leaves the file byte-identical.

## The domain in one minute

An IDEF0 model is a tree of **activity boxes** ("functions"). The root box is
`A0`; its children are `A1`, `A2`, `A3`; their children are `A11`, `A12`, and so
on. **Giving a box children is what creates that box's diagram** — there is no
separate "create diagram" step, and only decomposed boxes can be rendered.

**Arrows** connect a side of one box to a side of another, or to the diagram
border. Each side has a fixed meaning:

| Word | Box side | Meaning |
|------|----------|---------|
| `input` | left | what the activity consumes |
| `control` | top | what governs or constrains it |
| `mechanism` | bottom | who or what performs it |
| `output` | right | what it produces |

`left`, `top`, `bottom`, `right` are accepted as aliases. An endpoint of the
literal word `border` means the arrow enters or leaves the diagram.

**Classifiers** are the project's reference lists (roles, documents, systems),
each holding a tree of elements.

## Command groups

### `project` — `.rsf` lifecycle

| Command | Description |
|---------|-------------|
| `project new PATH` | Create a project. `--model-name`, `--type`, `--author`, `--project-name`, `--definition`, `--used-at`, `--classifier` (repeatable), `--overwrite` |
| `project info` | Models, counts, classifiers |
| `project save [PATH]` | Save, or save-as |
| `project validate [PATH]` | Check the file opens and has no broken arrows |
| `project close` | Close without saving |

### `model` — IDEF0 / DFD / DFDS models

| Command | Description |
|---------|-------------|
| `model list` | All models with their notation and counts |
| `model create NAME` | `--type idef0\|dfd\|dfds` |
| `model info` | Counts and title-block options |
| `model rename NAME` | Rename |
| `model delete` | Delete a model and its diagrams |
| `model tree` | Decomposition tree with node numbers |
| `model set-options` | `--author`, `--project-name`, `--definition`, `--used-at`, `--page-size` |

### `function` — activity boxes

| Command | Description |
|---------|-------------|
| `function list` | `--parent`, `--recursive/--direct` |
| `function add NAME` | `--parent`, `--type`, `--x`, `--y`, `--width`, `--height` |
| `function decompose PARENT CHILD...` | Add several children at once — this creates the parent's diagram |
| `function info REF` | One box in detail |
| `function rename REF NAME` | Rename (renaming `A0` renames the model) |
| `function move REF --x --y` | Reposition |
| `function resize REF --width --height` | Resize |
| `function set-color REF` | `--background`, `--foreground` as `#rrggbb` |
| `function set-font REF` | `--family`, `--size`, `--bold/--no-bold`, `--italic/--no-italic` |
| `function set-type REF TYPE` | `complex`, `process`, `subprocess`, `operation`, `action`, `external`, `datastore`, `role` |
| `function delete REF` | Delete a box and its subtree |

### `arrow` — flows

| Command | Description |
|---------|-------------|
| `arrow list` | `--diagram` to restrict to one diagram |
| `arrow add --from X --to Y` | `--name`, `--from-side`, `--to-side`, `--diagram`. Either endpoint may be `border` |
| `arrow rename ID NAME` | Relabel |
| `arrow delete ID` | Delete |
| `arrow streams` | The model's arrow dictionary |

### `classifier` / `element` — reference data

| Command | Description |
|---------|-------------|
| `classifier list` / `create NAME` / `rename REF NAME` / `delete REF` / `show REF` | Classifiers |
| `element list CLS` / `add CLS NAME [--parent]` / `rename CLS REF NAME` / `delete CLS REF` | Elements, which may nest |

### `export` / `import`

| Command | Description |
|---------|-------------|
| `export formats` | What this build can render |
| `export diagram PATH` | One diagram. `--diagram`, `--format`, `--width`, `--height`, `--overwrite` |
| `export all DIR` | Every decomposed diagram |
| `export pdf PATH` | One page per diagram |
| `export idl PATH` | IDEF0 interchange format (see limitations) |
| `import idl PATH` | Import an IDL file as a new model |

### `preview` — visual checkpoints

| Command | Description |
|---------|-------------|
| `preview recipes` | `diagram`, `model`, `tree` |
| `preview capture` | Publish a bundle. `--recipe`, `--diagram`, `--root-dir`, `--force` |
| `preview latest` | Newest existing bundle; renders nothing |
| `preview diff BASELINE.rsf` | Compare against another project |

### `session` — undo and redo

| Command | Description |
|---------|-------------|
| `session status` | What is open, and how much history exists |
| `session undo` / `session redo` | Step back and forward |
| `session history` | The snapshot stacks |
| `session list` | Sessions across projects |

## Addressing things

Boxes and arrows accept three forms, and every listing prints all of them:

- **numeric id** — always unique; prefer this in scripts
- **node number** — `A0`, `A2`, `A21`
- **name** — convenient; rejected with a clear message when ambiguous

`--model` is only needed when a project holds more than one model. With one it is
inferred; with several, the error names the candidates.

## Examples

### Build a process model from nothing

```bash
P=order.rsf
cli-anything-ramus project new $P --model-name "Fulfil customer order" \
    --author Analyst --project-name "Order fulfilment" --classifier Roles

cli-anything-ramus --project $P function add "Receive order"
cli-anything-ramus --project $P function add "Assemble goods"
cli-anything-ramus --project $P function add "Ship goods"

cli-anything-ramus --project $P arrow add --from border --from-side input \
    --to "Receive order" --name "Customer order"
cli-anything-ramus --project $P arrow add --from "Receive order" \
    --to "Assemble goods" --name "Confirmed order"
cli-anything-ramus --project $P arrow add --from "Assemble goods" \
    --to "Ship goods" --name "Packed goods"
cli-anything-ramus --project $P arrow add --from "Ship goods" \
    --to border --to-side output --name "Delivered goods"
cli-anything-ramus --project $P arrow add --from border --from-side control \
    --to "Assemble goods" --to-side control --name "Build specification"
```

### Decompose an activity into its own diagram

```bash
cli-anything-ramus --project $P function decompose "Assemble goods" \
    "Pick parts" "Build unit" "Test unit"
cli-anything-ramus --project $P arrow add --diagram "Assemble goods" \
    --from "Pick parts" --to "Build unit" --name Parts
cli-anything-ramus --project $P model tree
```

### Render

```bash
cli-anything-ramus --project $P export diagram a0.png --overwrite
cli-anything-ramus --project $P export all ./diagrams --overwrite
cli-anything-ramus --project $P export pdf order.pdf --overwrite
```

### Inspect an unfamiliar project

```bash
cli-anything-ramus --json --project other.rsf project info
cli-anything-ramus --json --project other.rsf model tree
cli-anything-ramus --json --project other.rsf arrow list
```

### Publish a preview, then inspect it

```bash
# Publish with this CLI
cli-anything-ramus --json --project $P preview capture --recipe model

# Inspect with cli-hub (a separate, read-only viewer)
cli-hub previews inspect <bundle-dir>
cli-hub previews html    <bundle-dir>
cli-hub previews watch   <bundle-dir>
```

## Preview support

Preview mode: **static and diff**. There is no live mode, deliberately — Ramus
has no incremental render pipeline, so every capture is a full re-render of the
saved project and static capture plus `diff` covers the same ground honestly.

Artifacts are **PNG and SVG images plus inspection JSON**, all produced by the
real Ramus renderer. No GUI window is ever screen-scraped.

Producer and consumer are separate roles: `cli-anything-ramus preview ...`
publishes bundles; `cli-hub previews ...` reads them. `cli-hub` is not a render
path.

Bundles are content-addressed by the project file, so capturing twice with
nothing changed reuses the bundle (`"_cached": true`); `--force` re-renders.
`--json` returns `_bundle_dir`, `_manifest_path`, `_summary_path` and a relative
`path` for each artifact.

## For AI agents

1. **Run `--json doctor` first.** Everything else depends on the backend being
   usable, and the `problem` field states the exact fix.
2. **Always pass `--json`** for parseable output. Errors become a JSON object on
   stderr (`{"ok": false, "error": ..., "error_type": ...}`) with a non-zero exit.
3. **Use numeric ids from a listing** when scripting; names are ambiguous and the
   CLI will say so rather than guessing.
4. **Use absolute paths** for project and output files.
5. **Decompose before rendering.** Only a box with children has a diagram;
   rendering a leaf box is refused with an explanation.
6. **`preview capture --recipe tree`** is the cheapest way to check state between
   edits — inspection JSON with no rendering.
7. **`--dry-run`** shows what a command would do without writing.
8. **Verify exports.** Every export result carries `"verified": true` after a
   magic-byte check; treat `false` as a failure even though the file exists.
9. **Undo works across separate one-shot commands**, because history is keyed by
   project path.

## Output formats

| Format | Notes |
|--------|-------|
| `png`, `jpg`, `bmp` | Raster, via `PIDEF0painter` |
| `svg` | Vector, via Batik |
| `pdf` | One page per diagram, via iText |
| `emf` | **Needs a display** — see limitations |
| `idl` | IDEF0 interchange — see limitations |

## Known Ramus limitations

These are defects and constraints in Ramus itself, reachable from the GUI too.
The CLI reports each precisely; do not treat them as CLI bugs, and do not retry.

- **EMF export needs a display.** Ramus writes EMF through FreeHEP, which asks
  the toolkit for the screen size — unanswerable headlessly. Use PNG/SVG/PDF, or
  set `CLI_ANYTHING_RAMUS_HEADLESS=0` on a machine with a display.
- **IDL export fails on labelled arrows.** `IDLExporter` passes `null` to
  `PStringBounder`, which then dereferences it. Models with unlabelled arrows
  export fine. Prefer PNG/SVG/PDF for sharing.
- **IDL import cannot read Ramus's own export.** The importer expects the context
  section to be named `A-0`; the exporter writes `A0`. Files from other IDEF0
  tools that follow the `A-0` convention import fine.
- **Undo does not produce a byte-identical file.** Ramus stamps a fresh revision
  date on every save, so an undone project is semantically identical but hashes
  differently. Diagrams render identically.

## Environment variables

| Variable | Meaning |
|----------|---------|
| `RAMUS_JAR` | Path to `ramus.jar`. Checked first. |
| `RAMUS_HOME` | Directory containing `ramus.jar` or a built checkout. |
| `JAVA_HOME` | Where to find `java` and `javac`. |
| `CLI_ANYTHING_RAMUS_HOME` | Sessions, snapshots and the compiled bridge. Default `~/.cli-anything-ramus`. |
| `CLI_ANYTHING_RAMUS_HEADLESS` | `0` runs with a display, which EMF export needs. Default `1`. |

## More information

- Full documentation: `README.md` in the package
- Test coverage and results: `tests/TEST.md`
- Codebase analysis and design rationale: `RAMUS.md`
- Methodology: `HARNESS.md` in the cli-anything-plugin

## Version

1.0.0
