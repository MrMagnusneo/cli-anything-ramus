# RAMUS.md — codebase analysis and CLI design

The software-specific SOP for `cli-anything-ramus`, following the phases in
`HARNESS.md`. This records what the Ramus codebase actually offers, which parts
the CLI drives, and why the design is shaped the way it is.

Source analysed: <https://github.com/Vitaliy-Yakovchuk/ramus> at `73a6001`.

---

## Phase 1 — Codebase analysis

### What Ramus is

A Java Swing desktop application for **IDEF0**, **DFD** and **DFDS**
business-process modelling: activity boxes joined by arrows, decomposed into
child diagrams, with a classifier system for reference data. It is a Gradle
multi-project build of 28 modules.

### The backend engine

Presentation and logic are cleanly separated, and the logic half is usable
without a display.

| Layer | Module | Key types |
|-------|--------|-----------|
| Data engine | `core`, `common` | `Engine`, `IEngine`, `Qualifier`, `Attribute`, `Element`, `FileIEngineImpl` |
| Database / persistence | `data-framework-common`, `database-storage` | `MemoryDatabase`, `FileDatabaseFactory`, `RowSet`, `Row`, H2 in-memory + JDBC |
| IDEF0 semantics | `idef0-core` | `IDEF0Plugin`, the `F_*` attribute registry, `IDEF0PluginProvider` |
| IDEF0 model API | `idef0-common` | `DataPlugin`, `Function`, `Sector`, `Stream`, `Crosspoint`, `NDataPluginFactory` |
| Rendering | `idef0-common` | `PIDEF0painter`, `MovingArea`, `SectorRefactor`, `PaintSector`, `ArrowPainter` |
| Interchange | `idef0-common` | `IDLExporter`, `IDLImporter` |
| PDF | `print-to-pdf` | iText `PdfGraphics2D` over `PIDEF0painter` |
| GUI | `gui-*`, `local-client` | Swing — **not used by the CLI** |

The critical discovery is that the whole model and render path is reachable
headlessly. `ramus-core-demo/RSFViewer` shows the entry point in miniature:

```java
Database db = FileDatabaseFactory.createDatabase(new File("model.rsf"));
Engine engine = db.getEngine(null);
```

`MovingArea` extends `JPanel` but is never realised as a window, so it
constructs and lays out fine under `-Djava.awt.headless=true`. That is what
makes a genuine CLI possible rather than a screen-scraper.

### The data model

- A project is a **`.rsf` file**: a ZIP archive (`PK\x03\x04`) written by
  `FileIEngineImpl.saveToFile`, holding the serialised engine database.
- A **model** is a `Qualifier` carrying the IDEF0 visual attributes, installed by
  `IDEF0Plugin.installFunctionAttributes`. `IDEF0Plugin.isFunction(q)` identifies
  one; `getBaseQualifiers(engine)` lists them.
- A **function** (activity box) is an `Element` of that qualifier, wrapped as
  `NFunction`, carrying bounds (`FRectangle`), colours, font, type and status.
  The decomposition tree is the element hierarchy; the `RowSet` root is the
  A0 base function, whose name *is* the model qualifier's name.
- An **arrow** is a `Sector` with two `NSectorBorder` endpoints, each bound
  either to a function and a side, or to a diagram border and a side. Its label
  is a **`Stream`** row in the model's arrow dictionary. Its geometry is a list
  of `SectorPointPersistent` referencing shared `Ordinate` objects, persisted
  into the parent function's `sectorData` blob by `SectorRefactor`.
- A **classifier** is any other qualifier; its elements form a `RowSet` tree.

### GUI actions mapped to API calls

| GUI action | API |
|------------|-----|
| File ▸ New project | `NewProjectDialog.finish()` — create qualifier, add the shared Name attribute, register it for auto-add, `installFunctionAttributes`, add to the model tree, set `ProjectOptions` |
| File ▸ Open / Save | `FileDatabaseFactory.createDatabase(file)` / `((FileIEngineImpl) engine.getDeligate()).saveToFile(file)` |
| Add a box | `DataPlugin.createFunction(parent, type)` then `setName` / `setBounds` |
| Draw an arrow | `createSector`, set both borders, `commit`, attach a `Stream`, then `new PaintSector(...)` + `SectorRefactor.addSector` + `savePointOrdinates` + `lightSaveToFunction` |
| Box properties | `Function.setBackground/setForeground/setFont/setType/setBounds` |
| Model ▸ Properties | `Function.setProjectOptions(ProjectOptions)` |
| File ▸ Export image | `new PIDEF0painter(function, size, dataPlugin).writeToStream(out, FORMAT)` |
| File ▸ Print (PDF) | `PdfGraphics2D` + `PIDEF0painter.paint(g, 0, 0)` |
| File ▸ Export/Import IDL | `DataPlugin.exportToIDL` / `importFromIDL` |
| Edit ▸ Undo/Redo | `Journaled.undoUserTransaction()` / `redoUserTransaction()` |

### Existing CLI tools

**None.** Ramus has no command-line interface, no headless mode and no scripting
API. `ramus-core-demo` contains two Swing viewer samples, not tools. This is why
the harness has to build its own bridge rather than wrap an existing binary.

### The command/undo system

`JournaledEngine` implements `Journaled`: `startUserTransaction`,
`commitUserTransaction`, `rollbackUserTransaction`, `undoUserTransaction`,
`redoUserTransaction`. Crucially, `MemoryDatabase.getJournalDirectoryName`
returns `null`, so **the journal is in-memory only and is never written to the
`.rsf`**. It gives us transactional safety inside one process, but it cannot be
the CLI's undo feature across processes.

---

## Phase 2 — CLI architecture

### Interaction model

Both, as `HARNESS.md` recommends: a Click subcommand CLI for scripting and
agents, and a REPL (the default with no subcommand) for interactive work.

### The backend bridge

Ramus offers no CLI to shell out to, so the harness compiles one:
`utils/java/com/cliany/ramus/*.java`, built against the user's own `ramus.jar`
on first use and cached under `~/.cli-anything-ramus/bridge/<fingerprint>/`.
The fingerprint covers both the bridge sources and the jar, so pointing at a
different Ramus build recompiles automatically.

The bridge is a long-lived JVM speaking newline-delimited JSON on stdin/stdout:

```
{"id": 3, "op": "function.add", "args": {"name": "Assemble"}}
{"id": 3, "ok": true, "result": {"id": 7, "node": "A2", ...}}
```

Design points worth recording:

- **stdout is reserved for protocol frames.** Ramus prints to `System.out` in
  several places, so `main` captures the real stdout first and redirects
  `System.out` to stderr. Without this the protocol would be corrupted by the
  application's own logging.
- **One JVM per CLI process.** Loading the engine costs ~2 s, so it is paid once
  per REPL session or per one-shot command, not once per operation.
- **Every mutation is a Ramus user transaction**, rolled back on failure, so a
  rejected command leaves the model exactly as it was.
- **No JSON library.** Ramus ships none, and adding a jar to the classpath would
  risk conflicting with the application's own dependencies, so the bridge
  carries a ~380-line reader/writer (`Json.java`).
- **Whole numbers survive the round trip.** JSON numbers arrive as `Double`, so
  an id sent as `14` would otherwise be read back as `"14.0"` and match nothing.
  `Json.text` renders integral values without a decimal point.

### Command groups

Chosen to mirror the application's own domains rather than the bridge's:

| Group | Domain |
|-------|--------|
| `project` | `.rsf` lifecycle: new, info, save, validate, close |
| `model` | IDEF0/DFD/DFDS models, the tree, title-block options |
| `function` | activity boxes, decomposition, geometry, appearance |
| `arrow` | flows, including to and from the diagram border |
| `classifier` / `element` | the reference-data layer |
| `export` / `import` | rendering and interchange |
| `preview` | publishing visual checkpoints |
| `session` | undo, redo, history |
| `doctor` | is the backend usable at all |

### State model

The `.rsf` file is the state. The Python `Session` holds the open project path, a
modified flag, and an undo history; the live engine holds the model.

**Undo is file snapshots, not Ramus's journal.** Ramus's journal is in-memory,
so it cannot serve one-shot commands that each run in their own process. Instead
the session asks Ramus to write a snapshot `.rsf` before each mutation, fifty
deep, under `~/.cli-anything-ramus/sessions/<id>/snapshots/`. Undo reopens a
snapshot, so it restores exactly the file Ramus would have written rather than a
reconstruction. History is keyed by project path, so a chain of separate one-shot
commands shares one history. `project.save-copy` exists precisely so a snapshot
does not retarget the engine's idea of which file it is editing.

### Output format

Every command supports `--json`; without it, output goes through `ReplSkin` as
tables and status lines. Errors in JSON mode are a JSON object on stderr with a
non-zero exit, carrying the Java trace when there is one.

### Auto-save and `--dry-run`

Mutations mark the session modified; the group's `result_callback` saves on the
way out unless `--dry-run` was given. Under `--dry-run` the session also skips
snapshotting, so a dry run leaves the project file byte-identical — which the
test suite checks.

---

## Phase 3 — Implementation notes

### Arrow creation, headlessly

The one genuinely hard part. Arrow geometry is produced by
`PointBuilder`/`PaintSector`, which normally run inside a live `MovingArea`.
Headless creation works like this:

```java
MovingArea area = new MovingArea(dp, diagram);   // a JPanel, never realised
area.setActiveFunction(diagram);                 // loads existing arrows
SectorRefactor refactor = area.getRefactor();

Sector s = dp.createSector();
s.setFunction(diagram);
s.getStart().setFunctionA(source); s.getStart().setFunctionTypeA(RIGHT); s.getStart().commit();
s.getEnd().setFunctionA(target);   s.getEnd().setFunctionTypeA(LEFT);    s.getEnd().commit();
s.setStream(stream, ReplaceStreamType.CHILDREN); // the label

PaintSector ps = new PaintSector(s, startPoint, endPoint, area);
refactor.addSector(ps);
ps.savePointOrdinates();
refactor.lightSaveToFunction();
```

One correction is needed for border endpoints. `Point.getType()` falls back to
`getBorderType()`, which dereferences the `PaintSector` back-reference that
`PaintSector` only installs *after* construction — so `PointBuilder` hits a null
while laying out the very sector that would supply it. The bridge sets the point
type explicitly for border endpoints, to exactly the value Ramus derives itself:
a line leaving a left or right border runs horizontally (`TYPE_X`), one leaving
top or bottom runs vertically (`TYPE_Y`).

### The rendering gap

`HARNESS.md` warns that a CLI can edit a project file and then render through
something that ignores the edits. That trap is avoided here by construction:
there is no second renderer. `PIDEF0painter` reads the live model, so anything
the CLI changes is by definition what gets drawn. The test suite still proves it
rather than assuming it — adding a box must change the PNG bytes, and colouring
a box must change the pixels it occupies.

### IDEF0 vocabulary at the CLI surface

Sides are named the way IDEF0 names them, with geometric aliases accepted:

| Word | Side | Meaning |
|------|------|---------|
| `input` | left | what the activity consumes |
| `control` | top | what governs it |
| `mechanism` | bottom | who or what performs it |
| `output` | right | what it produces |

Boxes are addressable by id, IDEF0 node number (`A0`, `A21`) or name, and every
listing prints all three.

---

## Phase 4–6 — Testing

See [`cli_anything/ramus/tests/TEST.md`](cli_anything/ramus/tests/TEST.md) for
the plan and the full recorded results: **182 tests, 100% passing**, of which 94
drive the real engine and 11 drive the installed command through `subprocess`.

Render checks decode the PNG in pure Python (no image dependency) and assert ink
coverage, colour counts and pixel changes, because "the command exited 0" is not
evidence that anything was drawn.

---

## Upstream defects found

Found while building and testing this harness. All three are in Ramus itself and
reachable from the GUI; the CLI reports each precisely and the test suite asserts
the reports, so a future fix will be noticed rather than silently diverged from.

1. **`IDLExporter` cannot export labelled arrows.**
   `IDLExporter.printSegments` (line ~248) constructs `new PStringBounder(null)`,
   and `PStringBounder.getStringBounds` (line ~51) then dereferences that null
   as `area.textPaintCache`. Any model whose arrows show a label throws an NPE.
   *Fix would be:* give `printSegments` the `MovingArea` it already has in scope,
   or make `getStringBounds` fall back to `PStringBounder.FONT_CONTEXT`.

2. **`IDLImporter` cannot read `IDLExporter`'s output.**
   The importer seeds its lookup with `hash.put("A-0", base)` and expects the
   first `DIAGRAM GRAPHIC` section to use that name; the exporter writes
   `DIAGRAM GRAPHIC A0`. `getFunction()` then indexes an empty `Vector` at
   `size() - 1` and throws `ArrayIndexOutOfBoundsException`.
   *Fix would be:* accept both names, or emit an `A-0` context section.

3. **EMF export cannot run headlessly.**
   Not a Ramus bug as such: FreeHEP's `EMFGraphics2D.writeHeader` asks the
   toolkit for the screen size, which throws `HeadlessException`. Ramus inherits
   the constraint. The CLI lists EMF under `needs_display` and offers
   `CLI_ANYTHING_RAMUS_HEADLESS=0` for machines that have one.

---

## Applying this pattern elsewhere

| | |
|---|---|
| Backend CLI | none — a purpose-built JSON bridge over `ramus.jar` |
| Native format | `.rsf` (ZIP archive of the engine database) |
| System package | build from source: `./gradlew :local-client:shadowJar` |
| How the CLI uses it | drives `com.ramussoft.*` headlessly; renders through `PIDEF0painter` |

The transferable lesson: when a GUI application ships no CLI at all, look for the
seam between its engine and its Swing layer. Ramus has a clean one, and a demo
class in the repository shows exactly where it is. A small compiled bridge across
that seam is a far better foundation than automating the GUI, and it costs about
1,900 lines of Java.
