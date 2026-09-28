# Scheduled Work heartbeat

This is the execution contract for the first real Work canary and the later Panoptes heartbeat.

## Hard boundary

A generic Scheduled Task is not a Work heartbeat. The scheduled item must be created from **Work mode** and must retain Work mode in Scheduled Tasks.

The repository code cannot create or change that product-mode property. The one unavoidable setup action is therefore performed in the ChatGPT Work UI. Everything after admission is repository-driven.

## Account-capacity precondition

Account capacity is external control state. Before scheduling substantive Panoptes work, use the account's explicit `panoptes.account-capacity/v1` record and current Settings/Usage or other explicit evidence.

- `EXHAUSTED`: do not expect Work to be admitted before the observed reset.
- elapsed `reset_at`: authorize one cheap Work canary only; elapsed time does not itself restore `AVAILABLE`.
- `AVAILABLE`: normal Panoptes heartbeat may run.
- `DEGRADED`: Panoptes may run with the cheaper configured reasoning level.

Never infer capacity from an ordinary Work failure.

## First Work canary

Create this task **inside Work**, pin **Sol** at the lowest/normal reasoning level that reliably follows GitHub instructions, and target only `AlkaiDynamics/Panoptes`.

Use this instruction verbatim:

> Read `AlkaiDynamics/Panoptes` main and `examples/pilots/PanoptesWorkCanary.json`. Operate only on branch `sandbox/work-canary-20260928`. Re-read the live main SHA and sandbox pre-run SHA. Create one new JSON file under `.panoptes/work-canary/` whose filename contains the UTC execution timestamp and whose content contains `scheduled_work_canary: "passed"`, `executed_at`, `source_main_sha`, and `sandbox_pre_run_sha`. Commit it with message `test(work): scheduled Panoptes canary`. Then re-read GitHub and verify the new commit exists on the sandbox branch and main did not change. Do not merge, deploy, publish, use Interception, or touch another repository. Report success only after that GitHub re-read proves the commit exists.

Canary success is the GitHub commit, not the task's prose response.

## Normal heartbeat after canary

Once explicit account evidence is updated to `AVAILABLE`, use **Sol + High** and run the repository-native driver:

```text
panoptes pilot-cycle
  --capacity <account-capacity.json>
  --account <account>
  --capacity-max-age-seconds <policy>
  --pilot <pilot-contract.json>
  --target <fresh-target-state.json>
  --state <project-control-state.json>
  --target-root <target-checkout>
  --output <next-prompt.json>
```

The Work invocation must:
1. refresh target GitHub state and write the fresh target-state JSON;
2. run `pilot-cycle`;
3. if it returns `waiting-for-executor-result`, stop without duplicating work;
4. if it returns `next-prompt-ready`, execute exactly that persisted prompt on the authorized sandbox;
5. commit the target implementation and `.panoptes/results/<prompt_id>.json` together;
6. verify the commit and checks by re-reading GitHub;
7. stop. The next scheduled Work heartbeat discovers the receipt and advances independently.

The executor's proposed `next_unit` is evidence only. The pilot DAG independently selects the next dependency-ready unit.

## Model policy

- canary/simple maintenance: Sol + Low/Normal;
- normal scheduled Panoptes heartbeat: Sol + High;
- Astra: escalation only after concrete evidence that the cheaper tier is inadequate.
