"""Manual interface for one bounded continuation cycle."""

import argparse
import json
from .core import acquire, advance, choose_next, connect, initialize, snapshot
from .planner import complete, install, next_task
from .corpus import campaign


def main(argv=None):
    parser = argparse.ArgumentParser(description="Panoptes continuation kernel")
    parser.add_argument("--db", default="panoptes.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init")
    start.add_argument("goal")
    start.add_argument("--constraint", action="append", default=[])
    commands.add_parser("status")
    commands.add_parser("next")
    generate = commands.add_parser("campaign", help="Generate an evidence-gated candidate plan from the bundled corpus")
    generate.add_argument("--target", type=int, choices=[72, 300], default=72)
    generate.add_argument("--output", help="Save a full plan JSON to this path")
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
    if args.command == "campaign":
        result = campaign(args.target)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as output:
                json.dump(result, output, indent=2)
                output.write("\n")
            result = {"output": args.output, "corpus_size": result["corpus_size"],
                      "candidate_count": result["candidate_count"],
                      "tasks": len(result["components"]),
                      "operational_integrations_claimed": 0,
                      "first_candidate": result["candidates"][0]}
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
