"""Manual interface for one bounded continuation cycle."""

import argparse
import json
from .core import acquire, advance, choose_next, connect, initialize, snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Panoptes continuation kernel")
    parser.add_argument("--db", default="panoptes.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("init")
    start.add_argument("goal")
    start.add_argument("--constraint", action="append", default=[])
    commands.add_parser("status")
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
    with connect(args.db) as db:
        if args.command == "init":
            result = initialize(db, args.goal, args.constraint)
        elif args.command == "status":
            result = snapshot(db)
            result["next_prompt"] = choose_next(result)
        elif args.command == "acquire":
            result = acquire(db, args.owner, args.ttl)
        else:
            result = advance(db, args.run_id, args.base_checkpoint, args.owner,
                             args.outcome, args.evidence, args.destination)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
