# Operational end-to-end planning pipeline

Panoptes runs the actual `build.mk` engine from
[`qwadratic/create-mvp` at `1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d`](https://github.com/qwadratic/create-mvp/tree/1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d/engine), MIT licensed. Its original license is in `vendor/create-mvp/LICENSE`. One local patch puts its effort-budget jq expression on one recipe line: the pinned original's multiline single-quoted expression passed literal backslashes to jq here and failed. The Panoptes adapter implements the engine's `plan`, `build` and `review` roles and builds actual corpus planning artifacts. GNU Make, Bash, jq and Python are required; no coding-agent CLI or API key is required for this deterministic planning pipeline.

Run the goal through planning, dependency-ordered parallel builds, per-component checks and final review:

```sh
make -C examples/e2e -j2
cat examples/e2e/build/report.md
python -c 'import json; print(json.load(open("examples/e2e/src/audit/artifact.json"))["next_prompt"])'
python -m panoptes.cli campaign --target 72 --output /tmp/panoptes-72.json
python -m panoptes.cli campaign --target 300 --output /tmp/panoptes-300.json
python -m panoptes.cli ledger
```

The 434-source inventory, provisional capability labels and nine partial
source inspections are bundled. The empty repository is excluded from
candidacy. The 72-source campaign has 145 inspection/integration/audit tasks;
the master campaign has 601. Both plans explicitly claim **zero** completed
integrations. Checks independently regenerate the plans and reject tampering;
`make` resumes completed components. The reviewer certifies planning
artifacts only. A generated task is not an implementation of a source. The
bundled contribution ledger (`panoptes/data/integration_evidence.json`) records
the pinned `create-mvp` engine as one **implemented and tested** source, with
the Makefile code path, behavior test and original MIT license. Its formal
accepted count remains zero pending independent acceptance of the contribution.

The pipeline also invokes the unmodified MIT-licensed
[`hermes-blind` scaffold at `61c270933291e2c726d09aaa8f66edc5ab369dce`](https://github.com/hermes-labs-ai/hermes-blind/tree/61c270933291e2c726d09aaa8f66edc5ab369dce/src/hermes_blind)
to turn a subsequently collected, nonempty source-and-test evidence packet
into an evidence-gated scoring prompt. The Make pipeline emits an
`audit_collection_prompt` alongside `next_prompt`; only after an
independent reviewer has gathered evidence may they run
`python -m panoptes.e2e_agent score audit-evidence.json`.
Original copyright and license are retained in
`panoptes/_vendor/HERMES_LICENSE`. This is deterministic, dependency-free
prompt construction, not proof that the submitted excerpts are authentic, that
an LLM follows the scaffold, or that an independent audit occurred. Scoring
prompt generation rejects missing or mismatched source records and cannot set
any acceptance flags.

The third implemented and tested contribution interoperates with the pinned,
Apache-2.0 [`ncz-os/mnemos` v1 API at
`e0271cc52b9a05feddf44e3d1b1d5412abe8be1a`](https://github.com/ncz-os/mnemos/tree/e0271cc52b9a05feddf44e3d1b1d5412abe8be1a).
Because upstream requires Python 3.13 and substantial service dependencies,
Panoptes supplies a dependency-free Python 3.11 JSON-over-HTTP adapter rather
than embedding the server. An administrator must provide a trusted root URL;
redirects and credentialed or path-bearing base URLs are rejected so bearer
keys stay bound to the configured origin. The CLI reads the key from an
environment variable rather than a command-line value:

```sh
export MNEMOS_BASE=http://localhost:8000
export MNEMOS_API_KEY='scoped-service-token'
python -m panoptes.cli memory-store 'checkpoint 12' --subcategory checkpoints --metadata-json '{"source":"panoptes"}'
python -m panoptes.cli memory-search 'latest checkpoint' --category projects --limit 5
```

The behavior tests use a real local HTTP connection and verify upstream route
shapes, payloads, bearer authentication, JSON responses and safe failures.
They do not run a live Mnemos deployment, so independent acceptance remains
open. The ledger now tracks three implemented and tested source contributions;
accepted remains zero until independent review.

Continuation is ledger-aware. Candidate 003 (`Hiteshgottapu/ReAct-AI`) is
explicitly deferred because the pinned tree has no verified reuse license and
several advertised paths are placeholders. The current audit artifact skips
that blocked candidate and the already implemented Mnemos contribution, then
points to candidate 004 (`alib8b8/aflare`) for the next bounded source/license/
fit decision. A deferred source contributes zero to the 72/300 goals.

The SQLite continuation interface uses dependency validation with cycle
rejection, longest remaining dependency chain selection, evidence-gated task
completion and a blocked-work planning fallback. Load the generated plan:

```sh
python -m panoptes.cli --db /tmp/panoptes-72.sqlite3 init 'Deliver 72 distinct supplied repositories' --constraint 'Require observable integration evidence'
python -m panoptes.cli --db /tmp/panoptes-72.sqlite3 acquire writer
python -m panoptes.cli --db /tmp/panoptes-72.sqlite3 plan-load /tmp/panoptes-72.json 0 writer
python -m panoptes.cli --db /tmp/panoptes-72.sqlite3 next
```

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

Each subsequent task uses the checkpoint from `status`, a fresh `acquire`, and `task-record`. A blocked task is recorded with its exact reason. If all available work is blocked, `next` supplies independent planning work and never disables an alarm. `status` shows current task states and next prompt. Installing a different graph over an existing plan fails to prevent silent scope replacement; changing plans requires explicit migration. This CLI plans and emits prompts; no scheduler dispatch or agent execution is wired yet. The sample graph is a roadmap, not proof of 72 or 300 integrations. Only contribution-ledger entries with pinned, source-specific implementation and test evidence count as implemented; independent acceptance is a separate gate.

## Current product boundary

The legacy sample graph above is an optional small CLI example. The Make
adapter now runs the upstream planning engine end to end and verifies the
generated campaigns. Its final `VERDICT: PASS` is scoped to planning artifacts.
Autonomous implementation of source integrations, external scheduler dispatch,
and independent acceptance of 72/300 operational repositories remain open.
