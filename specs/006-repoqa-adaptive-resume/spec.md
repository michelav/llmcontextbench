# RepoQA adaptive workflow with resumable episodes

Accepted implementation scope: the user-supplied five-slice plan (A–E).
This is a Level 3 research workflow change. No provider runs, dependency
installation, dataset edits, scorer changes, or canonical schema changes are authorized.

## Requirements and invariants

Prepare language-stratified target splits (seed 20260929), paired candidate trials,
context budgets and shared balanced workloads. Execute four independent policy
arms under stationary and degradation/recovery conditions. Policy version 2 and
decision/run schema 1 remain fixed. Preserve canonical trial identity and treatment.

Resume restores policy state by decide/observe replay. Completed success/error/unserved
outcomes remain final. Incomplete provider attempts require explicit retry permission
and carry unavailable prior cost. Reject identity changes, corruption, gaps and
concurrent writers. Durable packets precede projections; repair missing projections
without executing a model. Recovery is between requests only.

Freeze calibration before held-out execution. A pooled baseline p90 is the default
latency objective. Select the smallest qualifying per-tool delay from 100/250/500/1000
ms, or report stationary only. Analyze all scheduled requests with explicit coverage,
paired target bootstrap intervals and interrupted-block sensitivity.

## Acceptance

Provider-free mocked episodes cover all arms/scenarios, interrupted execution,
replay equivalence, canonical validation, completed no-op, and reconstruction.
Synthetic analysis verifies denominators, pairing, group resampling and uncertainty.
Paid calibration/study and scorer dependency installation remain separate gates.
