# Scheduled Work pilot contracts

These two files are **project-specific instructions**, not execution receipts or current capacity observations. Refresh every pinned ref and read the linked authority at the start of each Work invocation. ARTTOO's earlier Alkai canvas repository is not this pilot's canonical target.

Each scheduled Work task must check external account admission before starting, run in Work Mode, and then supply a fresh account-matched capacity observation and an explicit `--capacity-max-age-seconds` to Panoptes. A scheduled task in another execution mode does not count as a Work pilot run. Do not create or claim a run when Work capacity, private sandbox access, target lease, or Interception RETURN is unresolved.

For each project, keep control and treatment on isolated branches at equivalent starting commits and comparable dependency-ready units. The control uses the existing ARTTOO Driver method or the existing Archotraz hand-written prompt; the treatment uses Panoptes plus a completed Interception reflection. Preserve prompt text, model/effort, Work usage, branch heads, tests, interventions, failures, and elapsed time for both. Run 2 must ingest Run 1's committed target receipt once and use a different unit chosen by Panoptes from current dependencies.

Record: correct scope, passing behavior checks, repeated work, misunderstandings, human interventions, Work usage, and causal Run 1 → Run 2 continuation. An untested reflection candidate has no measured advantage. Do not promote the treatment or increment the independent acceptance ledger until the four real Work runs and comparison pass.

The repository-native target receipt discovery/cycle driver and independent dependency selector are now implemented in `panoptes/pilot_cycle.py` and exposed as `panoptes pilot-cycle`. The executor's proposed next unit is retained as evidence while the pilot DAG independently selects the next dependency-ready unit.

The first live execution gate is the Panoptes-only Work canary in `PanoptesWorkCanary.json` and `docs/WORK_HEARTBEAT.md`. A generic Scheduled Task does not satisfy this gate; the task must be created from Work mode and must produce a verified GitHub commit on the isolated canary branch.

Still outstanding: the actual scheduled-Work canary receipt, the private GitHub → Work → RETURN → same-caller Interception proof, and the measured multi-run project comparison. Do not claim those gates from repository tests alone.
