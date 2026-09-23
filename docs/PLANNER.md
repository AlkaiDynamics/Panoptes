# Operational planning slice

Panoptes adopts the bounded component DAG and gated completion pattern from
[`qwadratic/create-mvp` at `1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d`](https://github.com/qwadratic/create-mvp/tree/1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d/engine), MIT licensed. It adapts that framework to durable SQLite state rather than copying its Makefile or invoking coding agents. The algorithms are dependency validation with cycle rejection, longest remaining dependency chain selection, evidence-gated task completion, and blocked-work planning fallback. Dependency fanout is bounded by the 434-source corpus; no shell commands from agent-authored plans run automatically.

Run from this project directory (Python 3.11+):

```sh
python -m unittest discover -s tests -v
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 init 'Deliver a 72-source lightweight and 300-source master prompt engine' --constraint '72 and 300 mean distinct supplied repositories with operational integration evidence' --constraint 'Keep recurring work enabled through blockers'
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 acquire writer
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 plan-load examples/prompt-engine-plan.json 0 writer
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 next
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 acquire writer
python -m panoptes.cli --db /tmp/panoptes-example.sqlite3 task-record scope 1 writer verified --evidence 'User confirmed distinct 72 minimum'
```

Each subsequent task uses the checkpoint from `status`, a fresh `acquire`, and `task-record`. A blocked task is recorded with its exact reason. If all available work is blocked, `next` supplies independent planning work and never disables an alarm. `status` shows current task states and next prompt. Installing a different graph over an existing plan fails to prevent silent scope replacement; changing plans requires explicit migration. This CLI plans and emits prompts; no scheduler dispatch or agent execution is wired yet. The sample graph is a roadmap, not proof of 72 or 300 integrations. No source besides the adapted planning framework can be counted as implemented by these files.
