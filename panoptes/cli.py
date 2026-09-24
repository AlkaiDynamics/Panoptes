"""Manual interface for one bounded continuation cycle."""

import argparse
from contextlib import contextmanager
import json
import os
import tempfile
from pathlib import Path
from .core import acquire, advance, choose_next, connect, initialize, snapshot
from .planner import complete, install, next_task
from .corpus import campaign, integration_ledger
from .integrations.mnemos import MnemosClient
from .integrations.genetic_prompt_lab import plan_evolution_round
from .integrations.brainstormer import plan_to_excalidraw
from .integrations.qworld import advance_criteria_run, build_criteria_plan, start_criteria_run


def _write_json(path, payload):
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(payload, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(target)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def _state_write_lock(path):
    """Portable fail-fast single-writer guard for one durable JSON state file."""
    lock = Path(f"{path}.lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError(f"Qworld state is already locked: {lock}") from error
    try:
        yield
    finally:
        lock.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Panoptes continuation kernel")
    parser.add_argument("--db", default="panoptes.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init")
    start.add_argument("goal")
    start.add_argument("--constraint", action="append", default=[])
    commands.add_parser("status")
    commands.add_parser("next")
    commands.add_parser("ledger", help="Report implemented, tested, and accepted source counts")
    generate = commands.add_parser("campaign", help="Generate an evidence-gated candidate plan from the bundled corpus")
    generate.add_argument("--target", type=int, choices=[72, 300], default=72)
    generate.add_argument("--output", help="Save a full plan JSON to this path")
    memory_search = commands.add_parser("memory-search", help="Search a configured Mnemos service")
    memory_search.add_argument("query")
    memory_search.add_argument("--base-url", default=os.environ.get("MNEMOS_BASE", "http://localhost:8000"))
    memory_search.add_argument("--api-key-env", default="MNEMOS_API_KEY")
    memory_search.add_argument("--category")
    memory_search.add_argument("--limit", type=int, default=10)
    memory_search.add_argument("--semantic", action="store_true")
    memory_store = commands.add_parser("memory-store", help="Store a durable item in a configured Mnemos service")
    memory_store.add_argument("content")
    memory_store.add_argument("--base-url", default=os.environ.get("MNEMOS_BASE", "http://localhost:8000"))
    memory_store.add_argument("--api-key-env", default="MNEMOS_API_KEY")
    memory_store.add_argument("--category", default="projects")
    memory_store.add_argument("--subcategory")
    memory_store.add_argument("--metadata-json", default="{}")
    evolve = commands.add_parser("prompt-evolve-plan", help="Plan a provider-neutral genetic prompt round")
    evolve.add_argument("file", help="JSON file containing a population list")
    evolve.add_argument("--mutation-rate", type=float, default=0.1)
    evolve.add_argument("--seed", type=int, default=0)
    diagram = commands.add_parser("plan-diagram", help="Project a component DAG into Excalidraw skeletons")
    diagram.add_argument("file", help="JSON file containing components or a campaign")
    diagram.add_argument("--output", help="Save the diagram JSON to this path")
    criteria = commands.add_parser("criteria-plan", help="Build a Qworld question-specific evaluation DAG")
    criteria.add_argument("question")
    criteria.add_argument("--output", help="Save the criteria plan JSON to this path")
    criteria_start = commands.add_parser("criteria-run-start", help="Initialize a typed Qworld RET run")
    criteria_start.add_argument("question")
    criteria_start.add_argument("--output", help="Save the executable run state to this path")
    criteria_advance = commands.add_parser("criteria-run-advance", help="Validate and record one Qworld RET stage")
    criteria_advance.add_argument("state", help="Current Qworld run-state JSON")
    criteria_advance.add_argument("result", help="JSON result for the ready stage")
    criteria_advance.add_argument("--output", help="Save advanced state; may equal the state path")
    plan = commands.add_parser("plan-load", help="Install a JSON component DAG under a writer lease")
    plan.add_argument("file")
    plan.add_argument("checkpoint", type=int)
    plan.add_argument("owner")
    done = commands.add_parser("task-record")
    done.add_argument("id")
    done.add_argument("checkpoint", type=int)
    done.add_argument("owner")
    done.add_argument("outcome", choices=["verified", "blocked", "pending"])
    done.add_argument("--evidence", action="append", default=[])
    lease = commands.add_parser("acquire")
    lease.add_argument("owner")
    lease.add_argument("--ttl", type=int, default=300)
    record = commands.add_parser("record")
    record.add_argument("run_id")
    record.add_argument("base_checkpoint", type=int)
    record.add_argument("owner")
    record.add_argument("outcome", choices=["verified", "blocked", "failed", "deferred"])
    record.add_argument("--evidence", action="append", default=[])
    record.add_argument("--destination")
    args = parser.parse_args(argv)
    if args.command == "ledger":
        print(json.dumps(integration_ledger(), indent=2))
        return
    if args.command == "campaign":
        result = campaign(args.target)
        if args.output:
            _write_json(args.output, result)
            result = {"output": args.output, "corpus_size": result["corpus_size"],
                      "candidate_count": result["candidate_count"],
                      "tasks": len(result["components"]),
                      "operational_integrations_claimed": 0,
                      "first_candidate": result["candidates"][0]}
        print(json.dumps(result, indent=2))
        return
    if args.command in {"memory-search", "memory-store"}:
        client = MnemosClient(args.base_url, api_key=os.environ.get(args.api_key_env))
        if args.command == "memory-search":
            result = client.search(args.query, category=args.category, limit=args.limit,
                                   semantic=args.semantic)
        else:
            metadata = json.loads(args.metadata_json)
            if not isinstance(metadata, dict):
                raise ValueError("--metadata-json must contain a JSON object")
            result = client.create(args.content, category=args.category,
                                   subcategory=args.subcategory, metadata=metadata)
        print(json.dumps(result, indent=2))
        return
    if args.command == "prompt-evolve-plan":
        with open(args.file, encoding="utf-8") as source:
            payload = json.load(source)
        population = payload.get("population") if isinstance(payload, dict) else payload
        print(json.dumps(plan_evolution_round(population,
                                              mutation_rate=args.mutation_rate,
                                              seed=args.seed), indent=2))
        return
    if args.command == "plan-diagram":
        if args.output and Path(args.file).resolve() == Path(args.output).resolve():
            raise ValueError("plan input and diagram output must use different paths")
        with open(args.file, encoding="utf-8") as source:
            payload = json.load(source)
        components = payload.get("components") if isinstance(payload, dict) else payload
        result = plan_to_excalidraw(components)
        if args.output:
            _write_json(args.output, result)
            result = {"output": args.output,
                      "component_count": result["component_count"],
                      "dependency_count": result["dependency_count"],
                      "format": result["format"]}
        print(json.dumps(result, indent=2))
        return
    if args.command == "criteria-plan":
        result = build_criteria_plan(args.question)
        if args.output:
            _write_json(args.output, result)
            result = {"output": args.output,
                      "component_count": len(result["components"]),
                      "method": result["method"],
                      "source_revision": result["source_revision"]}
        print(json.dumps(result, indent=2))
        return
    if args.command == "criteria-run-start":
        result = start_criteria_run(args.question)
        if args.output:
            _write_json(args.output, result)
            result = {"output": args.output, "status": result["status"],
                      "next_task": result["next_task"]}
        print(json.dumps(result, indent=2))
        return
    if args.command == "criteria-run-advance":
        with open(args.result, encoding="utf-8") as source:
            stage_result = json.load(source)
        if args.output:
            state_path = Path(args.state).resolve()
            if Path(args.output).resolve() != state_path:
                raise ValueError("persistent Qworld advance must replace the authoritative state file")
            with _state_write_lock(state_path):
                with state_path.open(encoding="utf-8") as source:
                    state = json.load(source)
                result = advance_criteria_run(state, stage_result)
                _write_json(state_path, result)
            result = {"output": args.output, "status": result["status"],
                      "completed": len(result["completed"]),
                      "next_task": result.get("next_task")}
        else:
            with open(args.state, encoding="utf-8") as source:
                state = json.load(source)
            result = advance_criteria_run(state, stage_result)
        print(json.dumps(result, indent=2))
        return
    with connect(args.db) as db:
        if args.command == "init":
            result = initialize(db, args.goal, args.constraint)
        elif args.command == "status":
            result = snapshot(db)
            result["next_prompt"] = next_task(db)["prompt"]
            result["task_progress"] = [dict(row) for row in db.execute("SELECT * FROM progress ORDER BY id")]
        elif args.command == "next":
            result = next_task(db)
        elif args.command == "plan-load":
            with open(args.file, encoding="utf-8") as source:
                result = install(db, json.load(source)["components"], args.checkpoint, args.owner)
        elif args.command == "task-record":
            result = complete(db, args.id, args.outcome, args.evidence, args.checkpoint, args.owner)
        elif args.command == "acquire":
            result = acquire(db, args.owner, args.ttl)
        else:
            result = advance(db, args.run_id, args.base_checkpoint, args.owner,
                             args.outcome, args.evidence, args.destination)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
