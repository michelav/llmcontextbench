# LLMCtxBench v1 refactoring plan — accepted design

Accepted by the research owner in this conversation; implementation branch: `refactor/llmctxbench-v1`.
This replaces the earlier draft and its proposed decisions. Implementation status is tracked in
[the slice checklist](../../specs/009-llmctxbench-v1/tasks.md), not inferred from this target design.

## Purpose and scope

Deliver a simpler domain-neutral benchmark and self-adaptation tool with one execution runtime,
first-class OpenAI/Claude/Gemini adapters, and definition-driven experiments. Keep the public lifecycle
`llmctxbench plan → execute → eval → export → metrics`, with `status` for progress.

Preserve taskParams (task-template inputs) separately from modelParams (generation settings).
Execution limits and MCP connection settings belong to execution/provisioning configuration.
Models and provisioning configurations are separate; a candidate is their pair.

## Accepted decisions

1. Historical reproduction relies on a code tag and Zenodo, not a new archival subsystem. Keep small
   useful fixtures; exact parity is not required for known defects. Do not move/delete existing outputs.
2. One runtime serves static and adaptive execution. Share client tool-loop code without erasing
   transport-specific measurements. Dataset and provider details stay inside their adapters.
3. Typed Python interfaces and internal registries suffice. MAPE-K describes responsibilities, not a
   required class hierarchy. Unknown providers fail; mock execution is explicit.
4. Single-parent extends: declaring-file-relative paths, recursive object merge, replacement arrays,
   null removes a key, cycles fail. Fully resolve before validation/planning. No general sweep engine.
5. Freeze definitions, workloads, candidate definitions and knowledge digests. Fingerprint these inputs,
   dataset digests, relevant source contents (including dirty edits) and dependency versions. Check on
   resume; reject conflicting fingerprints when combining identical design identities.
6. Atomic execution/request records replace the proposed journal. One writer lock per run. Write
   started before external work, then succeeded/failed atomically. A remaining started record means an
   uncertain interruption. Never silently rerun completed or uncertain work.
7. Explicit --retry-uncertain makes a distinct attempt, preserving the original unknown expenditure.
   Operator recovery retries are separate from automatic fallback limits. Corruption fails explicitly.
8. Each adaptive request has zero or more attempts. Reject admission when no candidate is feasible,
   unless best effort was explicitly configured. Targets only report violations. Goals declare upper
   or lower bounds and explicit windows; window warm-up reports the available sample count.
9. Fallback follows an ordered list, each candidate once, fresh context, default maximum two attempts.
   Default triggers are execution failures. An online sensor can reject an answer; rejected answers
   cannot be delivered. Deliver the first accepted answer; otherwise the request fails.
10. Record known expenditure even without a response. Unknown totals remain unavailable, with known
    subtotal and coverage separate. Admission estimates never replace observations. Arithmetic sums
    are derived; partial is completeness, not a sixth provenance category. Execution and evaluation
    costs remain separate; request-level sensor/feature costs are included explicitly.
11. Measure attempt/request elapsed time directly. Keep model/tool spans as diagnostics; omit calculated
    overhead from overlapping spans. Distinguish interruption gaps from measured active execution.
12. Controllers receive only deployable features and observations. Ground-truth sensors mark runs
    privileged. Check calibration/knowledge versus evaluation lineage across experiments, using a
    declared source-group key for related variants.
13. Adaptive runs execute serially in seeded order. Pair complete runs by scenario, seed and repeat;
    report paired differences and coverage. Do not assume independent requests. Provider cache isolation
    must be verified, not inferred from a cache key.
14. Initial simulation is seeded calibration resampling by candidate/feature group; missing coverage
    fails and outputs are estimated. Dataset derivation materializes directories with provenance.
15. Implement one verified slice at a time, report changes and impacts, update documentation and commit.

## Artifact authority and migration

See [the target contracts](../architecture/v1-contracts.md). Existing artifact contracts remain the
implemented baseline until the corresponding slice migrates readers and writers together.
Breaking changes use explicit versions and reject historical artifacts; historical readers live at
the old tag. No automatic in-place artifact migration or compatibility-reader framework is planned.

## Deferred work

No append-only journal/event sourcing, per-tool-call recovery checkpoints, content-addressed dataset
store, third-party entry-point plugin system, general sweeps, online learning, concurrent adaptive
runs, context-sharing fallback, general analytical simulation, or advanced statistical/report engine.
Reaction lag and settling time require a concrete experimental need and agreed formulas before addition.
Do not delete behavioral tests based on runtime or overlapping line coverage alone.

## Delivery and verification

The table below defines purposes; the checklist owns task state and evidence. Milestones:
S06 = durable static lifecycle; S09 = adaptive lifecycle with fallback; S12 = completed replacement.

| Slice | Purpose | Depends on |
|---|---|---|
| S01: Branch and accepted design | Reconcile the accepted design, tracking, and target architecture. | none |
| S02: Definitions and parameter names | Separate taskParams/modelParams; validate candidates and single-parent extends. | S01 |
| S03: Frozen planning and identity | Freeze inputs and validate execution identity and artifact versions. | S02 |
| S04: One runtime and dataset boundary | Route strategies through one runtime with domain-neutral capabilities. | S03 |
| S05: Usage and timing | Preserve complete/partial expenditure and directly measured latency. | S04 |
| S06: Durable execution and lifecycle readers | Persist atomic attempts; recover and rebuild collections consistently. | S05 |
| S07: Providers and remote MCP | Explicit providers/capabilities, preserved judge params, client-hosted remote MCP. | S06 |
| S08: Minimal adaptive lifecycle | Static/threshold control, knowledge, explicit/phased workloads, tool delay, all lifecycle commands. | S07 |
| S09: Fallback and request outcomes | Ordered fresh attempts; accepted delivery; sensors and cumulative request expenditure. | S08 |
| S10: Additional controllers and disturbances | Utility/circuit breaker/budget/exploration and required disturbances using existing interfaces. | S09 |
| S11: Research preparation and analysis utilities | Workloads, seeded resampling, knowledge diff, materialized derivation and simple reports. | S10 |
| S12: Remove superseded code | Remove replaced stacks and update final architecture and examples. | S11 |

Use fake datasets, mock providers, recorded fixtures, and injected clocks. Loopback MCP tests are
allowed; live provider tests need explicit approval and a cost/risk statement. No dependency installs,
lockfile edits, publication, or remote pushes are authorized by this plan alone. Track significant
steps in the worklog and use token_provenance=unavailable when actual usage is unavailable.

## Historical reproduction

Existing tags include `seams2027-paper`, `seams-v1-studies`, `seams-v2-freeze`, `seams-v3-freeze`,
and `seams-r3-freeze`. The owner has been asked for the Zenodo deposit reference. No DOI has been
verified, and this plan does not claim the historical evidence chain is complete. This omission does
not block tool implementation. Existing datasets, baselines, and runs remain untouched.
