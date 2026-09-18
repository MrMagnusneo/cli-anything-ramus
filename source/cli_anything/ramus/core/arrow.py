"""Arrows — the flows between boxes on a diagram.

IDEF0 gives each side of a box a meaning, and this module uses those names:

===========  ========  ==================================================
Side word    Box side  Meaning
===========  ========  ==================================================
``input``    left      what the activity consumes
``control``  top       what constrains or governs it
``mechanism``bottom    who or what performs it
``output``   right     what it produces
===========  ========  ==================================================

An endpoint may also be the literal word ``border``, for an arrow that enters or
leaves the diagram rather than connecting two boxes on it.
"""

from __future__ import annotations

from .session import get_session

SIDES = ("input", "control", "mechanism", "output", "left", "top", "bottom", "right")
BORDER = "border"


def _mutate(op: str, **args) -> dict:
    session = get_session()
    session.require_project()
    session.snapshot()
    result = session.bridge.call(op, **args)
    session.mark_modified()
    return result


def list_arrows(model: str | None = None, diagram: str | None = None) -> dict:
    session = get_session()
    session.require_project()
    return session.bridge.call("arrow.list", model=model, diagram=diagram)


def list_streams(model: str | None = None) -> dict:
    """The model's arrow dictionary: every label defined so far."""
    session = get_session()
    session.require_project()
    return session.bridge.call("arrow.streams", model=model)


def add_arrow(
    source: str,
    target: str,
    name: str | None = None,
    model: str | None = None,
    diagram: str | None = None,
    from_side: str = "output",
    to_side: str = "input",
) -> dict:
    """Draw an arrow on ``diagram`` between two boxes, or a box and the border.

    Both endpoints cannot be the border: such an arrow would carry nothing.
    """
    for side, label in ((from_side, "--from-side"), (to_side, "--to-side")):
        if side not in SIDES:
            raise ValueError(f"Unknown {label} '{side}'. Use one of: {', '.join(SIDES)}")
    if source.lower() == BORDER and target.lower() == BORDER:
        raise ValueError("At least one endpoint must be a function; border-to-border arrows are not meaningful")
    return _mutate(
        "arrow.add",
        model=model,
        diagram=diagram,
        **{"from": source, "to": target},
        from_side=from_side,
        to_side=to_side,
        name=name,
    )


def rename_arrow(arrow_id: str, name: str, model: str | None = None) -> dict:
    return _mutate("arrow.rename", model=model, id=arrow_id, name=name)


def delete_arrow(arrow_id: str, model: str | None = None) -> dict:
    return _mutate("arrow.delete", model=model, id=arrow_id)


def describe_endpoint(endpoint: dict) -> str:
    """One-line rendering of an arrow endpoint for terminal output."""
    kind = endpoint.get("kind")
    side = endpoint.get("side", "?")
    if kind == "function":
        return f"{endpoint.get('node', '?')} {endpoint.get('function', '?')} ({side})"
    if kind == "border":
        return f"border ({side})"
    return "unset"
