"""Build a provisional source campaign from the user's supplied corpus.

The capability map is a description-derived hypothesis, never evidence of a
repository's code or an accepted integration.
"""

import csv
import hashlib
import json
from importlib.resources import files
from pathlib import Path

from .planner import validate


CORPUS_SHA256 = "7c9b677aee42aca4e66743f79907e5bd9a55a882e41fd0f2e1c26b5d2a0a9181"
PRIORITY = {"planning_decision", "agents_orchestration", "execution_automation",
            "reliability_state", "verification_evaluation", "prompt_optimization",
            "software_engineering", "data_connectors_tools", "memory_knowledge"}


def load_corpus(path=None, hypotheses_path=None):
    bundled = files("panoptes").joinpath("data")
    source = Path(path) if path else bundled.joinpath("corpus_2026-09-23.csv")
    if path is None and hashlib.sha256(source.read_bytes()).hexdigest() != CORPUS_SHA256:
        raise ValueError("bundled corpus changed unexpectedly")
    labels = Path(hypotheses_path) if hypotheses_path else bundled.joinpath("capability_hypotheses.csv")
    with labels.open(newline="", encoding="utf-8") as stream:
        hypotheses = {r["repository"]: set(filter(None, r["hypothesis_labels"].split(";")))
                      for r in csv.DictReader(stream)}
    with source.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    with bundled.joinpath("seed_evidence.json").open(encoding="utf-8") as stream:
        inspected = {entry["url"]: entry for entry in json.load(stream)["sources"]}
    seen = set()
    for row in rows:
        repo = row["repository"]
        if (not repo or repo in seen or row["url"] != "https://github.com/" + repo
                or repo.count("/") != 1):
            raise ValueError("duplicate or noncanonical GitHub repository in corpus")
        seen.add(repo)
        row["hypothesis_labels"] = sorted(hypotheses.get(repo, ()))
        if row["url"] in inspected:
            entry = inspected[row["url"]]
            row["inspection_status"] = entry["status"]
            row["pinned_revision"] = entry.get("revision", "")
            row["integration_disposition"] = entry.get("integration_disposition", "")
    if len(rows) < 72:
        raise ValueError("corpus cannot supply 72 distinct repositories")
    return rows


def campaign(target=72, rows=None):
    """Choose diverse *inspection candidates* and produce an evidence gated DAG.

    Selection uses diminishing returns for repeated provisional labels. Nothing
    in the returned plan certifies a source or claims an operational integration.
    """
    sources = list(load_corpus() if rows is None else rows)
    if not isinstance(target, int) or target < 1 or target > len(sources):
        raise ValueError("target must fit the distinct source corpus")
    # The planning framework is already wired into Panoptes; inspect its
    # contribution first so the campaign starts from a real code path.
    foundation = next((r for r in sources if r["repository"] == "qwadratic/create-mvp"), None)
    chosen = [foundation] if foundation is not None else []
    coverage = {}
    remaining = [row for row in sources if row["inspection_status"] != "assessed_empty_repository"]
    if foundation is not None:
        remaining.remove(foundation)
        for label in foundation["hypothesis_labels"]:
            coverage[label] = 1
    if target > len(remaining):
        raise ValueError("insufficient nonempty candidate repositories")
    for _ in range(target - len(chosen)):
        def score(row):
            priority = row["hypothesis_labels"] and PRIORITY.intersection(row["hypothesis_labels"])
            labels = priority or set(row["hypothesis_labels"])
            diversity = sum(1 / (1 + coverage.get(label, 0)) for label in labels)
            relevance = 2 if priority else 0
            # An inspected source still requires source revision and test gates.
            inspected = 5 if row["inspection_status"] == "partial_code_inspection" else 0
            return (relevance + inspected + diversity, -int(row["source_line"]))

        item = max(remaining, key=score)
        remaining.remove(item)
        chosen.append(item)
        for label in item["hypothesis_labels"]:
            coverage[label] = coverage.get(label, 0) + 1

    tasks = []
    for index, item in enumerate(chosen, 1):
        prefix = f"source-{index:03d}"
        repo = item["repository"]
        tasks.append({"id": f"inspect-{prefix}", "desc": f"Inspect {repo} at an immutable revision; confirm license, code paths, behavior and relevant capability. Supplied description is unverified.",
                      "deps": [], "check": "Record pinned source SHA, named inspected files, fit and constraints; inspection alone counts zero integrations."})
        tasks.append({"id": f"integrate-{prefix}", "desc": f"Integrate one distinct operational capability from {repo} into Panoptes, or document why it is unsuitable and substitute from the remaining corpus.",
                      "deps": [f"inspect-{prefix}"], "check": "Repository-specific implementation, immutable source revision, meaningful passing test, observable end-to-end behavior, and independent acceptance evidence."})
    tasks.append({"id": f"audit-{target}", "desc": f"Independently audit {target} distinct working repository contributions and the end-to-end journey.",
                  "deps": [f"integrate-source-{i:03d}" for i in range(1, target + 1)],
                  "check": f"At least {target} distinct supplied repositories pass operational integration evidence and independent review."})
    validate(tasks)
    return {"status": "provisional_candidate_campaign", "target_distinct_repositories": target,
            "corpus_size": len(sources), "candidate_count": len(chosen),
            "operational_integrations_claimed": 0,
            "selection_basis": "description-derived labels for provisional diversity; inspected source evidence is a later gate",
            "candidates": [{"repository": item["repository"], "url": item["url"],
                            "inspection_status": item["inspection_status"],
                            "pinned_revision": item["pinned_revision"],
                            "integration_disposition": item.get("integration_disposition", ""),
                            "hypothesis_labels": item["hypothesis_labels"]} for item in chosen],
            "components": tasks}


def integration_ledger():
    """Separate actual adapter progress from candidate and inspection counts."""
    source = files("panoptes").joinpath("data", "integration_evidence.json")
    with source.open(encoding="utf-8") as stream:
        contributions = json.load(stream)["contributions"]
    corpus = {row["url"] for row in load_corpus()}
    seen = set()
    root = Path(__file__).resolve().parents[1]
    checkout_present = (root / "vendor/create-mvp/build.mk").is_file()
    for item in contributions:
        if item["url"] not in corpus or item["url"] in seen:
            raise ValueError("integration evidence must use distinct supplied sources")
        seen.add(item["url"])
        revision = item["source_revision"]
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("source revision must be an immutable SHA")
        if item["tested_in_engine"] and not item["implemented"]:
            raise ValueError("test cannot precede implementation")
        if item["accepted"] and (not item["tested_in_engine"] or not item.get("independent_review")):
            raise ValueError("acceptance requires tests and independent review")
        if checkout_present and any(not (root / p).is_file() for p in item["implementation_paths"] + item["behavior_test_paths"]):
            raise ValueError("source implementation or behavior test is missing")
    return {"sources": len(corpus),
            "local_evidence_paths_checked": checkout_present,
            "selected": sum(bool(i["selected"]) for i in contributions),
            "implemented": sum(bool(i["implemented"]) for i in contributions),
            "tested": sum(bool(i["tested_in_engine"]) for i in contributions),
            "accepted": sum(bool(i["accepted"]) for i in contributions),
            "contributions": contributions}
