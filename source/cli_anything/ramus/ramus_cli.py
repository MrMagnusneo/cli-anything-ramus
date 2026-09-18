"""cli-anything-ramus — a command-line interface to Ramus.

Ramus is a Java desktop IDEF0/DFD business-process modeller. This CLI drives the
real application headlessly: model edits go through Ramus's own engine and every
rendered diagram comes out of Ramus's own painter.

Run without a subcommand to enter the REPL. Pass ``--json`` for machine-readable
output.
"""

from __future__ import annotations

import json
import shlex
import sys

import click

from .core import arrow as arrow_mod
from .core import classifier as classifier_mod
from .core import export as export_mod
from .core import function as function_mod
from .core import model as model_mod
from .core import preview as preview_mod
from .core import project as project_mod
from .core.session import Session, get_session
from .utils.ramus_backend import (
    BridgeError,
    JavaNotFound,
    RamusNotFound,
    backend_info,
    shutdown_bridge,
)
from .utils.repl_skin import ReplSkin

VERSION = "1.0.0"

_repl_mode = False
_skin = ReplSkin("ramus", version=VERSION)


# ---------------------------------------------------------------- plumbing


def _json_mode(ctx) -> bool:
    return bool(ctx.obj and ctx.obj.get("json"))


def emit(ctx, data: dict, render=None) -> None:
    """Print a result as JSON, or hand it to a human-readable renderer."""
    if _json_mode(ctx):
        click.echo(json.dumps(data, indent=2, sort_keys=False, default=str))
    elif render is not None:
        render(data)
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def fail(ctx, exc: Exception) -> None:
    """Report a failure the way the caller asked for it, then stop."""
    message = str(exc)
    if _json_mode(ctx):
        payload = {"ok": False, "error": message, "error_type": type(exc).__name__}
        if isinstance(exc, BridgeError) and exc.trace:
            payload["java_trace"] = exc.trace
        click.echo(json.dumps(payload, indent=2), err=True)
    else:
        _skin.error(message)
    if _repl_mode:
        raise click.exceptions.Exit(1)
    sys.exit(1)


def guard(func):
    """Turn backend and engine failures into clean CLI errors."""

    def wrapper(ctx, *args, **kwargs):
        try:
            return func(ctx, *args, **kwargs)
        except click.ClickException:
            raise
        except click.exceptions.Exit:
            raise
        except (BridgeError, RamusNotFound, JavaNotFound, RuntimeError, ValueError,
                OSError) as exc:
            fail(ctx, exc)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _ensure_project(ctx) -> None:
    """Open the project named by ``--project`` if it is not open already."""
    path = ctx.obj.get("project") if ctx.obj else None
    session = get_session()
    if path and session.project_path != str(path):
        session.open_project(path)


# ------------------------------------------------------------------- group


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--json", "use_json", is_flag=True, help="Emit machine-readable JSON.")
@click.option("--project", "project_path", type=str, default=None,
              help="Ramus project file (.rsf) to work on.")
@click.option("--dry-run", "dry_run", is_flag=True, default=False,
              help="Run the command but do not save the project to disk.")
@click.version_option(VERSION, "-V", "--version", prog_name="cli-anything-ramus")
@click.pass_context
def cli(ctx, use_json, project_path, dry_run):
    """Command-line interface to Ramus, the IDEF0 and DFD modeller."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json
    ctx.obj["project"] = project_path
    ctx.obj["dry_run"] = dry_run
    get_session().dry_run = dry_run

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl, project_path=project_path)


@cli.result_callback()
def auto_save_on_exit(result, use_json, project_path, dry_run, **kwargs):
    """Persist one-shot mutations, unless this was a dry run.

    In the REPL the user decides when to save, so this does nothing there.
    """
    if _repl_mode or dry_run:
        return
    session = get_session()
    if session.has_project() and session.modified and session.project_path:
        try:
            session.save_project()
        except (BridgeError, RuntimeError) as exc:
            click.echo(f"Warning: auto-save failed: {exc}", err=True)


# ------------------------------------------------------------------ doctor


@cli.command()
@click.pass_context
@guard
def doctor(ctx):
    """Check that Java and a Ramus build are available."""
    info = backend_info()
    if info["available"]:
        try:
            info.update(get_session().bridge.ping())
        except (BridgeError, RamusNotFound, JavaNotFound) as exc:
            info["available"] = False
            info["problem"] = str(exc)

    def render(data):
        if data["available"]:
            _skin.success("Ramus backend is ready")
            _skin.status("java", data.get("java") or "-")
            _skin.status("javac", data.get("javac") or "-")
            _skin.status("ramus.jar", data.get("ramus_jar") or "-")
            _skin.status("java version", data.get("java_version") or "-")
            _skin.status("bridge", data.get("bridge_classes") or "-")
        else:
            _skin.error("Ramus backend is not usable")
            click.echo(data.get("problem", ""))

    emit(ctx, info, render)
    if not info["available"]:
        sys.exit(1)


# ----------------------------------------------------------------- project


@cli.group()
def project():
    """Create, open, inspect and save Ramus .rsf projects."""


@project.command("new")
@click.argument("path", type=click.Path())
@click.option("--model-name", default="A0", show_default=True, help="Name of the first model.")
@click.option("--type", "diagram_type", type=click.Choice(model_mod.DIAGRAM_TYPES),
              default="idef0", show_default=True, help="Diagram notation for the first model.")
@click.option("--author", default="", help="Author shown in every diagram's title block.")
@click.option("--project-name", "project_name", default="", help="Project name for the title block.")
@click.option("--definition", default="", help="Purpose/definition text for the model.")
@click.option("--used-at", default="", help="'Used at' field for the title block.")
@click.option("--classifier", "classifiers", multiple=True,
              help="Create a classifier with this name (repeatable).")
@click.option("--overwrite", is_flag=True, help="Replace the file if it already exists.")
@click.pass_context
@guard
def project_new(ctx, path, model_name, diagram_type, author, project_name, definition,
                used_at, classifiers, overwrite):
    """Create a new project file."""
    result = project_mod.new_project(
        path, model_name=model_name, diagram_type=diagram_type, author=author,
        project=project_name, definition=definition, used_at=used_at,
        classifiers=list(classifiers), overwrite=overwrite,
    )

    def render(data):
        _skin.success(f"Created {data['path']}")
        _skin.status("size", export_mod.human_size(data.get("file_size", 0)))
        for m in data.get("models", []):
            _skin.status("model", f"{m['name']} ({m['diagram_type']}, id {m['id']})")
        for c in data.get("classifiers", []):
            _skin.status("classifier", f"{c['name']} (id {c['id']})")

    emit(ctx, result, render)


@project.command("info")
@click.pass_context
@guard
def project_info_cmd(ctx):
    """Summarise the open project."""
    _ensure_project(ctx)
    result = project_mod.project_info()

    def render(data):
        _skin.section("Project")
        _skin.status("path", data["path"])
        _skin.status("size", export_mod.human_size(data.get("file_size", 0)))
        _skin.status("modified", "yes" if data.get("modified") else "no")
        if data.get("models"):
            _skin.table(
                ["id", "model", "type", "functions", "arrows"],
                [[str(m["id"]), m["name"], m["diagram_type"],
                  str(m["function_count"]), str(m["arrow_count"])] for m in data["models"]],
            )
        if data.get("classifiers"):
            _skin.table(
                ["id", "classifier", "elements"],
                [[str(c["id"]), c["name"], str(c["element_count"])] for c in data["classifiers"]],
            )

    emit(ctx, result, render)


@project.command("save")
@click.argument("path", type=click.Path(), required=False)
@click.option("--overwrite/--no-overwrite", default=True, show_default=True,
              help="Allow replacing an existing file when saving to a new path.")
@click.pass_context
@guard
def project_save(ctx, path, overwrite):
    """Save the project, optionally to a new path."""
    _ensure_project(ctx)
    result = project_mod.save_project(path, overwrite=overwrite)
    emit(ctx, result, lambda d: _skin.success(
        f"Saved {d['path']} ({export_mod.human_size(d.get('file_size', 0))})"))


@project.command("validate")
@click.argument("path", type=click.Path(exists=True), required=False)
@click.pass_context
@guard
def project_validate(ctx, path):
    """Check a project file opens cleanly and has no broken arrows."""
    if path is None:
        _ensure_project(ctx)
    result = project_mod.validate(path)

    def render(data):
        if data["valid"]:
            _skin.success(f"{data['path']} is a valid Ramus project")
        else:
            _skin.error(f"{data['path']} has problems")
        _skin.status("models", str(data["model_count"]))
        _skin.status("functions", str(data["function_count"]))
        _skin.status("arrows", str(data["arrow_count"]))
        for problem in data["problems"]:
            _skin.error(problem)
        for warning in data["warnings"]:
            _skin.warning(warning)

    emit(ctx, result, render)
    if not result["valid"]:
        sys.exit(1)


@project.command("close")
@click.pass_context
@guard
def project_close(ctx):
    """Close the open project without saving."""
    result = project_mod.close_project()
    emit(ctx, result, lambda d: _skin.info("Closed" if d["closed"] else "No project was open"))


# ------------------------------------------------------------------- model


@cli.group()
def model():
    """IDEF0, DFD and DFDS models inside a project."""


@model.command("list")
@click.pass_context
@guard
def model_list(ctx):
    """List the models in the project."""
    _ensure_project(ctx)
    result = model_mod.list_models()

    def render(data):
        if not data["models"]:
            _skin.warning("No models. Create one with: model create <name>")
            return
        _skin.table(
            ["id", "name", "type", "functions", "arrows", "diagrams"],
            [[str(m["id"]), m["name"], m["diagram_type"], str(m["function_count"]),
              str(m["arrow_count"]), str(m["decomposed_diagrams"])] for m in data["models"]],
        )

    emit(ctx, result, render)


@model.command("create")
@click.argument("name")
@click.option("--type", "diagram_type", type=click.Choice(model_mod.DIAGRAM_TYPES),
              default="idef0", show_default=True)
@click.pass_context
@guard
def model_create(ctx, name, diagram_type):
    """Add a model to the project."""
    _ensure_project(ctx)
    result = model_mod.create_model(name, diagram_type)
    emit(ctx, result, lambda d: _skin.success(f"Created model '{d['name']}' (id {d['id']}, {d['diagram_type']})"))


@model.command("info")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def model_info_cmd(ctx, model_selector):
    """Show a model's counts and title-block options."""
    _ensure_project(ctx)
    result = model_mod.model_info(model_selector)

    def render(data):
        _skin.section(f"Model {data['name']}")
        _skin.status("id", str(data["id"]))
        _skin.status("type", data["diagram_type"])
        _skin.status("functions", str(data["function_count"]))
        _skin.status("arrows", str(data["arrow_count"]))
        _skin.status("diagrams", str(data["decomposed_diagrams"]))
        _skin.status("page size", data.get("page_size", "A4"))
        for key, value in (data.get("options") or {}).items():
            if value:
                _skin.status(key, value)

    emit(ctx, result, render)


@model.command("rename")
@click.argument("name")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def model_rename(ctx, name, model_selector):
    """Rename a model."""
    _ensure_project(ctx)
    result = model_mod.rename_model(name, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Renamed '{d['previous_name']}' to '{d['name']}'"))


@model.command("delete")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.confirmation_option(prompt="Delete this model and everything in it?")
@click.pass_context
@guard
def model_delete(ctx, model_selector):
    """Delete a model and all of its diagrams."""
    _ensure_project(ctx)
    result = model_mod.delete_model(model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Deleted model '{d['name']}'"))


@model.command("tree")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def model_tree_cmd(ctx, model_selector):
    """Print the decomposition tree with IDEF0 node numbers."""
    _ensure_project(ctx)
    result = model_mod.model_tree(model_selector)

    def render(data):
        _skin.section(f"Model {data['model']}")
        for line in model_mod.render_tree(data["root"]):
            click.echo(line)

    emit(ctx, result, render)


@model.command("set-options")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--author", default=None, help="Author for the title block.")
@click.option("--project-name", "project_name", default=None, help="Project name for the title block.")
@click.option("--definition", default=None, help="Purpose/definition text.")
@click.option("--used-at", default=None, help="'Used at' field.")
@click.option("--page-size", default=None, help="Diagram page size, e.g. A4 or A4x2.")
@click.pass_context
@guard
def model_set_options(ctx, model_selector, author, project_name, definition, used_at, page_size):
    """Set the header fields Ramus prints on every diagram."""
    _ensure_project(ctx)
    result = model_mod.set_options(
        model=model_selector, author=author, project=project_name,
        definition=definition, used_at=used_at, page_size=page_size,
    )
    emit(ctx, result, lambda d: _skin.success(f"Updated options for '{d['name']}'"))


# ---------------------------------------------------------------- function


@cli.group()
def function():
    """Activity boxes and the decomposition tree."""


def _function_table(data):
    if not data.get("functions"):
        _skin.warning("No functions.")
        return
    _skin.table(
        ["id", "node", "name", "type", "x", "y", "w", "h", "children"],
        [[str(f["id"]), f["node"], f["name"], f["type"],
          f"{f['bounds']['x']:g}", f"{f['bounds']['y']:g}",
          f"{f['bounds']['width']:g}", f"{f['bounds']['height']:g}",
          str(f["child_count"])] for f in data["functions"]],
    )


@function.command("list")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--parent", default=None, help="Only list children of this box.")
@click.option("--recursive/--direct", default=None,
              help="Whole subtree, or immediate children only.")
@click.pass_context
@guard
def function_list(ctx, model_selector, parent, recursive):
    """List boxes in a model."""
    _ensure_project(ctx)
    emit(ctx, function_mod.list_functions(model_selector, parent, recursive), _function_table)


@function.command("add")
@click.argument("name")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--parent", default=None, help="Parent box (default: the base function A0).")
@click.option("--type", "function_type", type=click.Choice(function_mod.FUNCTION_TYPES),
              default="complex", show_default=True)
@click.option("--x", type=float, default=None, help="Left edge, in diagram units (canvas is 800x444).")
@click.option("--y", type=float, default=None, help="Top edge, in diagram units.")
@click.option("--width", type=float, default=None, help="Box width.")
@click.option("--height", type=float, default=None, help="Box height.")
@click.pass_context
@guard
def function_add(ctx, name, model_selector, parent, function_type, x, y, width, height):
    """Add a box. Adding children to a box is what gives it a diagram."""
    _ensure_project(ctx)
    result = function_mod.add_function(
        name, model=model_selector, parent=parent, type=function_type,
        x=x, y=y, width=width, height=height,
    )
    emit(ctx, result, lambda d: _skin.success(f"Added {d['node']} '{d['name']}' (id {d['id']})"))


@function.command("decompose")
@click.argument("parent")
@click.argument("names", nargs=-1, required=True)
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--type", "function_type", type=click.Choice(function_mod.FUNCTION_TYPES),
              default="complex", show_default=True)
@click.pass_context
@guard
def function_decompose(ctx, parent, names, model_selector, function_type):
    """Give a box its own diagram by adding several children at once."""
    _ensure_project(ctx)
    result = function_mod.decompose(parent, list(names), model=model_selector, type=function_type)

    def render(data):
        _skin.success(f"Decomposed {parent} into {data['count']} boxes")
        for child in data["created"]:
            _skin.status(child["node"], child["name"])

    emit(ctx, result, render)


@function.command("info")
@click.argument("function_ref")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_info_cmd(ctx, function_ref, model_selector):
    """Show one box in detail."""
    _ensure_project(ctx)
    result = function_mod.function_info(function_ref, model_selector)

    def render(data):
        _skin.section(f"{data['node']}  {data['name']}")
        _skin.status("id", str(data["id"]))
        _skin.status("type", data["type"])
        b = data["bounds"]
        _skin.status("bounds", f"x={b['x']:g} y={b['y']:g} w={b['width']:g} h={b['height']:g}")
        _skin.status("colours", f"fill {data['background']} / text {data['foreground']}")
        if data.get("font"):
            f = data["font"]
            _skin.status("font", f"{f['family']} {f['size']}{' bold' if f['bold'] else ''}")
        _skin.status("parent", data.get("parent_name") or "-")
        _skin.status("children", str(data["child_count"]))
        _skin.status("arrows on its diagram", str(data.get("arrows_on_own_diagram", 0)))

    emit(ctx, result, render)


@function.command("rename")
@click.argument("function_ref")
@click.argument("name")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_rename(ctx, function_ref, name, model_selector):
    """Rename a box. Renaming A0 renames the model."""
    _ensure_project(ctx)
    result = function_mod.rename_function(function_ref, name, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Renamed '{d['previous_name']}' to '{d['name']}'"))


@function.command("move")
@click.argument("function_ref")
@click.option("--x", type=float, default=None)
@click.option("--y", type=float, default=None)
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_move(ctx, function_ref, x, y, model_selector):
    """Move a box on its diagram."""
    _ensure_project(ctx)
    result = function_mod.move_function(function_ref, x, y, model_selector)
    emit(ctx, result, lambda d: _skin.success(
        f"{d['node']} now at x={d['bounds']['x']:g} y={d['bounds']['y']:g}"))


@function.command("resize")
@click.argument("function_ref")
@click.option("--width", type=float, default=None)
@click.option("--height", type=float, default=None)
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_resize(ctx, function_ref, width, height, model_selector):
    """Resize a box."""
    _ensure_project(ctx)
    result = function_mod.resize_function(function_ref, width, height, model_selector)
    emit(ctx, result, lambda d: _skin.success(
        f"{d['node']} now {d['bounds']['width']:g}x{d['bounds']['height']:g}"))


@function.command("set-color")
@click.argument("function_ref")
@click.option("--background", default=None, help="Fill colour, #rrggbb.")
@click.option("--foreground", default=None, help="Text colour, #rrggbb.")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_set_color(ctx, function_ref, background, foreground, model_selector):
    """Set a box's fill and text colours."""
    _ensure_project(ctx)
    result = function_mod.set_color(function_ref, background, foreground, model_selector)
    emit(ctx, result, lambda d: _skin.success(
        f"{d['node']} fill {d['background']} / text {d['foreground']}"))


@function.command("set-font")
@click.argument("function_ref")
@click.option("--family", default=None, help="Font family.")
@click.option("--size", type=int, default=None, help="Font size in points.")
@click.option("--bold/--no-bold", default=None)
@click.option("--italic/--no-italic", default=None)
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_set_font(ctx, function_ref, family, size, bold, italic, model_selector):
    """Set a box's label font."""
    _ensure_project(ctx)
    result = function_mod.set_font(function_ref, family, size, bold, italic, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"{d['node']} font updated"))


@function.command("set-type")
@click.argument("function_ref")
@click.argument("function_type", type=click.Choice(function_mod.FUNCTION_TYPES))
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_set_type(ctx, function_ref, function_type, model_selector):
    """Change a box's activity type."""
    _ensure_project(ctx)
    result = function_mod.set_type(function_ref, function_type, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"{d['node']} is now '{d['type']}'"))


@function.command("delete")
@click.argument("function_ref")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def function_delete(ctx, function_ref, model_selector):
    """Delete a box and its subtree."""
    _ensure_project(ctx)
    result = function_mod.delete_function(function_ref, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Deleted {d['node']} '{d['name']}'"))


# ------------------------------------------------------------------- arrow


@cli.group()
def arrow():
    """Arrows between boxes, and between a box and the diagram border."""


@arrow.command("list")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--diagram", default=None, help="Only arrows on this box's diagram.")
@click.pass_context
@guard
def arrow_list(ctx, model_selector, diagram):
    """List arrows."""
    _ensure_project(ctx)
    result = arrow_mod.list_arrows(model_selector, diagram)

    def render(data):
        if not data["arrows"]:
            _skin.warning("No arrows.")
            return
        _skin.table(
            ["id", "label", "from", "to", "diagram"],
            [[str(a["id"]), a["name"] or "(unlabelled)",
              arrow_mod.describe_endpoint(a["from"]),
              arrow_mod.describe_endpoint(a["to"]),
              a.get("diagram_node") or "-"] for a in data["arrows"]],
        )

    emit(ctx, result, render)


@arrow.command("add")
@click.option("--from", "source", required=True,
              help="Source box (id, node or name), or the word 'border'.")
@click.option("--to", "target", required=True,
              help="Target box (id, node or name), or the word 'border'.")
@click.option("--name", default=None, help="Arrow label.")
@click.option("--from-side", type=click.Choice(arrow_mod.SIDES), default="output",
              show_default=True, help="Side of the source the arrow leaves from.")
@click.option("--to-side", type=click.Choice(arrow_mod.SIDES), default="input",
              show_default=True, help="Side of the target the arrow arrives at.")
@click.option("--diagram", default=None,
              help="Diagram to draw on (default: the model's top-level A0 diagram).")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def arrow_add(ctx, source, target, name, from_side, to_side, diagram, model_selector):
    """Draw an arrow.

    IDEF0 side names: input (left), control (top), mechanism (bottom),
    output (right).
    """
    _ensure_project(ctx)
    result = arrow_mod.add_arrow(
        source, target, name=name, model=model_selector, diagram=diagram,
        from_side=from_side, to_side=to_side,
    )

    def render(data):
        _skin.success(
            f"Added arrow {data['id']}: {arrow_mod.describe_endpoint(data['from'])}"
            f" -> {arrow_mod.describe_endpoint(data['to'])}"
            + (f"  [{data['name']}]" if data.get("name") else "")
        )

    emit(ctx, result, render)


@arrow.command("rename")
@click.argument("arrow_id")
@click.argument("name")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def arrow_rename(ctx, arrow_id, name, model_selector):
    """Relabel an arrow."""
    _ensure_project(ctx)
    result = arrow_mod.rename_arrow(arrow_id, name, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Arrow {d['id']} is now labelled '{d['name']}'"))


@arrow.command("delete")
@click.argument("arrow_id")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def arrow_delete(ctx, arrow_id, model_selector):
    """Delete an arrow."""
    _ensure_project(ctx)
    result = arrow_mod.delete_arrow(arrow_id, model_selector)
    emit(ctx, result, lambda d: _skin.success(f"Deleted arrow {d['id']}"))


@arrow.command("streams")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.pass_context
@guard
def arrow_streams(ctx, model_selector):
    """List the model's arrow dictionary — every label defined so far."""
    _ensure_project(ctx)
    result = arrow_mod.list_streams(model_selector)

    def render(data):
        if not data["streams"]:
            _skin.warning("No arrow labels defined yet.")
            return
        _skin.table(["id", "label"], [[str(s["id"]), s["name"]] for s in data["streams"]])

    emit(ctx, result, render)


# -------------------------------------------------------------- classifier


@cli.group()
def classifier():
    """Classifiers — the project's reference data."""


@classifier.command("list")
@click.pass_context
@guard
def classifier_list(ctx):
    """List classifiers."""
    _ensure_project(ctx)
    result = classifier_mod.list_classifiers()

    def render(data):
        if not data["classifiers"]:
            _skin.warning("No classifiers. Create one with: classifier create <name>")
            return
        _skin.table(
            ["id", "name", "elements"],
            [[str(c["id"]), c["name"], str(c["element_count"])] for c in data["classifiers"]],
        )

    emit(ctx, result, render)


@classifier.command("create")
@click.argument("name")
@click.pass_context
@guard
def classifier_create(ctx, name):
    """Create a classifier."""
    _ensure_project(ctx)
    result = classifier_mod.create_classifier(name)
    emit(ctx, result, lambda d: _skin.success(f"Created classifier '{d['name']}' (id {d['id']})"))


@classifier.command("rename")
@click.argument("classifier_ref")
@click.argument("name")
@click.pass_context
@guard
def classifier_rename(ctx, classifier_ref, name):
    """Rename a classifier."""
    _ensure_project(ctx)
    result = classifier_mod.rename_classifier(classifier_ref, name)
    emit(ctx, result, lambda d: _skin.success(f"Renamed '{d['previous_name']}' to '{d['name']}'"))


@classifier.command("delete")
@click.argument("classifier_ref")
@click.confirmation_option(prompt="Delete this classifier and all of its elements?")
@click.pass_context
@guard
def classifier_delete(ctx, classifier_ref):
    """Delete a classifier and its elements."""
    _ensure_project(ctx)
    result = classifier_mod.delete_classifier(classifier_ref)
    emit(ctx, result, lambda d: _skin.success(f"Deleted classifier '{d['name']}'"))


@classifier.command("show")
@click.argument("classifier_ref")
@click.pass_context
@guard
def classifier_show(ctx, classifier_ref):
    """Show a classifier's attributes and element tree."""
    _ensure_project(ctx)
    result = classifier_mod.show_classifier(classifier_ref)

    def render(data):
        _skin.section(f"Classifier {data['name']}")
        _skin.status("id", str(data["id"]))
        _skin.status("elements", str(data["element_count"]))
        for line in classifier_mod.render_elements(data.get("elements", [])):
            click.echo(line)

    emit(ctx, result, render)


@cli.group()
def element():
    """Elements inside a classifier."""


@element.command("list")
@click.argument("classifier_ref")
@click.pass_context
@guard
def element_list(ctx, classifier_ref):
    """List a classifier's elements."""
    _ensure_project(ctx)
    result = classifier_mod.list_elements(classifier_ref)

    def render(data):
        if not data["elements"]:
            _skin.warning("No elements.")
            return
        _skin.table(
            ["id", "name", "parent"],
            [[str(e["id"]), e["name"], str(e["parent_id"] or "-")] for e in data["elements"]],
        )

    emit(ctx, result, render)


@element.command("add")
@click.argument("classifier_ref")
@click.argument("name")
@click.option("--parent", default=None, help="Nest under this element.")
@click.pass_context
@guard
def element_add(ctx, classifier_ref, name, parent):
    """Add an element to a classifier."""
    _ensure_project(ctx)
    result = classifier_mod.add_element(classifier_ref, name, parent)
    emit(ctx, result, lambda d: _skin.success(f"Added '{d['name']}' to {d['classifier']} (id {d['id']})"))


@element.command("rename")
@click.argument("classifier_ref")
@click.argument("element_ref")
@click.argument("name")
@click.pass_context
@guard
def element_rename(ctx, classifier_ref, element_ref, name):
    """Rename an element."""
    _ensure_project(ctx)
    result = classifier_mod.rename_element(classifier_ref, element_ref, name)
    emit(ctx, result, lambda d: _skin.success(f"Renamed '{d['previous_name']}' to '{d['name']}'"))


@element.command("delete")
@click.argument("classifier_ref")
@click.argument("element_ref")
@click.pass_context
@guard
def element_delete(ctx, classifier_ref, element_ref):
    """Delete an element."""
    _ensure_project(ctx)
    result = classifier_mod.delete_element(classifier_ref, element_ref)
    emit(ctx, result, lambda d: _skin.success(f"Deleted '{d['name']}'"))


# ------------------------------------------------------------------ export


@cli.group()
def export():
    """Render diagrams and write interchange files."""


@export.command("formats")
@click.pass_context
@guard
def export_formats(ctx):
    """List the formats this Ramus build can produce."""
    _ensure_project(ctx)
    result = export_mod.formats()

    def render(data):
        _skin.status("raster", ", ".join(data["raster"]))
        _skin.status("vector", ", ".join(data["vector"]))
        _skin.status("interchange", ", ".join(data["interchange"]))
        _skin.status("renderer", data["renderer"])

    emit(ctx, result, render)


@export.command("diagram")
@click.argument("path", type=click.Path())
@click.option("--diagram", default=None, help="Which box's diagram (default: A0).")
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--format", "image_format", type=click.Choice(export_mod.IMAGE_FORMATS), default=None,
              help="Output format (default: inferred from the file extension).")
@click.option("--width", type=int, default=None, help="Render width in pixels.")
@click.option("--height", type=int, default=None, help="Render height in pixels.")
@click.option("--overwrite", is_flag=True, help="Replace the file if it exists.")
@click.pass_context
@guard
def export_diagram(ctx, path, diagram, model_selector, image_format, width, height, overwrite):
    """Render one diagram to an image."""
    _ensure_project(ctx)
    result = export_mod.export_diagram(
        path, diagram=diagram, model=model_selector, format=image_format,
        width=width, height=height, overwrite=overwrite,
    )
    check = export_mod.verify_output(result["output"], result["format"])
    result["verified"] = check["valid"]
    result["verification"] = check["detail"]

    def render(data):
        _skin.success(f"Rendered {data['diagram_node']} {data['diagram']} -> {data['output']}")
        _skin.status("size", export_mod.human_size(data["file_size"]))
        _skin.status("verified", "yes" if data["verified"] else f"NO ({data['verification']})")

    emit(ctx, result, render)
    if not check["valid"]:
        sys.exit(1)


@export.command("all")
@click.argument("directory", type=click.Path())
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--format", "image_format", type=click.Choice(export_mod.IMAGE_FORMATS),
              default="png", show_default=True)
@click.option("--width", type=int, default=None)
@click.option("--height", type=int, default=None)
@click.option("--overwrite", is_flag=True)
@click.pass_context
@guard
def export_all(ctx, directory, model_selector, image_format, width, height, overwrite):
    """Render every diagram in a model into a directory."""
    _ensure_project(ctx)
    result = export_mod.export_all(
        directory, model=model_selector, format=image_format,
        width=width, height=height, overwrite=overwrite,
    )
    for output in result["outputs"]:
        check = export_mod.verify_output(output["output"], output["format"])
        output["verified"] = check["valid"]

    def render(data):
        _skin.success(f"Rendered {data['count']} diagrams into {data['directory']}")
        _skin.table(
            ["node", "diagram", "file", "size", "ok"],
            [[o["diagram_node"], o["diagram"], o["output"].rsplit("/", 1)[-1],
              export_mod.human_size(o["file_size"]), "yes" if o["verified"] else "NO"]
             for o in data["outputs"]],
        )

    emit(ctx, result, render)
    if not all(o["verified"] for o in result["outputs"]):
        sys.exit(1)


@export.command("pdf")
@click.argument("path", type=click.Path())
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--diagram", default=None, help="Export a single diagram instead of the whole model.")
@click.option("--width", type=int, default=None, help="Page width in points.")
@click.option("--height", type=int, default=None, help="Page height in points.")
@click.option("--overwrite", is_flag=True)
@click.pass_context
@guard
def export_pdf(ctx, path, model_selector, diagram, width, height, overwrite):
    """Render a model to PDF, one page per diagram."""
    _ensure_project(ctx)
    result = export_mod.export_pdf(
        path, model=model_selector, diagram=diagram,
        width=width, height=height, overwrite=overwrite,
    )
    check = export_mod.verify_output(result["output"], "pdf")
    result["verified"] = check["valid"]
    result["verification"] = check["detail"]

    def render(data):
        _skin.success(f"Wrote {data['output']} ({data['page_count']} pages)")
        _skin.status("size", export_mod.human_size(data["file_size"]))
        _skin.status("verified", "yes" if data["verified"] else f"NO ({data['verification']})")
        for page in data["pages"]:
            _skin.status(f"page {page['page']}", f"{page['diagram_node']} {page['diagram']}")

    emit(ctx, result, render)
    if not check["valid"]:
        sys.exit(1)


@export.command("idl")
@click.argument("path", type=click.Path())
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--encoding", default="UTF-8", show_default=True)
@click.option("--overwrite", is_flag=True)
@click.pass_context
@guard
def export_idl(ctx, path, model_selector, encoding, overwrite):
    """Export a model to IDL, the IDEF0 interchange format.

    Ramus's own IDL writer crashes on arrows that show a label; the CLI reports
    that clearly instead of dumping a stack trace. See the README.
    """
    _ensure_project(ctx)
    result = export_mod.export_idl(path, model=model_selector, encoding=encoding, overwrite=overwrite)
    emit(ctx, result, lambda d: _skin.success(
        f"Wrote {d['output']} ({export_mod.human_size(d['file_size'])})"))


@cli.group("import")
def import_group():
    """Bring outside models into the project."""


@import_group.command("idl")
@click.argument("path", type=click.Path(exists=True))
@click.option("--name", default=None, help="Name for the imported model.")
@click.option("--encoding", default="cp1251", show_default=True,
              help="Encoding of the IDL file.")
@click.pass_context
@guard
def import_idl(ctx, path, name, encoding):
    """Import an IDL file as a new model."""
    _ensure_project(ctx)
    result = export_mod.import_idl(path, name=name, encoding=encoding)
    emit(ctx, result, lambda d: _skin.success(
        f"Imported '{d['name']}' ({d['function_count']} functions, {d['arrow_count']} arrows)"))


# ----------------------------------------------------------------- preview


@cli.group()
def preview():
    """Publish preview bundles of the project's visual state.

    These commands produce bundles; read them with `cli-hub previews ...`.
    """


@preview.command("recipes")
@click.pass_context
@guard
def preview_recipes(ctx):
    """List the available preview recipes."""
    result = preview_mod.list_recipes()

    def render(data):
        _skin.table(
            ["recipe", "what it publishes"],
            [[r["name"], r["description"]] for r in data["recipes"]],
        )
        _skin.info(data["live_note"])

    emit(ctx, result, render)


@preview.command("capture")
@click.option("--recipe", type=click.Choice(sorted(preview_mod.RECIPES)), default="diagram",
              show_default=True)
@click.option("--model", "model_selector", default=None, help="Model id or name.")
@click.option("--diagram", default=None, help="Which box's diagram, for the 'diagram' recipe.")
@click.option("--width", type=int, default=None)
@click.option("--height", type=int, default=None)
@click.option("--root-dir", default=None, help="Where to write bundles.")
@click.option("--force", is_flag=True, help="Re-render even if an identical bundle exists.")
@click.pass_context
@guard
def preview_capture(ctx, recipe, model_selector, diagram, width, height, root_dir, force):
    """Render a preview bundle for the open project."""
    _ensure_project(ctx)
    result = preview_mod.capture(
        recipe=recipe, model=model_selector, diagram=diagram,
        width=width, height=height, root_dir=root_dir, force=force,
    )
    emit(ctx, result, _render_bundle)


@preview.command("latest")
@click.option("--recipe", default=None, help="Restrict to one recipe.")
@click.option("--root-dir", default=None)
@click.pass_context
@guard
def preview_latest(ctx, recipe, root_dir):
    """Show the newest existing bundle. Renders nothing."""
    _ensure_project(ctx)
    emit(ctx, preview_mod.latest(recipe=recipe, root_dir=root_dir), _render_bundle)


@preview.command("diff")
@click.argument("baseline", type=click.Path(exists=True))
@click.option("--recipe", type=click.Choice(sorted(preview_mod.RECIPES)), default="diagram",
              show_default=True)
@click.option("--model", "model_selector", default=None)
@click.option("--diagram", default=None)
@click.option("--width", type=int, default=None)
@click.option("--height", type=int, default=None)
@click.option("--root-dir", default=None)
@click.pass_context
@guard
def preview_diff(ctx, baseline, recipe, model_selector, diagram, width, height, root_dir):
    """Compare the open project with another .rsf and publish the comparison."""
    _ensure_project(ctx)
    result = preview_mod.diff(
        baseline, recipe=recipe, model=model_selector, diagram=diagram,
        width=width, height=height, root_dir=root_dir,
    )
    emit(ctx, result, _render_bundle)


def _render_bundle(data):
    _skin.success(f"Bundle {data['bundle_id']}")
    _skin.status("kind", data["bundle_kind"])
    _skin.status("directory", data["_bundle_dir"])
    _skin.status("status", data.get("status", "ok"))
    if data.get("_cached"):
        _skin.info("Reused an existing bundle; the project has not changed.")
    for artifact in data.get("artifacts", []):
        _skin.status(artifact["kind"], f"{artifact['path']}  {artifact['label']}")
    for warning in data.get("warnings", []) or []:
        _skin.warning(warning)
    _skin.hint(f"Inspect it with: cli-hub previews inspect {data['_bundle_dir']}")


# ----------------------------------------------------------------- session


@cli.group()
def session():
    """Session state: undo, redo, history."""


@session.command("status")
@click.pass_context
@guard
def session_status(ctx):
    """Show what is open and how much history is available."""
    _ensure_project(ctx)
    result = get_session().status()

    def render(data):
        _skin.section("Session")
        _skin.status("project", data["project_path"] or "(none open)")
        _skin.status("modified", "yes" if data["modified"] else "no")
        _skin.status("undo available", str(data["undo_available"]))
        _skin.status("redo available", str(data["redo_available"]))
        if data.get("model_count") is not None:
            _skin.status("models", str(data["model_count"]))
            _skin.status("functions", str(data["function_count"]))
            _skin.status("arrows", str(data["arrow_count"]))

    emit(ctx, result, render)


@session.command("undo")
@click.pass_context
@guard
def session_undo(ctx):
    """Undo the last change."""
    _ensure_project(ctx)
    result = get_session().undo()
    emit(ctx, result, lambda d: _skin.success(
        f"Undone. {d['undo_available']} more undo, {d['redo_available']} redo available."))


@session.command("redo")
@click.pass_context
@guard
def session_redo(ctx):
    """Redo the change that was undone."""
    _ensure_project(ctx)
    result = get_session().redo()
    emit(ctx, result, lambda d: _skin.success(
        f"Redone. {d['undo_available']} undo, {d['redo_available']} redo available."))


@session.command("history")
@click.pass_context
@guard
def session_history(ctx):
    """List the undo and redo snapshots."""
    _ensure_project(ctx)
    result = get_session().history()

    def render(data):
        _skin.section("Undo stack (newest last)")
        if not data["undo"]:
            _skin.info("empty")
        for entry in data["undo"]:
            _skin.status(export_mod.human_size(entry["size"]), entry["path"])
        _skin.section("Redo stack")
        if not data["redo"]:
            _skin.info("empty")
        for entry in data["redo"]:
            _skin.status(export_mod.human_size(entry["size"]), entry["path"])

    emit(ctx, result, render)


@session.command("list")
@click.pass_context
@guard
def session_list(ctx):
    """List saved sessions across projects."""
    result = {"sessions": Session.list_sessions()}

    def render(data):
        if not data["sessions"]:
            _skin.info("No sessions yet.")
            return
        _skin.table(
            ["session", "project", "exists", "undo", "redo"],
            [[s["session_id"], s["project_path"] or "-", "yes" if s["project_exists"] else "no",
              str(s["undo_available"]), str(s["redo_available"])] for s in data["sessions"]],
        )

    emit(ctx, result, render)


# -------------------------------------------------------------------- REPL


REPL_HELP = {
    "project": "new / info / save / validate / close",
    "model": "list / create / info / rename / delete / tree / set-options",
    "function": "list / add / decompose / info / rename / move / resize / set-color / set-font / set-type / delete",
    "arrow": "list / add / rename / delete / streams",
    "classifier": "list / create / rename / delete / show",
    "element": "list / add / rename / delete",
    "export": "formats / diagram / all / pdf / idl",
    "import": "idl",
    "preview": "recipes / capture / latest / diff",
    "session": "status / undo / redo / history / list",
    "doctor": "check that Java and Ramus are available",
    "open <file>": "open a project",
    "save": "save the open project",
    "help": "show this list",
    "quit": "leave the REPL",
}


@cli.command()
@click.option("--project", "project_path", type=click.Path(exists=True), default=None,
              help="Open this project on startup.")
@click.pass_context
def repl(ctx, project_path):
    """Start the interactive session (the default when no command is given)."""
    global _repl_mode
    _repl_mode = True
    ctx.ensure_object(dict)
    ctx.obj.setdefault("json", False)
    ctx.obj["project"] = None  # The REPL manages the open project itself.

    _skin.print_banner()

    info = backend_info()
    if not info["available"]:
        _skin.error("Ramus backend is not usable")
        click.echo(info.get("problem", ""))
        _skin.hint("Fix the above, then run 'doctor' to re-check.")
    else:
        _skin.info(f"Using {info['ramus_jar']}")

    session_obj = get_session()
    if project_path:
        try:
            opened = session_obj.open_project(project_path)
            _skin.success(f"Opened {opened['path']}")
        except (BridgeError, RamusNotFound, JavaNotFound, RuntimeError) as exc:
            _skin.error(str(exc))

    pt_session = _skin.create_prompt_session()
    while True:
        try:
            name = ""
            if session_obj.has_project():
                name = str(session_obj.project_path).rsplit("/", 1)[-1]
            line = _skin.get_input(pt_session, project_name=name, modified=session_obj.modified)
        except (EOFError, KeyboardInterrupt):
            break
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line in ("help", "?"):
            _skin.help(REPL_HELP)
            continue
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            _skin.error(f"Could not parse the command: {exc}")
            continue

        # A couple of shorthands that make an interactive session pleasant.
        if parts[0] == "open" and len(parts) == 2:
            try:
                opened = session_obj.open_project(parts[1])
                _skin.success(f"Opened {opened['path']}")
            except (BridgeError, RuntimeError, OSError) as exc:
                _skin.error(str(exc))
            continue
        if parts == ["save"]:
            parts = ["project", "save"]

        try:
            cli.main(args=parts, standalone_mode=False, obj=dict(ctx.obj), prog_name="")
        except click.exceptions.Exit:
            pass
        except click.ClickException as exc:
            _skin.error(exc.format_message())
        except (BridgeError, RamusNotFound, JavaNotFound, RuntimeError, ValueError, OSError) as exc:
            _skin.error(str(exc))

    if session_obj.has_project() and session_obj.modified:
        _skin.warning("The project has unsaved changes. Use 'save' before quitting to keep them.")
    _skin.print_goodbye()
    _repl_mode = False


def main():
    try:
        cli(obj={})
    finally:
        shutdown_bridge()


if __name__ == "__main__":
    main()
