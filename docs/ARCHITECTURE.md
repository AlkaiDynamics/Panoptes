# Panoptes Architecture

This document is the architectural source of truth for the current Panoptes branch. Historical implementation notes belong in Git history, not in competing live documentation.

## Product contract

Panoptes turns an authoritative goal and constraints into a bounded, dependency-aware sequence of work while preserving evidence about what has actually been implemented, tested, blocked, deferred, or accepted.

The lightweight target is 72 distinct supplied repositories with operational integration evidence. The master target is 300. Generated campaign entries, descriptions, hypotheses, prompts, mocks, and planning artifacts do not count as completed integrations.

## System flow

```text
Goal + constraints
      |
      v
Pinned create-mvp planning engine
      |
      v
Panoptes corpus adapter ---------> 72 / 300 candidate campaigns
      |                                  |
      |                                  v
      |                            component DAG
      |                                  |
      v                                  v
checks + review <------------ SQLite continuation kernel
                                      |
                                      v
                           dependency-aware next task
                                      |
                      +---------------+---------------+
                      |                               |
                  executable                       blocked
                      |                               |
                      v                               v
                evidence record              planning fallback
                      |                               |
                      +---------------+---------------+
                                      |
                                      v
                              next bounded prompt
```

## Components

### 1. End-to-end planning driver

`vendor/create-mvp/build.mk` is pinned from `qwadratic/create-mvp` at revision `1b61d541a4712a7571db2a3fbd2dee0fc9cbff1d`. `examples/e2e/Makefile` runs that engine with `python3 -m panoptes.e2e_agent` as its plan/build/review adapter.

The pipeline performs goal → plan → dependency-ordered builds → checks → review. Its PASS verdict certifies planning artifacts only; it is not a claim that 72 or 300 repositories have been operationally integrated.

### 2. Corpus and campaign generator

`panoptes/corpus.py` loads the bundled repository corpus, applies inspected evidence where available, excludes assessed-empty repositories and deferred lightweight candidates, and produces deterministic 72- or 300-candidate plans.

Inspected confirmed capability labels replace description-derived hypotheses for selection. Deferred candidates are backfilled so they do not consume target slots.

### 3. Continuation kernel

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

`panoptes/inference.py` defines an asynchronous `InferenceBackend` protocol and a thin `InterceptionBackend` client. It uses the actual bridge contract in `zhenrez/Interception` PR #4 at `a7bf0d5df64c4696a081404771c146233c3bce37`. Interception retains the durable request ledger, checkpoint and RETURN validation, GitHub/Work transport, and caller continuation. Panoptes must save only the returned request ID in its own existing scheduler node checkpoint. The scheduler-to-client caller is not wired yet.

### 4. Dependency-aware planner

`panoptes/planner.py` validates bounded component DAGs, rejects cycles and missing dependencies, installs a plan once, and selects the next ready task by longest remaining dependency chain.

Verified tasks require evidence and become immutable. A plan cannot be silently replaced; changing the installed graph requires an explicit migration. If all executable work is blocked, the planner emits independent planning/refinement work rather than cancelling continuation.

### 5. Evidence and audit adapters

Panoptes currently carries six implemented/tested source contributions in its evidence ledger:

1. `qwadratic/create-mvp` — pinned planning framework used by the end-to-end Make pipeline.
2. `hermes-labs-ai/hermes-blind` — evidence-gated audit-prompt scaffold; it cannot set acceptance flags.
3. `ncz-os/mnemos` — dependency-free Python 3.11 JSON/HTTP adapter to a separately operated Mnemos service.
4. `AmanPriyanshu/GeneticPromptLab` — deterministic provider-neutral genetic prompt-round planner without paid inference.
5. `shivangdoshi07/brainstormer` — deterministic projection of validated Panoptes component DAGs into Excalidraw element skeletons; the upstream web server and provider stack are excluded.
6. `mims-harvard/Qworld` — question-specific Recursive Expansion Tree executed as 17 typed stages with bounded scenario, perspective, criterion, and lineage handoffs. Stage results are revision-bound; generic receipts, inconsistent state, destructive rewrites, and polarity reversal fail closed. Structurally finished criteria stop at `pending_review`, not acceptance. Upstream provider clients, embeddings, and model SDKs are excluded.

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

## Counting model

Panoptes intentionally separates four concepts:

- **Candidate:** a repository elected into a generated campaign.
- **Implemented:** Panoptes contains source-specific implementation evidence for that contribution.
- **Tested:** behavior evidence exists in the engine/test suite.
- **Accepted:** an independent review has accepted the contribution against the source-specific gate.

Only operational source-specific work may contribute toward the 72/300 integration goals. Campaign size is not completion count.

## Security and external-service boundary

The Mnemos adapter is optional and points to a separately operated service. API keys are read from an environment variable rather than a CLI argument. The client constrains the configured base URL to reduce credential leakage through redirects or malformed origins.

No external model-provider credential is required for the deterministic planning pipeline or genetic round planner.

The Brainstormer adapter is also dependency-free. It consumes an already-validated component DAG and emits deterministic visualization data; it does not expose the upstream server's unrestricted CORS or in-memory session surface.

## What is not wired yet

The current repository does not provide:

- autonomous scheduler/alarm dispatch;
- an autonomous scheduler caller for the native inference client;
- automatic implementation of elected repositories;
- independent acceptance automation;
- a completed 72-source or 300-source operational product.

Those are deployment/integration layers above the deterministic planning and state core described here.
