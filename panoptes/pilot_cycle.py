"""Deterministic scheduled-Work pilot cycle driver.

This module closes the repository-native gaps between one Work heartbeat and
Panoptes control:
- validate a project-specific unit DAG;
- independently select the next dependency-ready unit;
- discover the exact outstanding executor receipt from the target checkout;
- preserve the executor's proposed next unit as evidence while replacing it
  with the independently selected unit for control ingestion;
- emit exactly one next prompt or wait without duplicating work.

It does not schedule Work, scrape account usage, call GitHub, or execute target
code. Those are external Work responsibilities.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .control import RESULT_SCHEMA, run_invocation


PILOT_SCHEMA = "panoptes.pilot-contract/v2"


def _unit_for_control(unit):
    return {
        "id": unit["id"],
        "objective": unit["objective"],
        "acceptance_criteria": list(unit["acceptance_criteria"]),
        "exclusions": list(unit["exclusions"]),
    }


def validate_pilot_contract(contract):
    if not isinstance(contract, dict) or contract.get("schema_version") != PILOT_SCHEMA:
        raise ValueError(f"pilot contract must use {PILOT_SCHEMA}")

    for key in ("project", "repository", "sandbox_ref", "execution_owner", "goal"):
        if not isinstance(contract.get(key), str) or not contract[key].strip():
            raise ValueError(f"pilot contract {key} must be a non-empty string")

    units = contract.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("pilot contract requires at least one unit")

    ids = []
    by_id = {}
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("pilot units must be objects")
        ident = unit.get("id")
        if not isinstance(ident, str) or not ident.strip():
            raise ValueError("pilot unit id must be a non-empty string")
        if ident in by_id:
            raise ValueError(f"duplicate pilot unit id: {ident}")
        for key in ("objective",):
            if not isinstance(unit.get(key), str) or not unit[key].strip():
                raise ValueError(f"pilot unit {ident} {key} must be non-empty")
        for key in ("acceptance_criteria", "exclusions", "depends_on"):
            value = unit.get(key)
            if not isinstance(value, list) or (
                key == "acceptance_criteria" and not value
            ) or not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(
                    f"pilot unit {ident} {key} must be a list of non-empty strings"
                )
        ids.append(ident)
        by_id[ident] = unit

    known = set(ids)
    for unit in units:
        ident = unit["id"]
        deps = unit["depends_on"]
        if ident in deps:
            raise ValueError(f"pilot unit {ident} cannot depend on itself")
        missing = [dep for dep in deps if dep not in known]
        if missing:
            raise ValueError(
                f"pilot unit {ident} has unknown dependencies: {', '.join(missing)}"
            )

    # Deterministic cycle check.
    visiting = set()
    visited = set()

    def visit(ident):
        if ident in visiting:
            raise ValueError("pilot unit graph contains a cycle")
        if ident in visited:
            return
        visiting.add(ident)
        for dep in by_id[ident]["depends_on"]:
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in ids:
        visit(ident)

    storage = contract.get("result_storage", {})
    if not isinstance(storage, dict):
        raise ValueError("pilot result_storage must be an object")
    receipt_dir = storage.get("target_receipt_dir", ".panoptes/results")
    if (
        not isinstance(receipt_dir, str)
        or not receipt_dir.strip()
        or Path(receipt_dir).is_absolute()
        or ".." in Path(receipt_dir).parts
    ):
        raise ValueError("target_receipt_dir must be a safe relative path")

    return copy.deepcopy(contract)


def verified_unit_ids(control_state):
    if control_state is None:
        return set()
    results = control_state.get("applied_results", [])
    if not isinstance(results, list):
        raise ValueError("control state applied_results must be a list")
    completed = set()
    for result in results:
        if isinstance(result, dict) and result.get("status") == "verified":
            ident = result.get("completed_unit_id")
            if isinstance(ident, str) and ident:
                completed.add(ident)
    return completed


def select_next_unit(contract, completed_unit_ids):
    contract = validate_pilot_contract(contract)
    completed = set(completed_unit_ids)
    known = {unit["id"] for unit in contract["units"]}
    unknown = completed - known
    if unknown:
        raise ValueError(
            "control history contains units outside the pilot contract: "
            + ", ".join(sorted(unknown))
        )

    for unit in contract["units"]:
        if unit["id"] in completed:
            continue
        if set(unit["depends_on"]).issubset(completed):
            return _unit_for_control(unit)

    if completed == known:
        return None
    raise ValueError("pilot has unfinished units but no dependency-ready unit")


def receipt_path(contract, target_root, prompt_id):
    validate_pilot_contract(contract)
    if (
        not isinstance(prompt_id, str)
        or len(prompt_id) != 64
        or any(character not in "0123456789abcdef" for character in prompt_id)
    ):
        raise ValueError("outstanding prompt_id must be a lowercase SHA-256 hex digest")
    receipt_dir = contract.get("result_storage", {}).get(
        "target_receipt_dir", ".panoptes/results"
    )
    root = Path(target_root).resolve()
    candidate = (root / receipt_dir / f"{prompt_id}.json").resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError("target receipt path escapes target root")
    return candidate


def discover_outstanding_result(contract, control_state, target_root):
    if not control_state or not control_state.get("outstanding"):
        return None
    outstanding = control_state["outstanding"]
    prompt_id = outstanding.get("prompt_id")
    path = receipt_path(contract, target_root, prompt_id)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as source:
        result = json.load(source)
    if not isinstance(result, dict) or result.get("schema_version") != RESULT_SCHEMA:
        raise ValueError("target receipt must use panoptes.execution-result/v1")
    if result.get("prompt_id") != prompt_id:
        raise ValueError("target receipt prompt_id does not match outstanding prompt")
    return result


def _validate_live_target(contract, target_state):
    if not isinstance(target_state, dict) or target_state.get(
        "schema_version"
    ) != "panoptes.target-state/v1":
        raise ValueError("live target must use panoptes.target-state/v1")
    if target_state.get("project") != contract["project"]:
        raise ValueError("live target project does not match pilot contract")
    if target_state.get("repository", "").rstrip("/") != contract[
        "repository"
    ].rstrip("/"):
        raise ValueError("live target repository does not match pilot contract")
    execution = target_state.get("execution", {})
    if execution.get("ref") != contract["sandbox_ref"]:
        raise ValueError("live target execution ref does not match pilot sandbox_ref")
    authority = target_state.get("authority", {})
    if authority.get("executor") != contract["execution_owner"]:
        raise ValueError("live target executor does not match pilot contract")


def _target_with_selected_unit(contract, target_state, selected_unit):
    _validate_live_target(contract, target_state)
    target = copy.deepcopy(target_state)
    target["next_unit"] = copy.deepcopy(selected_unit)
    return target


def _result_for_independent_selection(result, selected_unit):
    normalized = copy.deepcopy(result)
    proposal = copy.deepcopy(normalized.get("next_unit"))
    normalized["executor_proposed_next_unit"] = proposal
    normalized["next_unit"] = copy.deepcopy(selected_unit)
    return normalized


def run_pilot_cycle(contract, target_state, control_state, target_root):
    """Prepare exactly one control transition for a scheduled Work heartbeat.

    Returns a JSON-serializable envelope with the next prompt artifact/state or
    a waiting/completed status. Caller persists state/artifact atomically.
    """
    contract = validate_pilot_contract(contract)
    _validate_live_target(contract, target_state)

    if control_state and control_state.get("outstanding"):
        result = discover_outstanding_result(contract, control_state, target_root)
        if result is None:
            return {
                "status": "waiting-for-executor-result",
                "prompt_id": control_state["outstanding"]["prompt_id"],
                "artifact": copy.deepcopy(
                    control_state["outstanding"].get("artifact")
                ),
                "state": copy.deepcopy(control_state),
                "result_discovered": False,
            }

        completed = verified_unit_ids(control_state)
        if result.get("status") == "verified":
            completed.add(result.get("completed_unit_id"))
        selected = select_next_unit(contract, completed)
        if selected is None:
            # Terminal apply is deliberately explicit; do not fabricate another
            # unit merely to make the loop continue.
            return {
                "status": "pilot-complete-receipt-discovered",
                "prompt_id": result["prompt_id"],
                "artifact": None,
                "state": copy.deepcopy(control_state),
                "result_discovered": True,
                "terminal_result": copy.deepcopy(result),
            }

        target = _target_with_selected_unit(contract, target_state, selected)
        normalized_result = _result_for_independent_selection(result, selected)
        artifact, state, duplicate = run_invocation(
            control_state, target, normalized_result
        )
        return {
            "status": "next-prompt-ready",
            "prompt_id": artifact["prompt_id"],
            "artifact": artifact,
            "state": state,
            "duplicate": duplicate,
            "result_discovered": True,
            "executor_proposed_next_unit": copy.deepcopy(result.get("next_unit")),
            "selected_next_unit": copy.deepcopy(selected),
        }

    selected = select_next_unit(contract, verified_unit_ids(control_state))
    if selected is None:
        return {
            "status": "pilot-complete",
            "artifact": None,
            "state": copy.deepcopy(control_state),
            "result_discovered": False,
        }
    target = _target_with_selected_unit(contract, target_state, selected)
    artifact, state, duplicate = run_invocation(control_state, target, None)
    return {
        "status": "next-prompt-ready",
        "prompt_id": artifact["prompt_id"],
        "artifact": artifact,
        "state": state,
        "duplicate": duplicate,
        "result_discovered": False,
        "selected_next_unit": copy.deepcopy(selected),
    }
