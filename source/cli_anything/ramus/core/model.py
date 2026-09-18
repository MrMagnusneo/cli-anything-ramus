"""Models — one IDEF0, DFD or DFDS decomposition tree each.

In Ramus a model is a "function qualifier": a classifier whose elements are the
activity boxes, carrying the IDEF0 visual attributes. A project can hold any
number of them.
"""

from __future__ import annotations

from .session import get_session

DIAGRAM_TYPES = ("idef0", "dfd", "dfds")


def _mutate(op: str, **args) -> dict:
    """Run a change: snapshot for undo first, then mark the session dirty."""
    session = get_session()
    session.require_project()
    session.snapshot()
    result = session.bridge.call(op, **args)
    session.mark_modified()
    return result


def list_models() -> dict:
    session = get_session()
    session.require_project()
    return session.bridge.call("model.list")


def create_model(name: str, diagram_type: str = "idef0") -> dict:
    if diagram_type not in DIAGRAM_TYPES:
        raise ValueError(f"Unknown diagram type '{diagram_type}'. Use one of: {', '.join(DIAGRAM_TYPES)}")
    return _mutate("model.create", name=name, diagram_type=diagram_type)


def model_info(model: str | None = None) -> dict:
    session = get_session()
    session.require_project()
    return session.bridge.call("model.info", model=model)


def rename_model(name: str, model: str | None = None) -> dict:
    return _mutate("model.rename", model=model, name=name)


def delete_model(model: str | None = None) -> dict:
    return _mutate("model.delete", model=model)


def model_tree(model: str | None = None) -> dict:
    """The decomposition tree, as nested nodes with IDEF0 node numbers."""
    session = get_session()
    session.require_project()
    return session.bridge.call("model.tree", model=model)


def set_options(
    model: str | None = None,
    author: str | None = None,
    project: str | None = None,
    definition: str | None = None,
    used_at: str | None = None,
    page_size: str | None = None,
) -> dict:
    """Set the header fields Ramus prints in every diagram's title block."""
    args = {
        key: value
        for key, value in (
            ("author", author),
            ("project", project),
            ("definition", definition),
            ("used_at", used_at),
            ("page_size", page_size),
        )
        if value is not None
    }
    if not args:
        raise ValueError(
            "Nothing to set. Pass at least one of --author, --project, --definition, --used-at, --page-size"
        )
    return _mutate("model.set-options", model=model, **args)


def render_tree(node: dict, prefix: str = "", is_last: bool = True,
                is_root: bool = True) -> list[str]:
    """Format a tree from :func:`model_tree` for terminal output."""
    connector = "" if is_root else ("└─ " if is_last else "├─ ")
    lines = [f"{prefix}{connector}{node['node']}  {node['name']}"]
    child_prefix = prefix if is_root else prefix + ("   " if is_last else "│  ")
    children = node.get("children", [])
    for index, child in enumerate(children):
        lines.extend(render_tree(child, child_prefix, index == len(children) - 1, False))
    return lines
