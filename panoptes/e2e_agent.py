"""A real, deterministic Panoptes adapter for the create-mvp Make engine.

Produces and checks corpus planning deliverables. It makes no claim that
upstream repositories have been implemented in Panoptes merely by planning.
"""

import json
import os
import sys
from pathlib import Path

from .corpus import campaign, load_corpus
from .planner import validate


COMPONENTS = [
    {"id": "inventory", "desc": "Validate all distinct supplied repositories and preserve source status", "deps": [], "check": "434 unique source URLs with status and immutable pins where inspected"},
    {"id": "lightweight", "desc": "Generate the 72 distinct repository inspection and integration campaign", "deps": ["inventory"], "check": "72 source-specific candidate plans, with separate inspection and integration gates"},
    {"id": "master", "desc": "Generate the 300 distinct repository master campaign", "deps": ["inventory"], "check": "300 unique candidate plans with operational evidence gates"},
    {"id": "audit", "desc": "Independently check the generated campaigns against the corpus and count ledger", "deps": ["lightweight", "master"], "check": "Both plans valid, lightweight candidates included in master, zero phantom accepted contributions"},
]


def _location():
    base = Path(os.environ.get("SRC", "src"))
    return {item["id"]: base / item["id"] / "artifact.json" for item in COMPONENTS}


def _json(path):
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def expected(ident):
    if ident == "inventory":
        return {"kind": "inventory", "sources": [
            {"url": r["url"], "repository": r["repository"],
             "inspection_status": r["inspection_status"],
             "pinned_revision": r["pinned_revision"]} for r in load_corpus()]}
    if ident in {"lightweight", "master"}:
        return campaign(72 if ident == "lightweight" else 300)
    if ident == "audit":
        paths = _location()
        inventory = _json(paths["inventory"])
        lightweight = _json(paths["lightweight"])
        master = _json(paths["master"])
        compact = {v["url"] for v in lightweight["candidates"]}
        expanded = {v["url"] for v in master["candidates"]}
        if len(inventory["sources"]) != 434 or not compact.issubset(expanded):
            raise ValueError("campaign source set or inventory drift")
        return {"kind": "planning_audit", "corpus_sources": len(inventory["sources"]),
                "lightweight_distinct_candidates": len(compact),
                "master_distinct_candidates": len(expanded),
                "operational_integrations_accepted": 0,
                "verdict": "planning pipeline verified; product integration acceptance pending"}
    raise ValueError(f"unknown component: {ident}")


def verify(ident):
    paths = _location()
    if ident not in paths or _json(paths[ident]) != expected(ident):
        raise ValueError(f"{ident}: artifact failed independent regeneration check")
    if ident in {"lightweight", "master"}:
        result = _json(paths[ident])
        validate(result["components"])
        if result["operational_integrations_claimed"] != 0:
            raise ValueError("candidate plan cannot claim completed integrations")
    return True


def build(ident):
    paths = _location()
    if ident not in paths:
        raise ValueError("unsupported build component")
    artifact = paths[ident]
    artifact.parent.mkdir(parents=True, exist_ok=True)
    result = expected(ident)
    artifact.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    check = artifact.parent / "check.sh"
    check.write_text(f"#!/bin/sh\nset -eu\npython3 -m panoptes.e2e_agent verify {ident}\n", encoding="utf-8")
    check.chmod(0o755)
    verify(ident)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise ValueError("expected plan, build, verify, or review")
    role, *rest = args
    if role == "plan" and len(rest) == 1:
        goal = Path(rest[0]).read_text(encoding="utf-8")
        if "72" not in goal or "300" not in goal:
            raise ValueError("this adapter requires the confirmed 72/300 product goal")
        validate([{**item} for item in COMPONENTS])
        print(json.dumps({"components": [{k: v for k, v in item.items() if k != "check"}
                                         for item in COMPONENTS]}))
    elif role == "build" and len(rest) == 1:
        build(rest[0])
    elif role == "verify" and len(rest) == 1:
        verify(rest[0])
        print(f"VERIFIED: {rest[0]}")
    elif role == "review" and not rest:
        for ident in _location():
            verify(ident)
        print("Panoptes candidate planning artifacts checked against bundled corpus.")
        print("Accepted source integrations: 0. Product MVP remains open.")
        print("VERDICT: PASS")
    else:
        raise ValueError("invalid role or arguments")


if __name__ == "__main__":
    main()
