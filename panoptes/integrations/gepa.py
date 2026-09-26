"""Small persistent GEPA control kernel for scheduled prompt work.

The implementation keeps the useful provider-neutral control semantics from
GEPA: evaluation slices, a candidate pool, Pareto-front preservation, bounded
iterations, plateau-triggered engine switching, retries, and explicit stopping
conditions.  It deliberately does not embed a model provider.  A caller may
use deterministic candidates or route reflective proposals through the
project's existing inference seam.
"""

import copy
import math


SOURCE = "https://github.com/developzir/gepa-mcp/commit/398e514bfa456794225219fc9bd433d4f59983e2"
REFERENCE = "https://github.com/gepa-ai/gepa/commit/d771eb21b5dd3228bc3f567293d2ccfc423fc900"


def new_run(evaluation_slices, *, engines, metric_budget,
            plateau_patience=2, retry_limit=2, min_improvement=1e-9):
    """Create JSON-serializable state for one bounded optimization run."""
    if (not isinstance(evaluation_slices, list) or not evaluation_slices
            or len(evaluation_slices) != len(set(evaluation_slices))
            or not all(isinstance(item, str) and item.strip()
                       for item in evaluation_slices)):
        raise ValueError("evaluation_slices must be distinct nonempty strings")
    if (not isinstance(engines, list) or not engines
            or len(engines) != len(set(engines))
            or not all(isinstance(item, str) and item.strip() for item in engines)):
        raise ValueError("engines must be distinct nonempty strings")
    if not isinstance(metric_budget, int) or isinstance(metric_budget, bool) or metric_budget < 1:
        raise ValueError("metric_budget must be a positive integer")
    if not isinstance(plateau_patience, int) or plateau_patience < 1:
        raise ValueError("plateau_patience must be a positive integer")
    if not isinstance(retry_limit, int) or retry_limit < 0:
        raise ValueError("retry_limit must be a nonnegative integer")
    if (not isinstance(min_improvement, (int, float))
            or isinstance(min_improvement, bool) or min_improvement < 0
            or not math.isfinite(min_improvement)):
        raise ValueError("min_improvement must be finite and nonnegative")
    return {
        "schema_version": "panoptes.gepa-state/v1",
        "algorithm": "reflective_candidate_evolution_with_pareto_frontier",
        "source_revision": SOURCE.rsplit("/", 1)[-1],
        "reference_revision": REFERENCE.rsplit("/", 1)[-1],
        "evaluation_slices": list(evaluation_slices),
        "engines": list(engines),
        "current_engine": engines[0],
        "engine_index": 0,
        "engine_switches": 0,
        "metric_budget": metric_budget,
        "metric_calls": 0,
        "iteration": 0,
        "plateau_patience": plateau_patience,
        "plateau_iterations": 0,
        "retry_limit": retry_limit,
        "retry_counts": {},
        "retry_events": [],
        "min_improvement": float(min_improvement),
        "best_score": -1.0,
        "candidates": [],
        "frontier": [],
        "selected_candidate": None,
        "status": "running",
        "stop_reason": None,
    }


def _validated_candidates(state, candidates):
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("an iteration requires at least one candidate")
    known = {item["id"] for item in state["candidates"]}
    seen = set()
    normalized = []
    expected = set(state["evaluation_slices"])
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("each candidate must be an object")
        ident = item.get("id")
        prompt = item.get("prompt")
        scores = item.get("scores")
        if (not isinstance(ident, str) or not ident.strip()
                or ident in seen or ident in known):
            raise ValueError("candidate IDs must be globally unique nonempty strings")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("candidate prompts must be nonempty strings")
        if not isinstance(scores, dict) or set(scores) != expected:
            raise ValueError("candidate scores must cover every evaluation slice exactly")
        clean_scores = {}
        for name, score in scores.items():
            if (not isinstance(score, (int, float)) or isinstance(score, bool)
                    or not math.isfinite(score) or not 0 <= score <= 1):
                raise ValueError("evaluation scores must be finite numbers from zero to one")
            clean_scores[name] = float(score)
        seen.add(ident)
        normalized.append({"id": ident, "prompt": prompt, "scores": clean_scores,
                           "iteration": state["iteration"] + 1})
    return normalized


def _pareto_front(candidates, slices):
    frontier = []
    for candidate in candidates:
        vector = candidate["scores"]
        dominated = False
        for other in candidates:
            if other is candidate:
                continue
            other_vector = other["scores"]
            if (all(other_vector[name] >= vector[name] for name in slices)
                    and any(other_vector[name] > vector[name] for name in slices)):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate["id"])
    return frontier


def _selected(candidates, frontier, slices):
    positions = {item["id"]: index for index, item in enumerate(candidates)}
    by_id = {item["id"]: item for item in candidates}
    return max(
        frontier,
        key=lambda ident: (
            sum(by_id[ident]["scores"][name] for name in slices) / len(slices),
            min(by_id[ident]["scores"][name] for name in slices),
            -positions[ident],
        ),
    )


def _switch_engine(state):
    if state["engine_index"] + 1 >= len(state["engines"]):
        return False
    state["engine_index"] += 1
    state["current_engine"] = state["engines"][state["engine_index"]]
    state["engine_switches"] += 1
    state["plateau_iterations"] = 0
    return True


def evaluate_iteration(run, candidates):
    """Evaluate one already-scored candidate batch and advance bounded state."""
    state = copy.deepcopy(run)
    if state.get("status") != "running":
        raise ValueError("GEPA run is not running")
    normalized = _validated_candidates(state, candidates)
    calls = len(normalized) * len(state["evaluation_slices"])
    if state["metric_calls"] + calls > state["metric_budget"]:
        raise ValueError("iteration would exceed metric budget")

    state["candidates"].extend(normalized)
    state["iteration"] += 1
    state["metric_calls"] += calls
    state["frontier"] = _pareto_front(state["candidates"], state["evaluation_slices"])
    state["selected_candidate"] = _selected(
        state["candidates"], state["frontier"], state["evaluation_slices"])
    selected = next(item for item in state["candidates"]
                    if item["id"] == state["selected_candidate"])
    score = sum(selected["scores"].values()) / len(state["evaluation_slices"])
    if score > state["best_score"] + state["min_improvement"]:
        state["best_score"] = score
        state["plateau_iterations"] = 0
    else:
        state["plateau_iterations"] += 1

    if all(selected["scores"][name] == 1.0 for name in state["evaluation_slices"]):
        state["status"] = "converged"
        state["stop_reason"] = "all_evaluation_slices_satisfied"
    elif state["metric_calls"] >= state["metric_budget"]:
        state["status"] = "stopped"
        state["stop_reason"] = "metric_budget_exhausted"
    elif state["plateau_iterations"] >= state["plateau_patience"]:
        if not _switch_engine(state):
            state["status"] = "stopped"
            state["stop_reason"] = "plateau_with_no_remaining_engine"
    return state


def register_retry(run, candidate_id, reason):
    """Record a bounded execution retry and switch engines when exhausted."""
    state = copy.deepcopy(run)
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id is required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("retry reason is required")
    count = state["retry_counts"].get(candidate_id, 0) + 1
    state["retry_counts"][candidate_id] = count
    state["retry_events"].append({"candidate_id": candidate_id, "attempt": count,
                                  "reason": reason})
    if count == state["retry_limit"] + 1:
        if not _switch_engine(state):
            state["status"] = "stopped"
            state["stop_reason"] = "retry_limit_with_no_remaining_engine"
    return state
