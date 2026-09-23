# Panoptes

Panoptes is an evidence-aware planning and continuation engine for turning a goal plus a supplied repository corpus into bounded, reproducible work campaigns.

The current implementation combines a pinned `create-mvp` planning pipeline, a SQLite continuation kernel, dependency-aware task selection, source-evidence tracking, and provider-neutral prompt-planning adapters. It can generate and verify provisional 72-source and 300-source campaigns without paid inference.

## Current boundary

| Capability | Status |
| --- | --- |
| Deterministic goal → plan → build → checks → review pipeline | Implemented and tested |
| Persistent continuation state with checkpoints and writer leases | Implemented and tested |
| Dependency-aware next-task selection and blocker fallback | Implemented and tested |
| 72-source / 300-source campaign generation | Implemented and tested as planning artifacts |
| Source contribution ledger | 4 implemented/tested; 0 independently accepted |
| External LLM inference | Not wired |
| Autonomous scheduler dispatch | Not wired |
| Completed 72-source operational integration set | Not claimed |
| Completed 300-source operational integration set | Not claimed |

A generated campaign entry is a candidate, not an integration. A source counts only after source-specific implementation and behavior evidence; independent acceptance is a separate gate.

## Requirements

- Python 3.11+
- GNU Make
- Bash
- `jq`

## Verify the repository

```sh
python -m unittest discover -s tests -v
make -C examples/e2e -B -j2
python -m panoptes.cli ledger
```

## Generate campaigns

```sh
python -m panoptes.cli campaign --target 72 --output /tmp/panoptes-72.json
python -m panoptes.cli campaign --target 300 --output /tmp/panoptes-300.json
```

The end-to-end example also emits the next bounded prompt:

```sh
make -C examples/e2e -B -j2
cat examples/e2e/build/report.md
python -c 'import json; print(json.load(open("examples/e2e/src/audit/artifact.json"))["next_prompt"])'
```

## Optional adapters

Plan a deterministic provider-neutral prompt-evolution round:

```sh
python -m panoptes.cli prompt-evolve-plan population.json --seed 17
```

Query a separately operated Mnemos service:

```sh
MNEMOS_BASE=http://localhost:8000 MNEMOS_API_KEY=... \
  python -m panoptes.cli memory-search 'latest Panoptes checkpoint' --category projects
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — components, data flow, invariants, counting rules, and product boundary.
- [Deployment](docs/DEPLOYMENT.md) — preflight checks, state initialization, operating loop, rollback, and current deployment gates.

## Operating rule

A blocker redirects work; it does not cancel work. When no dependency-ready task can proceed, Panoptes emits planning/refinement work and preserves the next run rather than treating the project as failed or complete.
