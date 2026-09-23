"""Bounded DAG planner adapted from create-mvp's plan/component gate.

The upstream Makefile accepts an agent-produced component graph and runs gated
components in dependency order. Panoptes keeps the graph and evidence in SQLite
so successive prompts can select one actionable component without shelling out.
"""

import json
import re
import time

from .core import StaleCheckpoint, WriterBusy, snapshot, write

SOURCE = "https://github.com/qwadratic/create-mvp/commit/1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d"
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")


def validate(components):
    """Reject malformed, circular, or unbounded agent-authored plans."""
    if not isinstance(components, list) or not 1 <= len(components) <= 434:
        raise ValueError("plan must have 1..434 components")
    by_id = {}
    for task in components:
        if not isinstance(task, dict) or set(task) != {"id", "desc", "deps", "check"}:
            raise ValueError("component requires id, desc, deps, check")
        ident = task["id"]
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in by_id:
            raise ValueError("invalid or duplicate component ID")
        if not all(isinstance(task[key], str) and task[key].strip() for key in ("desc", "check")):
            raise ValueError("description and acceptance check required")
        deps = task["deps"]
        if not isinstance(deps, list) or len(deps) != len(set(map(str, deps))):
            raise ValueError("dependencies must be distinct IDs")
        by_id[ident] = task
    visited = set()
    active = set()

    def visit(ident):
        if ident in active:
            raise ValueError("dependency cycle")
        if ident in visited:
            return
        active.add(ident)
        for dep in by_id[ident]["deps"]:
            if not isinstance(dep, str) or dep not in by_id:
                raise ValueError(f"missing dependency: {dep}")
            visit(dep)
        active.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    return by_id


def install(db, components, checkpoint, owner, now=None):
    """Install a validated plan once; preserve existing progress on duplicate."""
    by_id = validate(components)
    now = time.time() if now is None else now
    canonical = json.dumps(components, sort_keys=True)
    with write(db):
        state = snapshot(db)
        if state["lease_owner"] != owner or state["lease_until"] <= now:
            raise WriterBusy("acquire a live writer lease")
        if checkpoint != state["checkpoint"]:
            raise StaleCheckpoint(f"expected {state['checkpoint']}, got {checkpoint}")
        existing = db.execute("SELECT payload FROM plan WHERE singleton=1").fetchone()
        if existing and existing["payload"] != canonical:
            raise ValueError("plan already installed; revision requires an explicit migration")
        if not existing:
            db.execute("INSERT INTO plan VALUES(1, ?)", (canonical,))
            for ident in by_id:
                db.execute("INSERT INTO progress VALUES(?, 'pending', '[]')", (ident,))
            db.execute("UPDATE state SET checkpoint=checkpoint+1 WHERE singleton=1")
        db.execute("UPDATE state SET lease_owner=NULL, lease_until=0 WHERE singleton=1")
    return next_task(db)


def next_task(db):
    """Choose a ready task on the longest remaining dependency chain.

    If none is ready because of a blocker, return a planning task rather than
    letting a missing repo or credential halt continuation.
    """
    row = db.execute("SELECT payload FROM plan WHERE singleton=1").fetchone()
    if not row:
        return {"status": "plan_missing", "prompt": "Build and validate a bounded component DAG, then install it."}
    tasks = validate(json.loads(row["payload"]))
    progress = {r["id"]: r["status"] for r in db.execute("SELECT id, status FROM progress")}
    if all(v == "verified" for v in progress.values()):
        return {"status": "plan_complete", "prompt": "Audit all evidence and integration counts before claiming MVP completion."}
    children = {ident: [] for ident in tasks}
    for task in tasks.values():
        for dep in task["deps"]:
            children[dep].append(task["id"])

    def depth(ident):
        remaining = [depth(c) for c in children[ident] if progress[c] != "verified"]
        return 1 + max(remaining, default=0)

    ready = [t for t in tasks.values() if progress[t["id"]] == "pending"
             and all(progress[d] == "verified" for d in t["deps"])]
    if ready:
        task = min(ready, key=lambda t: (-depth(t["id"]), t["id"]))
        state = snapshot(db)
        return {"status": "ready", "task": task, "critical_depth": depth(task["id"]),
                "prompt": (f"Goal: {state['goal']}\nAuthoritative constraints (JSON): "
                           f"{json.dumps(state['constraints'])}\nDecision history (JSON): "
                           f"{json.dumps(state['decisions'])}\nCheckpoint: {state['checkpoint']}\n"
                           f"Next task [{task['id']}]: {task['desc']}\nAcceptance: {task['check']}\n"
                           "Inspect dependencies and source revisions. Record actual evidence; "
                           "do not claim integrations until code and behavior are verified.")}
    blocked = [ident for ident, value in progress.items() if value == "blocked"]
    return {"status": "planning_fallback", "blocked": blocked,
            "prompt": "Work around blocked components: inspect sources, refine interfaces or fixtures and document evidence. Keep the next run enabled. Reopen a blocked task when its prerequisite changes."}


def complete(db, ident, outcome, evidence, checkpoint, owner, now=None):
    if outcome not in {"verified", "blocked", "pending"}:
        raise ValueError("outcome must be verified, blocked or pending")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ValueError("evidence must be a list of strings")
    if outcome == "verified" and not evidence:
        raise ValueError("verified task requires evidence")
    now = time.time() if now is None else now
    with write(db):
        state = snapshot(db)
        if state["lease_owner"] != owner or state["lease_until"] <= now:
            raise WriterBusy("acquire a live writer lease")
        if state["checkpoint"] != checkpoint:
            raise StaleCheckpoint(f"expected {state['checkpoint']}, got {checkpoint}")
        row = db.execute("SELECT payload FROM plan WHERE singleton=1").fetchone()
        if not row:
            raise ValueError("install a plan first")
        tasks = validate(json.loads(row["payload"]))
        if ident not in tasks:
            raise ValueError("unknown task")
        before = db.execute("SELECT status FROM progress WHERE id=?", (ident,)).fetchone()["status"]
        if before == "verified":
            raise ValueError("verified task is immutable")
        statuses = {r["id"]: r["status"] for r in db.execute("SELECT id, status FROM progress")}
        if outcome == "verified" and any(statuses[dep] != "verified" for dep in tasks[ident]["deps"]):
            raise ValueError("verify dependencies first")
        db.execute("UPDATE progress SET status=?, evidence_json=? WHERE id=?",
                   (outcome, json.dumps(evidence), ident))
        db.execute("UPDATE state SET checkpoint=checkpoint+1, lease_owner=NULL, lease_until=0 WHERE singleton=1")
    return next_task(db)
