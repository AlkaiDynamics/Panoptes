# Panoptes Deployment Runbook

This runbook operates the current Panoptes planner/continuation core. External ChatGPT Work/Tasks owns wall-clock recurrence. This does **not** imply that reflective LLM inference or the 72/360 integration goals are complete.

## 1. Deployment target

Current development branch:

```text
feature/prompt-engine-first-slice
```

Current repository:

```text
https://github.com/AlkaiDynamics/Panoptes
```

For a production deployment, prefer a reviewed commit or merged `main`. If deploying the draft branch intentionally, record the exact commit SHA with the deployment receipt.

## 2. Runtime requirements

Required:

- Python 3.11+
- GNU Make
- Bash
- `jq`
- writable persistent storage for the SQLite database

No model-provider API key is required for the deterministic planner.

Optional:

- a separately operated Mnemos service;
- `MNEMOS_BASE` and `MNEMOS_API_KEY` when using the Mnemos adapter.

## 3. Clean checkout and installation

```sh
git clone https://github.com/AlkaiDynamics/Panoptes.git
cd Panoptes
git checkout feature/prompt-engine-first-slice
python -m venv .venv
```

Activate the environment, then install locally:

```sh
# Bash / Git Bash / WSL
source .venv/bin/activate
pip install -e .
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 4. Mandatory preflight

Run both verification paths before starting a persistent state database:

```sh
python -m unittest discover -s tests -v
make -C examples/e2e -B -j2
```

Then inspect the contribution ledger:

```sh
python -m panoptes.cli ledger
python -m panoptes.cli criteria-run-start 'Does this release satisfy its evidence contract?' --output /tmp/panoptes-qworld-run.json
```

Advance the Qworld run with the exact collection requested by `next_task`:

```sh
python -m panoptes.cli criteria-run-advance /tmp/panoptes-qworld-run.json stage-result.json --output /tmp/panoptes-qworld-run.json
```

The state write is atomic and guarded by a fail-fast single-writer lock. Each
stage result must carry the revision requested by `next_task`; each advance
replays and validates prior outputs, stage order, lineage, artifacts, and the
next-task handoff before accepting new data. A process killed while holding the
lock can leave `<state>.lock`; inspect the state before removing that directory.
The terminal status is `pending_review`, because structural validation cannot
substitute for independent review of the proposed rubric's quality.

Expected product-level interpretation:

- planning pipeline: verified by tests and end-to-end example;
- implemented/tested source contributions: currently 7;
- independently accepted operational integrations: currently 0;
- 72-source and 360-source campaigns: planning artifacts, not completion claims.

If the tests or end-to-end build fail, do not start or advance the persistent deployment state until the failure is understood.

## 5. Generate the initial campaign

Create a persistent state directory outside disposable build output:

```sh
mkdir -p state
python -m panoptes.cli campaign --target 72 --output state/panoptes-72.json
```

Optionally generate the master campaign separately:

```sh
python -m panoptes.cli campaign --target 360 --output state/panoptes-360.json
```

Do not load both plans into the same database. The installed DAG is intentionally immutable without an explicit migration.

## 6. Initialize persistent continuation state

For the 72-source operational campaign:

```sh
python -m panoptes.cli --db state/panoptes.sqlite3 init \
  'Deliver the Panoptes automated MVP prompt architecture' \
  --constraint '72 means distinct supplied repositories with operational integration evidence' \
  --constraint '360 is the master distinct-repository target' \
  --constraint 'A blocker redirects work; it does not cancel the next run'
```

Acquire the writer lease and load the generated plan at checkpoint 0:

```sh
python -m panoptes.cli --db state/panoptes.sqlite3 acquire deployer
python -m panoptes.cli --db state/panoptes.sqlite3 plan-load state/panoptes-72.json 0 deployer
```

Inspect the resulting state and next task:

```sh
python -m panoptes.cli --db state/panoptes.sqlite3 status
python -m panoptes.cli --db state/panoptes.sqlite3 next
```

`plan-load` advances the checkpoint. From this point forward, read the current checkpoint from `status` before every mutation.

## 7. Operating loop

For each bounded unit of work:

1. Read `status` / `next`.
2. Perform only the selected bounded task or a blocker-safe planning fallback.
3. Acquire a fresh writer lease.
4. Record the task outcome against the current checkpoint.
5. Preserve concrete evidence strings.
6. Read the newly emitted next task.

Example verified task record:

```sh
python -m panoptes.cli --db state/panoptes.sqlite3 acquire worker-001
python -m panoptes.cli --db state/panoptes.sqlite3 task-record TASK_ID CHECKPOINT worker-001 verified \
  --evidence 'source revision inspected' \
  --evidence 'behavior test passed'
```

Example blocked task record:

```sh
python -m panoptes.cli --db state/panoptes.sqlite3 acquire worker-001
python -m panoptes.cli --db state/panoptes.sqlite3 task-record TASK_ID CHECKPOINT worker-001 blocked \
  --evidence 'exact blocker and source reference'
```

When no task is dependency-ready, `next` returns a planning fallback. The external Work task must keep the next recurring run enabled.

## 8. Scheduler integration contract

Autonomous dispatch is not implemented inside Panoptes yet. Any external scheduler must preserve these semantics:

```text
read current state
    -> choose next bounded work
    -> execute or refine
    -> acquire lease
    -> commit evidence against exact checkpoint
    -> emit/read next work
    -> schedule next run
```

Required behavior:

- never reuse stale checkpoints;
- never allow multiple active writers for the same database;
- never convert a blocker into cancellation of future runs;
- never count a generated candidate as an operational integration;
- never mark verified without evidence;
- never silently replace an installed plan.

For a 60-minute loop, cadence belongs in the external scheduler. The Panoptes state machine should remain cadence-agnostic.

## 9. Persistence and backup

Treat the SQLite database as deployment state, not cache.

Recommended operational controls:

- place `state/panoptes.sqlite3` on persistent storage;
- back up the database before plan migrations or deployment upgrades;
- keep deployment commit SHA and database backup timestamp together;
- preserve generated campaign JSON used to create the installed DAG;
- do not copy an actively mutating SQLite file without using a safe SQLite backup method or stopping writers first.

## 10. Upgrade and rollback

Before upgrade:

1. stop external scheduler dispatch;
2. allow any current writer lease to expire or complete;
3. back up the database;
4. record the current repository commit SHA;
5. deploy the new reviewed commit;
6. rerun unit and end-to-end verification;
7. inspect `status` before resuming dispatch.

Rollback code by restoring the previous reviewed commit. Roll back state only from a known-good database backup. Do not attempt to overwrite a newer installed plan with `plan-load`; plan replacement requires an explicit migration path.

## 11. Deployment gates

### Green for current planner deployment

- repository checks pass;
- end-to-end planning build passes;
- persistent SQLite path is available;
- exact deployment commit is recorded;
- campaign JSON is generated and retained;
- scheduler wrapper, if used, honors leases/checkpoints/blocker fallback.

### Still open for autonomous MVP deployment

- an external ChatGPT Work task must invoke the bounded control run; Panoptes intentionally
  does not provide a competing wall-clock scheduler or alarm daemon;
- external LLM inference is not wired;
- independent acceptance automation is not wired;
- the ledger reports zero independently accepted integrations;
- neither the 72-source nor 360-source operational target is complete.

These open items do not invalidate deployment of the deterministic planning core. They do block describing the current repository as a fully autonomous completed MVP-integration system. GEPA's internal evaluation scheduling, retries, engine switching, and convergence control remain Panoptes responsibilities and are not wall-clock dispatch.
