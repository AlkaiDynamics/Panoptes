"""Read-only account-capacity gate for scheduled Work heartbeats.

Capacity state is intentionally separate from project continuation state.
This module validates explicit observations and derives an admission decision.
It never mutates capacity state and never infers exhaustion from a Work failure.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


SCHEMA_VERSION = "panoptes.account-capacity/v1"
STATUSES = {"AVAILABLE", "DEGRADED", "EXHAUSTED", "PROBE_AVAILABLE"}
SOURCES = {"settings-usage", "limit-banner", "codex-status", "manual"}
FRESHNESS = {"current", "stale", "unknown"}
LIMIT_TYPES = {"five_hour", "weekly", "credits", "combined", "unknown"}


def _parse_timestamp(value: Any, label: str, *, allow_none: bool = False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone offset")
    return parsed


def validate_capacity_state(state: dict, *, expected_account: str | None = None):
    """Validate one frozen panoptes.account-capacity/v1 observation."""
    if not isinstance(state, dict):
        raise ValueError("capacity state must be an object")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"capacity state must use {SCHEMA_VERSION}")

    account = state.get("account")
    if not isinstance(account, str) or not account.strip():
        raise ValueError("capacity account must be a non-empty string")
    if expected_account is not None and account != expected_account:
        raise ValueError("capacity state belongs to a different account")

    status = state.get("status")
    if status not in STATUSES:
        raise ValueError("capacity status is unsupported")

    limit_type = state.get("limit_type")
    if limit_type is not None and limit_type not in LIMIT_TYPES:
        raise ValueError("capacity limit_type is unsupported")

    observed_at = _parse_timestamp(state.get("observed_at"), "observed_at")
    reset_at = _parse_timestamp(state.get("reset_at"), "reset_at", allow_none=True)

    source = state.get("source")
    if source not in SOURCES:
        raise ValueError("capacity source is unsupported")

    evidence = state.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("capacity evidence must be a non-empty string")

    freshness = state.get("observation_freshness")
    if freshness not in FRESHNESS:
        raise ValueError("observation_freshness is unsupported")

    updated_by = state.get("updated_by")
    if not isinstance(updated_by, str) or not updated_by.strip():
        raise ValueError("updated_by must be a non-empty string")

    last_probe_at = _parse_timestamp(
        state.get("last_probe_at"), "last_probe_at", allow_none=True
    )
    last_probe_result = state.get("last_probe_result")
    if last_probe_result is not None and (
        not isinstance(last_probe_result, str) or not last_probe_result.strip()
    ):
        raise ValueError("last_probe_result must be null or a non-empty string")

    if status == "EXHAUSTED" and limit_type is None:
        raise ValueError("EXHAUSTED capacity requires limit_type")
    if status in {"AVAILABLE", "DEGRADED", "PROBE_AVAILABLE"} and limit_type is None:
        pass

    return {
        "account": account,
        "status": status,
        "limit_type": limit_type,
        "observed_at": observed_at,
        "reset_at": reset_at,
        "source": source,
        "evidence": evidence,
        "observation_freshness": freshness,
        "last_probe_at": last_probe_at,
        "last_probe_result": last_probe_result,
        "updated_by": updated_by,
    }


def evaluate_capacity_gate(
    state: dict,
    *,
    account: str | None = None,
    now: datetime | None = None,
):
    """Derive a read-only heartbeat admission decision from explicit capacity state.

    The function does not change status. Passing reset_at only makes a cheap probe
    admissible; it never promotes the account to AVAILABLE.
    """
    original = copy.deepcopy(state)
    parsed = validate_capacity_state(state, expected_account=account)
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a timezone offset")

    status = parsed["status"]
    reset_at = parsed["reset_at"]

    decision = {
        "schema_version": "panoptes.capacity-gate-decision/v1",
        "account": parsed["account"],
        "observed_status": status,
        "effective_status": status,
        "admit_work": False,
        "allow_panoptes": False,
        "mode": "blocked",
        "recommended_model": None,
        "recommended_reasoning": None,
        "reason": None,
        "observed_at": state["observed_at"],
        "reset_at": state.get("reset_at"),
        "source": parsed["source"],
        "observation_freshness": parsed["observation_freshness"],
    }

    if parsed["observation_freshness"] != "current":
        decision["reason"] = "capacity_observation_not_current"
    elif status == "AVAILABLE":
        decision.update(
            admit_work=True,
            allow_panoptes=True,
            mode="normal",
            recommended_model="Sol",
            recommended_reasoning="high",
            reason="explicit_capacity_available",
        )
    elif status == "DEGRADED":
        decision.update(
            admit_work=True,
            allow_panoptes=True,
            mode="degraded",
            recommended_model="Sol",
            recommended_reasoning="low",
            reason="explicit_capacity_degraded",
        )
    elif status == "PROBE_AVAILABLE":
        decision.update(
            admit_work=True,
            allow_panoptes=False,
            mode="probe",
            recommended_model="Sol",
            recommended_reasoning="low",
            reason="explicit_probe_authorized",
        )
    elif status == "EXHAUSTED":
        if reset_at is not None and current >= reset_at:
            decision.update(
                effective_status="PROBE_AVAILABLE",
                admit_work=True,
                allow_panoptes=False,
                mode="probe",
                recommended_model="Sol",
                recommended_reasoning="low",
                reason="observed_reset_window_elapsed_probe_only",
            )
        else:
            decision["reason"] = (
                "explicit_capacity_exhausted_until_reset"
                if reset_at is not None
                else "explicit_capacity_exhausted_reset_unknown"
            )

    if state != original:
        raise AssertionError("capacity gate must not mutate capacity state")
    return decision
