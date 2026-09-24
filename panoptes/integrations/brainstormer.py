"""Dependency-free plan visualization adapted from Brainstormer.

Brainstormer's deterministic fallback turns named architecture elements and
connections into Excalidraw element skeletons.  Panoptes applies that approach
to its already-validated component DAG, avoiding the upstream web server,
session, CORS, and model-provider dependencies.
"""

from collections import defaultdict
from functools import cache
import re

from ..planner import validate


SOURCE_URL = "https://github.com/shivangdoshi07/brainstormer"
SOURCE_REVISION = "cbe68eb23715a024b46af60fbaab00d28fcb49b5"
MAX_COLUMNS = 12
ROW_GAP = 170
REPOSITORY = re.compile(r"\b[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\b")


def _shape(component_id):
    words = set(component_id.split("-"))
    if words.intersection({"audit", "review", "gate", "decision"}):
        return "diamond"
    return "rectangle"


def _color(component_id):
    if component_id.startswith("inspect-"):
        return "#a5d8ff"
    if component_id.startswith("integrate-"):
        return "#b2f2bb"
    if component_id.startswith(("audit-", "review-")):
        return "#ffd8a8"
    return "#d0bfff"


def _label(component):
    task_name = component["id"].replace("-", " ").title()
    repository = REPOSITORY.search(component["desc"])
    return task_name if repository is None else f"{task_name}\n{repository.group()}"


def plan_to_excalidraw(components):
    """Project a validated component DAG into deterministic visual skeletons."""
    by_id = validate(components)

    @cache
    def depth(component_id):
        dependencies = by_id[component_id]["deps"]
        return 0 if not dependencies else 1 + max(depth(dep) for dep in dependencies)

    layers = defaultdict(list)
    for component in components:
        layers[depth(component["id"])].append(component)

    elements = []
    positions = {}
    layer_y = 100
    for layer in sorted(layers):
        layer_items = layers[layer]
        for index, component in enumerate(layer_items):
            row, column = divmod(index, MAX_COLUMNS)
            label = _label(component)
            width = max(160, min(300, 48 + max(map(len, label.splitlines())) * 9))
            x = 100 + column * 340
            y = layer_y + row * ROW_GAP
            positions[component["id"]] = (x, y, width)
            elements.append({
                "id": component["id"],
                "type": _shape(component["id"]),
                "x": x,
                "y": y,
                "width": width,
                "height": 80,
                "backgroundColor": _color(component["id"]),
                "label": {"text": label},
            })
        layer_y += ((len(layer_items) + MAX_COLUMNS - 1) // MAX_COLUMNS) * ROW_GAP

    for component in components:
        end_x, end_y, end_width = positions[component["id"]]
        for dependency in component["deps"]:
            start_x, start_y, start_width = positions[dependency]
            elements.append({
                "id": f"edge:{dependency}->{component['id']}",
                "type": "arrow",
                "x": start_x + start_width / 2,
                "y": start_y + 80,
                "start": {"id": dependency},
                "end": {"id": component["id"]},
                "points": [[0, 0],
                           [end_x + end_width / 2 - start_x - start_width / 2,
                            end_y - start_y - 80]],
            })

    return {
        "format": "excalidraw-element-skeletons",
        "layout": "hierarchical",
        "source_url": SOURCE_URL,
        "source_revision": SOURCE_REVISION,
        "component_count": len(components),
        "dependency_count": len(elements) - len(components),
        "elements": elements,
        "component_descriptions": {item["id"]: item["desc"] for item in components},
    }
