"""Project-level operations on Ramus ``.rsf`` files.

A ``.rsf`` is a ZIP archive holding the whole Ramus database — models,
classifiers, elements, attributes and diagram geometry. Only Ramus can read and
write it, so every function here goes through the engine.
"""

from __future__ import annotations

from pathlib import Path

from .session import get_session

#: The magic bytes at the start of every ``.rsf`` file (it is a ZIP archive).
RSF_MAGIC = b"PK\x03\x04"


def new_project(
    path: str,
    model_name: str = "A0",
    diagram_type: str = "idef0",
    author: str = "",
    project: str = "",
    definition: str = "",
    used_at: str = "",
    classifiers: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Create a ``.rsf`` containing one model, the way the Ramus wizard does."""
    session = get_session()
    return session.new_project(
        path,
        model_name=model_name,
        diagram_type=diagram_type,
        author=author,
        project=project,
        definition=definition,
        used_at=used_at,
        classifiers=list(classifiers or []),
        overwrite=overwrite,
    )


def open_project(path: str) -> dict:
    """Open an existing ``.rsf`` and describe what is inside it."""
    return get_session().open_project(path)


def save_project(path: str | None = None, overwrite: bool = True) -> dict:
    """Write the open project back to disk (or to a new path)."""
    return get_session().save_project(path, overwrite=overwrite)


def close_project() -> dict:
    """Close the open project, discarding anything unsaved."""
    return get_session().close_project()


def project_info() -> dict:
    """Summarise the open project: models, counts, classifiers."""
    session = get_session()
    session.require_project()
    info = session.bridge.call("project.info")
    info["modified"] = session.modified
    return info


def validate(path: str | None = None) -> dict:
    """Check that a file is a Ramus project the engine can actually open.

    Reports structural problems an agent should fix before going further:
    a model with no boxes, or arrows that never got an endpoint.
    """
    session = get_session()
    if path is not None:
        info = session.open_project(path)
    else:
        session.require_project()
        info = session.bridge.call("project.info")

    target = Path(info["path"])
    problems: list[str] = []
    warnings: list[str] = []

    with open(target, "rb") as handle:
        if handle.read(4) != RSF_MAGIC:
            problems.append(f"{target} does not start with the ZIP header a .rsf file must have")

    if not info.get("models"):
        warnings.append("Project has no IDEF0/DFD model; create one with 'model create <name>'")

    for model in info.get("models", []):
        if model.get("function_count", 0) <= 1:
            warnings.append(
                f"Model '{model['name']}' has no child boxes, so it has no diagram to render"
            )
        arrows = session.bridge.call("arrow.list", model=model["id"]).get("arrows", [])
        for arrow in arrows:
            for end in ("from", "to"):
                if arrow[end].get("kind") == "unset":
                    problems.append(
                        f"Arrow {arrow['id']} in model '{model['name']}' has no {end} endpoint"
                    )

    return {
        "path": str(target),
        "file_size": info.get("file_size", target.stat().st_size),
        "valid": not problems,
        "problems": problems,
        "warnings": warnings,
        "model_count": info.get("model_count", 0),
        "function_count": info.get("function_count", 0),
        "arrow_count": info.get("arrow_count", 0),
    }
