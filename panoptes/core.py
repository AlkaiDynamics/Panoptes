"""Durable single-project continuation kernel, using only Python's standard library.

This is a deliberately small deterministic slice. It does not call an LLM,
schedule an alarm, select upstream repositories, or count integrations.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class StaleCheckpoint(ValueError):
    pass


class WriterBusy(ValueError):
    pass


def connect(path):
    db = sqlite3.connect(str(Path(path)), timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    db.row_factory = sqlite3.Row
    return db


@contextmanager
def write(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


def initialize(db, goal, constraints=()):
    if not goal.strip():
        raise ValueError("goal cannot be empty")
    with write(db):
        db.execute("""CREATE TABLE IF NOT EXISTS state (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                checkpoint INTEGER NOT NULL,
                goal TEXT NOT NULL,
                constraints_json TEXT NOT NULL,
                destination TEXT,
                lease_owner TEXT,
                lease_until REAL NOT NULL DEFAULT 0
            )""")
        db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                run_id TEXT PRIMARY KEY,
                base_checkpoint INTEGER NOT NULL,
                result_checkpoint INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                next_prompt TEXT NOT NULL,
                input_json TEXT NOT NULL
            )""")
        db.execute("""CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                value TEXT,
                evidence_json TEXT NOT NULL,
                authority TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                supersedes_json TEXT NOT NULL
            )""")
        db.execute("CREATE TABLE IF NOT EXISTS plan (singleton INTEGER PRIMARY KEY CHECK (singleton=1), payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS progress (id TEXT PRIMARY KEY, status TEXT NOT NULL, evidence_json TEXT NOT NULL)")
        # The first initializer owns the goal. Re-initialization never changes it.
        db.execute("INSERT OR IGNORE INTO state(singleton, checkpoint, goal, constraints_json) VALUES(1, 0, ?, ?)",
                   (goal.strip(), json.dumps(list(constraints))))
    return snapshot(db)


def snapshot(db):
    row = db.execute("SELECT * FROM state WHERE singleton=1").fetchone()
    if row is None:
        raise ValueError("initialize the state first")
    decisions = []
    superseded = set()
    for item in db.execute("SELECT * FROM decisions ORDER BY recorded_at, decision_id"):
        targets = json.loads(item["supersedes_json"])
        superseded.update(targets)
        decisions.append({"id": item["decision_id"], "question": item["question"],
                          "status": item["status"], "value": item["value"],
                          "evidence": json.loads(item["evidence_json"]),
                          "authority": item["authority"], "recorded_at": item["recorded_at"],
                          "supersedes": targets})
    for decision in decisions:
        if decision["id"] in superseded:
            decision["status"] = "superseded"
    return {"checkpoint": row["checkpoint"], "goal": row["goal"],
            "constraints": json.loads(row["constraints_json"]),
            "destination": row["destination"], "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"], "decisions": decisions}


def choose_next(state):
    if state["destination"] is None:
        task = "Resolve destination from the latest user decision, then inspect the repository. Meanwhile refine the product contract and source evidence."
    else:
        task = "Check the repository and latest checkpoint, then implement the smallest dependency-unblocking task with evidence."
    constraints = json.dumps(state["constraints"], ensure_ascii=False)
    decisions = json.dumps(state.get("decisions", []), ensure_ascii=False, sort_keys=True)
    return (f"Goal: {state['goal']}\nCheckpoint: {state['checkpoint']}\n"
            f"Destination: {state['destination'] or 'UNRESOLVED'}\n"
            f"Authoritative constraints (JSON): {constraints}\n"
            f"Decision history (JSON): {decisions}\n"
            f"Next bounded task: {task}\n"
            "Preserve user corrections and source evidence. Do not claim an integration from a description or a mock result.")


def record_decision(db, decision_id, question, status, value, evidence, authority,
                    recorded_at, owner, supersedes=(), now=None):
    """Append a decision; corrections point backward and never rewrite history."""
    if status not in {"confirmed", "inferred", "unknown"}:
        raise ValueError("new decision status must be confirmed, inferred, or unknown")
    if not decision_id or not question or not authority or not recorded_at or not owner:
        raise ValueError("decision ID, question, authority, timestamp, and owner are required")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ValueError("evidence must be a list of strings")
    supersedes = list(supersedes)
    if decision_id in supersedes or len(supersedes) != len(set(supersedes)):
        raise ValueError("supersession targets must be unique prior decisions")
    now = time.time() if now is None else now
    with write(db):
        state = snapshot(db)
        if state["lease_owner"] != owner or state["lease_until"] <= now:
            raise WriterBusy("acquire a live writer lease before recording a decision")
        known = {decision["id"]: decision for decision in state["decisions"]}
        for target in supersedes:
            if target not in known:
                raise ValueError(f"unknown supersession target: {target}")
            if known[target]["status"] == "superseded":
                raise ValueError(f"decision already superseded: {target}")
        db.execute("INSERT INTO decisions VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                   (decision_id, question, status, value, json.dumps(evidence), authority,
                    recorded_at, json.dumps(supersedes)))
        db.execute("UPDATE state SET checkpoint=checkpoint+1, lease_owner=NULL, lease_until=0 WHERE singleton=1")
    return snapshot(db)


def acquire(db, owner, ttl=300, now=None):
    if not owner or ttl <= 0:
        raise ValueError("owner and positive ttl required")
    now = time.time() if now is None else now
    with write(db):
        row = db.execute("SELECT lease_owner, lease_until FROM state WHERE singleton=1").fetchone()
        if row is None:
            raise ValueError("initialize the state first")
        if row["lease_owner"] and row["lease_until"] > now and row["lease_owner"] != owner:
            raise WriterBusy(f"lease held by {row['lease_owner']}")
        db.execute("UPDATE state SET lease_owner=?, lease_until=? WHERE singleton=1", (owner, now + ttl))
    return snapshot(db)


def advance(db, run_id, base_checkpoint, owner, outcome, evidence, destination=None, now=None):
    if outcome not in {"verified", "blocked", "failed", "deferred"}:
        raise ValueError("unsupported outcome")
    if not run_id or not owner or not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence):
        raise ValueError("run_id, owner, and a list of evidence strings required")
    now = time.time() if now is None else now
    input_json = json.dumps({"base_checkpoint": base_checkpoint, "outcome": outcome,
                             "evidence": evidence, "destination": destination}, sort_keys=True)
    with write(db):
        old = db.execute("SELECT * FROM receipts WHERE run_id=?", (run_id,)).fetchone()
        if old:
            if old["input_json"] != input_json:
                raise ValueError("run ID already exists with different input")
            return {"run_id": run_id, "checkpoint": old["result_checkpoint"],
                    "outcome": old["outcome"], "next_prompt": old["next_prompt"], "duplicate": True}
        state = snapshot(db)
        if state["lease_owner"] != owner or state["lease_until"] <= now:
            raise WriterBusy("acquire a live writer lease before committing")
        if base_checkpoint != state["checkpoint"]:
            raise StaleCheckpoint(f"expected {state['checkpoint']}, got {base_checkpoint}")
        if destination is not None and not destination.startswith("https://github.com/"):
            raise ValueError("destination must be a GitHub repository URL")
        if outcome == "verified" and not evidence:
            raise ValueError("verified result requires evidence")
        # Failed work does not assert a new checkpoint, but it records a receipt
        # so the same run cannot apply again after a later recovery.
        result = base_checkpoint + (outcome != "failed")
        new_destination = destination or state["destination"]
        after = {**state, "checkpoint": result, "destination": new_destination}
        prompt = choose_next(after)
        db.execute("UPDATE state SET checkpoint=?, destination=?, lease_owner=NULL, lease_until=0 WHERE singleton=1",
                   (result, new_destination))
        db.execute("INSERT INTO receipts VALUES(?, ?, ?, ?, ?, ?, ?)",
                   (run_id, base_checkpoint, result, outcome, json.dumps(evidence), prompt, input_json))
    return {"run_id": run_id, "checkpoint": result, "outcome": outcome,
            "next_prompt": prompt, "duplicate": False}
