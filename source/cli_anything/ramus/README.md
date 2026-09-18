# cli-anything-ramus

A command-line interface to **[Ramus](https://github.com/Vitaliy-Yakovchuk/ramus)**,
the Java desktop modeller for IDEF0, DFD and DFDS business-process diagrams.

This is an interface *to* Ramus, not a reimplementation of it. Model edits go
through Ramus's own engine classes and every rendered diagram comes out of
`com.ramussoft.pb.print.PIDEF0painter` — the same painter the Ramus GUI uses for
File ▸ Export and for printing. A `.rsf` written here opens in the GUI, and a
`.rsf` written by the GUI opens here.

---

## Requirements

| | |
|---|---|
| **Ramus** | a built `ramus.jar` — **required**, the CLI cannot work without it |
| **JDK 11+** | both `java` and `javac`; a JRE alone is not enough |
| **Python** | 3.10 or newer |

`javac` is needed because the CLI compiles a small JSON bridge against *your*
`ramus.jar` the first time it runs, and caches the result under
`~/.cli-anything-ramus/bridge/`. That is what keeps it working against any Ramus
build rather than one pinned version.

### Getting Ramus

Ramus ships no binary release, so build the fat jar once:

```bash
git clone https://github.com/Vitaliy-Yakovchuk/ramus
cd ramus
./gradlew :local-client:shadowJar          # writes local-client/build/libs/ramus.jar
export RAMUS_JAR=$PWD/local-client/build/libs/ramus.jar
```

The CLI finds the jar from, in order: `$RAMUS_JAR`, `$RAMUS_HOME`, the usual
install locations (`/opt/ramus`, `/usr/share/ramus`, `/Applications/Ramus.app`,
…), and finally by walking up from the working directory — so running inside a
built checkout needs no configuration at all.

### Installing the CLI

```bash
cd ramus/agent-harness
pip install -e .
cli-anything-ramus doctor          # confirms java, javac and the jar
```

---

## Usage

```bash
cli-anything-ramus                       # interactive REPL
cli-anything-ramus --help                # one-shot commands
cli-anything-ramus --json <command>      # machine-readable output
```

`--project <file.rsf>` selects the project a one-shot command works on. Changes
are saved automatically when the command succeeds; `--dry-run` runs the command
and prints the result without writing anything.

### A model from nothing

```bash
P=order.rsf
cli-anything-ramus project new $P --model-name "Fulfil customer order" \
    --author "Analyst" --project-name "Order fulfilment" --classifier Roles

cli-anything-ramus --project $P function add "Receive order"
cli-anything-ramus --project $P function add "Assemble goods"
cli-anything-ramus --project $P function add "Ship goods"

# IDEF0 sides: input (left), control (top), mechanism (bottom), output (right)
cli-anything-ramus --project $P arrow add --from border --from-side input \
    --to "Receive order"  --name "Customer order"
cli-anything-ramus --project $P arrow add --from "Receive order" \
    --to "Assemble goods" --name "Confirmed order"
cli-anything-ramus --project $P arrow add --from "Assemble goods" \
    --to "Ship goods"     --name "Packed goods"
cli-anything-ramus --project $P arrow add --from "Ship goods" \
    --to border --to-side output --name "Delivered goods"

# Decomposing a box is what gives it its own diagram
cli-anything-ramus --project $P function decompose "Assemble goods" \
    "Pick parts" "Build unit" "Test unit"

cli-anything-ramus --project $P model tree
cli-anything-ramus --project $P export all ./diagrams --overwrite
cli-anything-ramus --project $P export pdf order.pdf --overwrite
```

`model tree` prints:

```
A0  Fulfil customer order
├─ A1  Receive order
├─ A2  Assemble goods
│  ├─ A21  Pick parts
│  ├─ A22  Build unit
│  └─ A23  Test unit
└─ A3  Ship goods
```

### Addressing things

Boxes and arrows can be named three ways, and every listing shows all of them:

- numeric id — always unique, best for scripts
- IDEF0 node number — `A0`, `A2`, `A21`
- name — convenient, and rejected with a clear message when ambiguous

`--model` is only needed when a project holds more than one model; with a single
model it is inferred, and with several the error message names the candidates.

---

## Command groups

| Group | Commands |
|-------|----------|
| `project` | `new`, `info`, `save`, `validate`, `close` |
| `model` | `list`, `create`, `info`, `rename`, `delete`, `tree`, `set-options` |
| `function` | `list`, `add`, `decompose`, `info`, `rename`, `move`, `resize`, `set-color`, `set-font`, `set-type`, `delete` |
| `arrow` | `list`, `add`, `rename`, `delete`, `streams` |
| `classifier` | `list`, `create`, `rename`, `delete`, `show` |
| `element` | `list`, `add`, `rename`, `delete` |
| `export` | `formats`, `diagram`, `all`, `pdf`, `idl` |
| `import` | `idl` |
| `preview` | `recipes`, `capture`, `latest`, `diff` |
| `session` | `status`, `undo`, `redo`, `history`, `list` |
| `doctor` | check that Java and Ramus are usable |

### Coordinates

The Ramus drawing area is **800 × 444** model units. New boxes are placed on the
classic IDEF0 staircase, sized so six of them fit on one page; pass `--x/--y` and
`--width/--height` to place them yourself.

---

## Undo and redo

Ramus's own undo stack lives inside a running JVM and is never written to the
`.rsf`, so it cannot survive between one-shot commands. This CLI keeps its own
history instead, as real `.rsf` snapshots written by Ramus and stored under
`~/.cli-anything-ramus/sessions/`, fifty levels deep. Undo reopens a snapshot,
so it restores exactly the file Ramus would have written.

History is keyed by project path, which means a chain of separate one-shot
commands shares one history — `session undo` works even though each command ran
in its own process.

```bash
cli-anything-ramus --project order.rsf session status
cli-anything-ramus --project order.rsf session undo
cli-anything-ramus --project order.rsf session redo
```

---

## Previews

A preview is a `preview-bundle/v1` directory holding diagrams rendered by Ramus
plus an inspection summary — a checkpoint you or an agent can look at between
edits. Publishing and viewing are separate roles:

```bash
# Publish, with this CLI
cli-anything-ramus --project order.rsf preview recipes
cli-anything-ramus --project order.rsf preview capture --recipe model
cli-anything-ramus --project order.rsf preview latest
cli-anything-ramus --project order.rsf preview diff baseline.rsf

# Inspect, with cli-hub
cli-hub previews inspect <bundle-dir>
cli-hub previews html    <bundle-dir>
cli-hub previews watch   <bundle-dir>
```

Recipes: `diagram` (one diagram as PNG + SVG), `model` (every decomposed diagram),
`tree` (inspection JSON only — the cheapest way to check state between edits).

Bundles are content-addressed by the project file, so capturing again with
nothing changed reuses the existing bundle; `--force` re-renders.

There is no live-preview mode, and that is deliberate: Ramus has no incremental
render pipeline, so every capture is a full re-render of the saved project.
Static capture plus `diff` covers the same ground without pretending to stream.

---

## Known Ramus limitations

These are defects and constraints in Ramus itself, reachable from the GUI too.
The CLI reports each one precisely rather than failing obscurely, and the test
suite asserts the reports so a future Ramus fix will be noticed.

**EMF export needs a display.** Ramus writes EMF through FreeHEP, whose
`EMFGraphics2D.writeHeader` asks the toolkit for the screen size — a question no
headless JVM can answer. `export formats` lists `emf` under `needs_display`. Use
PNG, JPEG, BMP, SVG or PDF, or run with a display and
`CLI_ANYTHING_RAMUS_HEADLESS=0`.

**IDL export fails on labelled arrows.** `IDLExporter.printSegments` constructs
`new PStringBounder(null)` and `PStringBounder.getStringBounds` then dereferences
that null, so exporting any model whose arrows show a label throws. Models with
unlabelled arrows export fine. The Ramus GUI fails the same way.

**IDL import cannot read Ramus's own export.** The importer pre-registers the
IDEF0 context diagram under the name `A-0`, but the exporter writes
`DIAGRAM GRAPHIC A0`. Import works on files that follow the `A-0` convention;
Ramus's own output has to have that one line changed first.

**Undo does not reproduce a byte-identical file.** Ramus stamps a fresh revision
date on every save, so an undone project is semantically identical but not
byte-identical. Diagrams render identically; only the file hash differs.

---

## How it works

```
ramus_cli.py  ──►  core/*.py  ──►  utils/ramus_backend.py
   Click CLI        domain          finds ramus.jar, compiles and runs the bridge
   and REPL         modules                     │
                                                ▼
                              java -cp ramus.jar:bridge com.cliany.ramus.RamusBridge
                                    newline-delimited JSON over stdin/stdout
                                                │
                                                ▼
                              com.ramussoft.*  — the real Ramus engine
                              PIDEF0painter    — the real Ramus renderer
```

One JVM is started per CLI process and reused for every operation in it, so a
REPL session or a one-shot command's whole chain of work pays the JVM start-up
cost once. Each mutation runs inside a Ramus user transaction and is rolled back
if it fails, so a rejected command leaves the model untouched.

The bridge sources live in `utils/java/com/cliany/ramus/` and ship with the
package.

---

## Running the tests

```bash
export RAMUS_JAR=/path/to/ramus.jar
pip install -e .
CLI_ANYTHING_FORCE_INSTALLED=1 python3 -m pytest cli_anything/ramus/tests/ -v -s
```

`test_core.py` needs no Ramus. `test_full_e2e.py` requires it and will fail
rather than skip if it is missing. `-s` prints every artifact path so the
rendered diagrams can be opened and looked at. See
[`tests/TEST.md`](tests/TEST.md) for the plan and the recorded results.

---

## Environment variables

| Variable | Meaning |
|----------|---------|
| `RAMUS_JAR` | Path to `ramus.jar`. Checked first. |
| `RAMUS_HOME` | Directory containing `ramus.jar` or a built checkout. |
| `JAVA_HOME` | Where to find `java` and `javac`. |
| `CLI_ANYTHING_RAMUS_HOME` | Where sessions, snapshots and the compiled bridge live. Default `~/.cli-anything-ramus`. |
| `CLI_ANYTHING_RAMUS_HEADLESS` | `0` runs the JVM with a display, which is what EMF export needs. Default `1`. |
| `CLI_ANYTHING_FORCE_INSTALLED` | `1` makes the test suite require the installed command. |
