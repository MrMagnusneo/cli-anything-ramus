"""Previews — truthful visual checkpoints of the open project.

A preview is a ``preview-bundle/v1`` directory holding diagrams rendered by
Ramus's own painter plus an inspection summary, so an agent can see what its
last few commands actually did before deciding what to do next. Nothing is
synthesised in Python and no GUI window is captured: every image is a real
Ramus render of real project state.

Bundles are immutable and content-addressed. Capturing again with the project
unchanged reuses the existing bundle instead of re-rendering.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from ..utils import preview_bundle as pb
from . import export as export_mod
from .session import get_session

SOFTWARE = "ramus"
HARNESS_VERSION = "1.0.0"

RECIPES = {
    "diagram": {
        "name": "diagram",
        "description": "Render one diagram (default: the model's top-level A0 diagram).",
        "artifacts": "PNG + SVG of a single diagram, plus its box and arrow inventory.",
        "options": ["--diagram", "--model", "--width", "--height"],
    },
    "model": {
        "name": "model",
        "description": "Render every decomposed diagram in a model.",
        "artifacts": "One PNG per diagram, plus the decomposition tree.",
        "options": ["--model", "--width", "--height"],
    },
    "tree": {
        "name": "tree",
        "description": "Inspect structure without rendering: decomposition tree and arrow list.",
        "artifacts": "JSON only — the cheapest way to check state between edits.",
        "options": ["--model"],
    },
}


def list_recipes() -> dict:
    return {
        "software": SOFTWARE,
        "protocol_version": pb.PROTOCOL_VERSION,
        "recipes": list(RECIPES.values()),
        "count": len(RECIPES),
        "live_supported": False,
        "live_note": (
            "Ramus has no incremental render pipeline: every capture is a full re-render of the "
            "saved project, so static capture plus diff covers the same ground truthfully."
        ),
    }


def _source_fingerprint(project_path: str) -> str:
    """Content hash of the project file, so an unchanged project reuses a bundle."""
    digest = hashlib.sha256()
    with open(project_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _generator(bridge_info: dict) -> dict:
    return {
        "harness": "cli-anything-ramus",
        "harness_version": HARNESS_VERSION,
        "backend": "Ramus PIDEF0painter (headless JVM)",
        "ramus_jar": bridge_info.get("ramus_jar"),
        "java_version": bridge_info.get("java_version"),
    }


def capture(
    recipe: str = "diagram",
    model: str | None = None,
    diagram: str | None = None,
    width: int | None = None,
    height: int | None = None,
    root_dir: str | None = None,
    force: bool = False,
) -> dict:
    """Publish a preview bundle for the open project."""
    if recipe not in RECIPES:
        raise ValueError(f"Unknown recipe '{recipe}'. Use one of: {', '.join(RECIPES)}")

    session = get_session()
    session.require_project()
    if session.modified:
        # The renderer reads the saved file, so publish what is really there.
        session.save_project()
    project_path = session.project_path
    assert project_path is not None

    options = {
        "model": model,
        "diagram": diagram,
        "width": width,
        "height": height,
    }
    # A bundle's directory name is a timestamp to the second plus its cache key.
    # Forcing a re-render of unchanged input would otherwise land on the
    # existing directory, so a forced capture gets its own cache key. The
    # recorded context below still shows only the options the caller passed.
    cache_options = dict(options)
    if force:
        cache_options["_forced_at"] = time.time_ns()

    prepared = pb.prepare_bundle(
        software=SOFTWARE,
        recipe=recipe,
        bundle_kind="static",
        source_fingerprint=_source_fingerprint(project_path),
        options=cache_options,
        harness_version=HARNESS_VERSION,
        project_path=project_path,
        root_dir=root_dir,
        force=force,
    )
    if prepared.get("cached"):
        manifest = prepared["manifest"]
        manifest["_cached"] = True
        return manifest

    bundle_dir = prepared["bundle_dir"]
    artifacts_dir = prepared["artifacts_dir"]
    bridge_info = session.bridge.ping()
    model_info = session.bridge.call("model.info", model=model)
    tree = session.bridge.call("model.tree", model=model)
    arrows = session.bridge.call("arrow.list", model=model)

    artifacts: list[dict] = []
    warnings: list[str] = []

    if recipe in ("diagram", "model"):
        targets = _render_targets(session, model, diagram, recipe)
        if not targets:
            warnings.append(
                "No decomposed function in this model, so there is no diagram to render. "
                "Add child boxes with 'function add'."
            )
        for index, target in enumerate(targets):
            node = target["node"]
            base = f"{node}-{target['name']}"
            for fmt, role in (("png", "primary" if index == 0 else "supporting"),
                              ("svg", "supporting")):
                if recipe == "model" and fmt == "svg":
                    continue  # One raster per diagram keeps batch bundles lean.
                out = os.path.join(artifacts_dir, f"{pb._slug(base)}.{fmt}")
                session.bridge.call(
                    "export.diagram",
                    path=out,
                    model=model,
                    diagram=str(target["id"]),
                    format=fmt,
                    width=width,
                    height=height,
                    overwrite=True,
                )
                check = export_mod.verify_output(out, fmt)
                if not check["valid"]:
                    warnings.append(f"{os.path.basename(out)} failed verification: {check['detail']}")
                artifacts.append(
                    pb.artifact_record(
                        bundle_dir=bundle_dir,
                        path=out,
                        artifact_id=f"{node}-{fmt}",
                        role=role,
                        kind="image",
                        label=f"{node} {target['name']} ({fmt.upper()})",
                        diagram_node=node,
                        verified=check["valid"],
                    )
                )

    inspection_path = os.path.join(artifacts_dir, "structure.json")
    pb.write_json(inspection_path, {"model": model_info, "tree": tree, "arrows": arrows})
    artifacts.append(
        pb.artifact_record(
            bundle_dir=bundle_dir,
            path=inspection_path,
            artifact_id="structure",
            role="primary" if recipe == "tree" else "supporting",
            kind="inspection",
            label="Decomposition tree and arrow inventory",
        )
    )

    summary = {
        "project": project_path,
        "model": model_info.get("name"),
        "model_id": model_info.get("id"),
        "diagram_type": model_info.get("diagram_type"),
        "function_count": model_info.get("function_count"),
        "arrow_count": model_info.get("arrow_count"),
        "decomposed_diagrams": model_info.get("decomposed_diagrams"),
        "rendered_diagrams": [a["label"] for a in artifacts if a["kind"] == "image"],
        "recipe": recipe,
    }

    manifest = pb.finalize_bundle(
        bundle_dir=bundle_dir,
        bundle_id=prepared["bundle_id"],
        bundle_kind="static",
        software=SOFTWARE,
        recipe=recipe,
        source={
            "path": project_path,
            "fingerprint": _source_fingerprint(project_path),
            "kind": "ramus-project",
        },
        artifacts=artifacts,
        summary=summary,
        cache_key=prepared["cache_key"],
        generator=_generator(bridge_info),
        status="ok" if not warnings else "partial",
        warnings=warnings or None,
        context={"options": {k: v for k, v in options.items() if v is not None}},
    )
    manifest["_cached"] = False
    return manifest


def _render_targets(session, model, diagram, recipe) -> list[dict]:
    """Which diagrams a recipe should render."""
    tree = session.bridge.call("model.tree", model=model)
    flat: list[dict] = []

    def walk(node):
        flat.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree["root"])
    decomposed = [n for n in flat if n.get("child_count", 0) > 0]
    if recipe == "model":
        return decomposed
    if diagram is None:
        return decomposed[:1]
    info = session.bridge.call("function.info", model=model, function=diagram)
    return [{"id": info["id"], "node": info["node"], "name": info["name"]}]


def latest(recipe: str | None = None, root_dir: str | None = None) -> dict:
    """The newest existing bundle. Never renders anything."""
    session = get_session()
    project_path = session.project_path
    manifest = pb.find_latest_manifest(
        software=SOFTWARE,
        recipe=recipe,
        project_path=project_path,
        root_dir=root_dir,
    )
    if manifest is None:
        raise RuntimeError(
            "No preview bundle has been published yet. Create one with: preview capture"
        )
    return manifest


def diff(
    baseline: str,
    recipe: str = "diagram",
    model: str | None = None,
    diagram: str | None = None,
    width: int | None = None,
    height: int | None = None,
    root_dir: str | None = None,
) -> dict:
    """Compare the open project against another ``.rsf``, publishing a bundle.

    Both sides are rendered by Ramus, so the comparison shows what a reader
    would actually see rather than a structural guess.
    """
    session = get_session()
    session.require_project()
    if session.modified:
        session.save_project()
    current_path = session.project_path
    assert current_path is not None

    baseline_path = str(Path(baseline).expanduser().resolve())
    if not Path(baseline_path).is_file():
        raise FileNotFoundError(f"Baseline project not found: {baseline_path}")
    if Path(baseline_path).resolve() == Path(current_path).resolve():
        raise ValueError("The baseline and the open project are the same file")

    current = capture(recipe=recipe, model=model, diagram=diagram,
                      width=width, height=height, root_dir=root_dir)

    # Render the baseline in the same shape, from its own file.
    session.bridge.call("project.open", path=baseline_path)
    try:
        before = capture_from_open(recipe, model, diagram, width, height, root_dir, baseline_path)
    finally:
        session.bridge.call("project.open", path=current_path)

    prepared = pb.prepare_bundle(
        software=SOFTWARE,
        recipe=f"{recipe}-diff",
        bundle_kind="diff",
        source_fingerprint=pb.fingerprint_data(
            {"a": before.get("cache_key"), "b": current.get("cache_key")}
        ),
        options={"baseline": baseline_path, "recipe": recipe},
        harness_version=HARNESS_VERSION,
        project_path=current_path,
        root_dir=root_dir,
        force=True,
    )
    bundle_dir = prepared["bundle_dir"]
    artifacts_dir = prepared["artifacts_dir"]

    changes = _compare(before, current)
    report_path = os.path.join(artifacts_dir, "diff.json")
    pb.write_json(report_path, changes)

    artifacts = [
        pb.artifact_record(
            bundle_dir=bundle_dir,
            path=report_path,
            artifact_id="diff",
            role="primary",
            kind="inspection",
            label="Structural differences between the two projects",
        )
    ]

    manifest = pb.finalize_bundle(
        bundle_dir=bundle_dir,
        bundle_id=prepared["bundle_id"],
        bundle_kind="diff",
        software=SOFTWARE,
        recipe=f"{recipe}-diff",
        source={"path": current_path, "baseline": baseline_path, "kind": "ramus-project-pair"},
        artifacts=artifacts,
        summary=changes,
        cache_key=prepared["cache_key"],
        generator=_generator(session.bridge.ping()),
        source_bundles=[
            {"role": "baseline", "bundle_dir": before.get("_bundle_dir"), "bundle_id": before.get("bundle_id")},
            {"role": "current", "bundle_dir": current.get("_bundle_dir"), "bundle_id": current.get("bundle_id")},
        ],
    )
    return manifest


def capture_from_open(recipe, model, diagram, width, height, root_dir, project_path) -> dict:
    """Capture for a project the bridge already has open under another path."""
    session = get_session()
    saved_path, session.project_path = session.project_path, project_path
    try:
        return capture(recipe=recipe, model=model, diagram=diagram,
                       width=width, height=height, root_dir=root_dir)
    finally:
        session.project_path = saved_path


def _compare(before: dict, after: dict) -> dict:
    """Summarise what changed between two captured bundles."""

    def summary_of(manifest: dict) -> dict:
        path = os.path.join(manifest["_bundle_dir"], manifest.get("summary_path", "summary.json"))
        return pb._load_json(Path(path))

    a, b = summary_of(before), summary_of(after)
    fields = ("model", "diagram_type", "function_count", "arrow_count", "decomposed_diagrams")
    changed = {
        field: {"baseline": a.get(field), "current": b.get(field)}
        for field in fields
        if a.get(field) != b.get(field)
    }
    return {
        "baseline": {"project": a.get("project"), **{f: a.get(f) for f in fields}},
        "current": {"project": b.get("project"), **{f: b.get(f) for f in fields}},
        "changed": changed,
        "identical": not changed,
    }
