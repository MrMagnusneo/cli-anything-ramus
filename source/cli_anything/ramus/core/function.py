"""Functions — the activity boxes of an IDEF0 or DFD diagram.

Every box lives in a model's decomposition tree. Adding children to a box is
what creates that box's diagram, which is why ``function add --parent A1`` is
the decomposition operation.

Boxes are addressed by numeric id, IDEF0 node number (``A0``, ``A12``), or name.
"""

from __future__ import annotations

from .session import get_session

FUNCTION_TYPES = (
    "complex",
    "process",
    "subprocess",
    "operation",
    "action",
    "external",
    "datastore",
    "role",
)


def _mutate(op: str, **args) -> dict:
    session = get_session()
    session.require_project()
    session.snapshot()
    result = session.bridge.call(op, **args)
    session.mark_modified()
    return result


def _read(op: str, **args) -> dict:
    session = get_session()
    session.require_project()
    return session.bridge.call(op, **args)


def list_functions(model: str | None = None, parent: str | None = None,
                   recursive: bool | None = None) -> dict:
    return _read("function.list", model=model, parent=parent, recursive=recursive)


def add_function(
    name: str,
    model: str | None = None,
    parent: str | None = None,
    type: str = "complex",
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict:
    """Add a box under ``parent`` (the base function A0 when not given)."""
    if type not in FUNCTION_TYPES:
        raise ValueError(f"Unknown function type '{type}'. Use one of: {', '.join(FUNCTION_TYPES)}")
    return _mutate(
        "function.add",
        model=model,
        parent=parent,
        name=name,
        type=type,
        x=x,
        y=y,
        width=width,
        height=height,
    )


def function_info(function: str, model: str | None = None) -> dict:
    return _read("function.info", model=model, function=function)


def rename_function(function: str, name: str, model: str | None = None) -> dict:
    """Rename a box. Renaming A0 renames the model, as it does in the GUI."""
    return _mutate("function.rename", model=model, function=function, name=name)


def move_function(function: str, x: float | None = None, y: float | None = None,
                  model: str | None = None) -> dict:
    if x is None and y is None:
        raise ValueError("Pass --x and/or --y")
    return _mutate("function.move", model=model, function=function, x=x, y=y)


def resize_function(function: str, width: float | None = None, height: float | None = None,
                    model: str | None = None) -> dict:
    if width is None and height is None:
        raise ValueError("Pass --width and/or --height")
    return _mutate("function.resize", model=model, function=function, width=width, height=height)


def set_color(function: str, background: str | None = None, foreground: str | None = None,
              model: str | None = None) -> dict:
    if background is None and foreground is None:
        raise ValueError("Pass --background and/or --foreground")
    return _mutate(
        "function.set-color", model=model, function=function,
        background=background, foreground=foreground,
    )


def set_font(function: str, family: str | None = None, size: int | None = None,
             bold: bool | None = None, italic: bool | None = None,
             model: str | None = None) -> dict:
    if family is None and size is None and bold is None and italic is None:
        raise ValueError("Pass at least one of --family, --size, --bold/--no-bold, --italic/--no-italic")
    return _mutate(
        "function.set-font", model=model, function=function,
        family=family, size=size, bold=bold, italic=italic,
    )


def set_type(function: str, type: str, model: str | None = None) -> dict:
    if type not in FUNCTION_TYPES:
        raise ValueError(f"Unknown function type '{type}'. Use one of: {', '.join(FUNCTION_TYPES)}")
    return _mutate("function.set-type", model=model, function=function, type=type)


def delete_function(function: str, model: str | None = None) -> dict:
    return _mutate("function.delete", model=model, function=function)


def decompose(parent: str, names: list[str], model: str | None = None,
              type: str = "complex") -> dict:
    """Give a box its own diagram by adding several children at once.

    IDEF0 recommends three to six boxes per diagram; the default staircase
    layout is sized for exactly that.
    """
    if not names:
        raise ValueError("Pass at least one child name")
    created = [
        add_function(name, model=model, parent=parent, type=type)
        for name in names
    ]
    return {
        "parent": parent,
        "created": created,
        "count": len(created),
        "model": created[0].get("model"),
    }
