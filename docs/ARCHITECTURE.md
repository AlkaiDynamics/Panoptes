# Panoptes Architecture

This document is the architectural source of truth for the current Panoptes branch. Historical implementation notes belong in Git history, not in competing live documentation.

## Product contract

Panoptes turns an authoritative goal and constraints into a bounded, dependency-aware sequence of work while preserving evidence about what has actually been implemented, tested, blocked, deferred, or accepted.

The lightweight target is 72 distinct supplied repositories with operational integration evidence. The master target is 360. Generated campaign entries, descriptions, hypotheses, prompts, mocks, and planning artifacts do not count as completed integrations.

GEPA is the primary prompt-evolution and optimization spine. `qwadratic/create-mvp` remains the end-to-end goal → plan → dependency-ordered build → checks → review spine. The Prompt/Skills Library is an incrementally assembled source of exceptional capabilities behind stable interfaces; it is neither the principal architecture nor a prerequisite for the heartbeat to function.

## Account-capacity pre-gate

Work/Codex account capacity is external control state, not project state. Panoptes stores one `panoptes.account-capacity/v1` observation per account and derives a read-only admission decision before substantive control work.

The four observed states are `AVAILABLE`, `DEGRADED`, `EXHAUSTED`, and `PROBE_AVAILABLE`. Exhaustion may be set only from explicit evidence whose source is one of `settings-usage`, `limit-banner`, `codex-status`, or `manual`; an ordinary Work invocation failure is never capacity evidence.

`reset_at` is an observation, not a durable scheduling truth. While an explicit `EXHAUSTED` reset is still in the future, Panoptes fails closed without touching project continuation state. Once the observed reset time has elapsed, only a cheap Sol/low probe is admissible; the account is not promoted to `AVAILABLE` merely because time passed. A successful explicit probe observation may later update the external account record.

Alkai and zhenrez records are independent. Exhaustion on one account never authorizes failover to the other account.

The gate has two decisions:
- `admit_work`: whether a Work invocation is worth attempting at all.
- `allow_panoptes`: whether substantive Panoptes continuation may run. Probe mode deliberately sets this to false.

No usage scraping or machine-readable allowance inference is implemented in this slice.

## System flow

```text
ChatGPT Work/Tasks wall-clock heartbeat
                  |
                  v
      recover Panoptes + target state
                  |
                  v
     GEPA internal optimization spine
  slices -> candidates -> Pareto frontier
  iterations -> plateau/retry/engine switch
          -> budget/convergence gate
                  |
                  v
       one target-specific prompt artifact
                  |
                  v
       separate target-project executor
                  |
                  v
 commit + evidence + checkpoint result
                  |
                  +------> next heartbeat ingests once
```

## Components

### 1. External invocation and GEPA control spine

Wall-clock recurrence belongs only to ChatGPT Work/Tasks. `panoptes/control.py` owns the work performed inside one invocation: validate recovered target state, prevent duplicate prompt issuance, evaluate bounded prompt candidates over explicit slices, preserve the Pareto frontier and internal control state, and persist one next-prompt artifact plus its result contract.

`panoptes/integrations/gepa.py` adapts the pinned `developzir/gepa-mcp` reflective optimization loop at `398e514bfa456794225219fc9bd433d4f59983e2`. It adds the persistent provider-neutral scheduling semantics Panoptes requires: candidate/frontier state, evaluation slices, iterations, plateau-driven engine switching, bounded retries, metric budgets, and explicit convergence. The official MIT GEPA implementation at `d771eb21b5dd3228bc3f567293d2ccfc423fc900` is a semantic reference for per-slice Pareto state and bounded engine control. Model-backed reflection, when needed later, must use the Interception inference seam.

The first operational target is Archotraz. `examples/archotraz/target-state.json`, `control-state.json`, and `next-prompt.json` prove control/generation ownership only. The separate Archotraz Work task owns repository mutation and returns the exact `panoptes.execution-result/v1` envelope embedded in the prompt artifact. A verified result names the completed unit, concrete evidence, its immutable Archotraz commit, and a proposed next unit. Panoptes accepts the result only after refreshed target state independently contains that commit on `main` or in `active_work` and carries the same next-unit contract. Verified work must advance to a distinct unit; blocked or failed work may preserve or redirect it.

### 2. End-to-end planning driver

`vendor/create-mvp/build.mk` is pinned from `qwadratic/create-mvp` at revision `1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d`. `examples/e2e/Makefile` runs that engine with `python3 -m panoptes.e2e_agent` as its plan/build/review adapter.

The pipeline performs goal → plan → dependency-ordered builds → checks → review. Its PASS verdict certifies planning artifacts only; it is not a claim that 72 or 360 repositories have been operationally integrated.

### 3. Corpus and campaign generator

`panoptes/corpus.py` loads the bundled repository corpus, applies inspected evidence where available, excludes assessed-empty repositories and deferred lightweight candidates, and produces deterministic 72- or 360-candidate plans.

Inspected confirmed capability labels replace description-derived hypotheses for selection. Deferred candidates are backfilled so they do not consume target slots.

At pinned `iamadityakumar/forge` revision `a80c38545ae09db5e76ecd2f4da91e23f19a39c3`, the Git tree has no license file despite the README's MIT badge. Its worker/PostgreSQL lifecycle overlaps Panoptes continuation, and its direct Groq backend conflicts with the Interception inference boundary. The evidence registry defers it pending license and boundary review, excludes it from both campaign sizes, and backfills from the remaining corpus. The contribution ledger is seven implemented, seven tested, zero independently accepted.

### 4. Continuation kernel

`panoptes/core.py` stores durable state in SQLite using WAL mode. It owns:

- authoritative goal and constraints;
- monotonic checkpoints;
- destination repository state;
- expiring single-writer leases;
- idempotent run receipts;
- append-only decisions with explicit supersession;
- installed plan and task progress.

The kernel is intentionally deterministic. It does not itself call an LLM, schedule an alarm, or claim source integrations.

### Native inference boundary

`panoptes/inference.py` defines an asynchronous `InferenceBackend` protocol and a thin `InterceptionBackend` client. It uses the actual bridge contract in `zhenrez/Interception` PR #4 at `a7bf0d5df64c4696a081404771c146233c3bce37`. Interception retains the durable request ledger, checkpoint and RETURN validation, GitHub/Work transport, and caller continuation. Panoptes saves only the returned request ID in its own work-item checkpoint. A GEPA reflection step may use this seam when model inference is actually required; recurrence remains external.

### 5. Dependency-aware planner

`panoptes/planner.py` validates bounded component DAGs, rejects cycles and missing dependencies, installs a plan once, and selects the next ready task by longest remaining dependency chain.

Verified tasks require evidence and become immutable. A plan cannot be silently replaced; changing the installed graph requires an explicit migration. If all executable work is blocked, the planner emits independent planning/refinement work rather than cancelling continuation.

### 6. Evidence and audit adapters

Panoptes currently carries seven implemented/tested source contributions in its evidence ledger:

1. `qwadratic/create-mvp` — pinned planning framework used by the end-to-end Make pipeline.
2. `hermes-labs-ai/hermes-blind` — evidence-gated audit-prompt scaffold; it cannot set acceptance flags.
3. `ncz-os/mnemos` — dependency-free Python 3.11 JSON/HTTP adapter to a separately operated Mnemos service.
4. `AmanPriyanshu/GeneticPromptLab` — deterministic provider-neutral genetic prompt-round planner without paid inference.
5. `shivangdoshi07/brainstormer` — deterministic projection of validated Panoptes component DAGs into Excalidraw element skeletons; the upstream web server and provider stack are excluded.
6. `mims-harvard/Qworld` — question-specific Recursive Expansion Tree executed as 17 typed stages with bounded scenario, perspective, criterion, and lineage handoffs. Stage results are revision-bound; generic receipts, inconsistent state, destructive rewrites, and polarity reversal fail closed. Structurally finished criteria stop at `pending_review`, not acceptance. Upstream provider clients, embeddings, and model SDKs are excluded.
7. `developzir/gepa-mcp` — provider-neutral reflective optimization control, extended with persistent evaluation slices, Pareto frontier state, bounded retries, plateau switching, and budget/convergence gates. Gemini, MCP, and provider SDK paths are excluded.

Independent acceptance remains a distinct gate. The current accepted integration count is zero.

## State-transition invariants

These rules are enforced by code and must remain true across deployment wrappers:

1. **One live writer.** Mutating state requires a current owner lease.
2. **Checkpoint match.** A mutation based on a stale checkpoint fails rather than overwriting newer state.
3. **Run idempotency.** Reusing a run ID with identical input returns the recorded receipt; conflicting input for the same run ID is rejected.
4. **Failed runs do not advance state.** They still record a receipt so they cannot later replay as a new run.
5. **Verified means evidenced.** A task cannot become verified without evidence, and its dependencies must already be verified.
6. **Verified tasks are immutable.** Later work must extend state rather than rewriting a completed task.
7. **Plan replacement is explicit.** Installing a different DAG over an existing plan fails.
8. **Blockers redirect work.** When execution is blocked, the next prompt must move to useful planning, inspection, interface, fixture, or evidence work and keep continuation enabled.
9. **Descriptions are not evidence.** Repository descriptions and generated prompts cannot be used to claim integration completion.
10. **Draft commits are first-class checkpoints.** A verified executor commit may remain on a refreshed active branch or pull request; it is not forced onto `main` merely to advance control state.
11. **Success advances the unit.** A verified result must identify the outstanding unit and supply a distinct next unit that exactly matches independently refreshed target state.
12. **Capacity state is external and explicit.** Work failure cannot change account capacity state, account records never cross-apply, and elapsed reset time authorizes only a probe until fresh evidence restores availability.

## Counting model

Panoptes intentionally separates four concepts:

- **Candidate:** a repository elected into a generated campaign.
- **Implemented:** Panoptes contains source-specific implementation evidence for that contribution.
- **Tested:** behavior evidence exists in the engine/test suite.
- **Accepted:** an independent review has accepted the contribution against the source-specific gate.

Only operational source-specific work may contribute toward the 72/360 integration goals. Campaign size is not completion count.

## Security and external-service boundary

The Mnemos adapter is optional and points to a separately operated service. API keys are read from an environment variable rather than a CLI argument. The client constrains the configured base URL to reduce credential leakage through redirects or malformed origins.

No external model-provider credential is required for the deterministic planning pipeline or genetic round planner.

The Brainstormer adapter is also dependency-free. It consumes an already-validated component DAG and emits deterministic visualization data; it does not expose the upstream server's unrestricted CORS or in-memory session surface.

## What is not wired yet

The current repository does not provide:

- an in-repository alarm/cron daemon (external Work/Tasks owns recurrence by design);
- a GEPA reflective-proposal caller for the native inference client;
- automatic implementation of elected repositories;
- independent acceptance automation;
- a completed 72-source or 360-source operational product.

Those are deployment/integration layers above the deterministic planning and state core described here.
