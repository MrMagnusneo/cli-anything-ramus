"""Classifiers and their elements — Ramus's reference-data layer.

A classifier is a named list (roles, documents, resources, systems) whose
elements can be nested. Models point at these elements, and the Ramus GUI shows
them in its classifier tree.
"""

from __future__ import annotations

from .session import get_session


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


# -- classifiers ---------------------------------------------------------


def list_classifiers() -> dict:
    return _read("classifier.list")


def create_classifier(name: str) -> dict:
    return _mutate("classifier.create", name=name)


def rename_classifier(classifier: str, name: str) -> dict:
    return _mutate("classifier.rename", classifier=classifier, name=name)


def delete_classifier(classifier: str) -> dict:
    return _mutate("classifier.delete", classifier=classifier)


def show_classifier(classifier: str) -> dict:
    """A classifier with its attributes and its element tree."""
    return _read("classifier.show", classifier=classifier)


# -- elements ------------------------------------------------------------


def list_elements(classifier: str) -> dict:
    return _read("element.list", classifier=classifier)


def add_element(classifier: str, name: str, parent: str | None = None) -> dict:
    return _mutate("element.add", classifier=classifier, name=name, parent=parent)


def rename_element(classifier: str, element: str, name: str) -> dict:
    return _mutate("element.rename", classifier=classifier, element=element, name=name)


def delete_element(classifier: str, element: str) -> dict:
    return _mutate("element.delete", classifier=classifier, element=element)


def render_elements(nodes: list[dict], indent: int = 0) -> list[str]:
    """Format a nested element tree for terminal output."""
    lines = []
    for node in nodes:
        lines.append(f"{'  ' * indent}- {node['name']}  (id {node['id']})")
        lines.extend(render_elements(node.get("children", []), indent + 1))
    return lines
