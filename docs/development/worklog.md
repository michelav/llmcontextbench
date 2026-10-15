# RepoQA prototype development log

## 2026-10-02 — Complete prototype slices 1 and 2

Accepted implementation plan: four internal slices A–D, scoped to surface
validation, model-free policies and sidecar contracts. Prototype semantics were
updated before implementation. The repository's existing unrelated changes were
preserved. Token usage provenance: unavailable.

- **A — Surface enforcement completed:** planning rejects empty/unknown operation
  lists; every operation is discovered and invoked through FastMCP; all omitted
  operations reject direct and transport calls. Artifact spying covers all four
  operations and excludes oracle/native-task/hidden-prompt/raw inputs.
  Focused surface/tool validation: **40 passed**. Adapter changes were unnecessary.
- **B — Contracts completed:** centralized canonical configuration IDs; explicit
  nominal variant mapping in RepoQA workload preparation; validated features,
  metrics, context-fit budgets/provenance and unique candidate IDs. Added versioned
  camelCase decision and run sidecars with identity/outcome metadata outside
  policy inputs. Sidecars are models only, without writers.
- **C — Estimation completed:** observe() belongs to policy arms; frozen/fixed
  arms record without updating. A shared estimator rejects mixed keys, computes
  rolling successful means, retains source provenance/counts, and independently
  applies the three-sample latency/token threshold with calibration fallback.
  Each state copies calibration and starts fresh. No time-based expiry.
- **D — Routing completed:** objective priority after cooldown, k+6 switching,
  exact 10% material improvement, known-before-missing ordering, canonical ties,
  ineligibility override, explicit unserved fixed arms, and transient probes that
  commit normal routing state. Policy version **2** is the documented baseline
  to pin before future calibration. Deterministic tests cover these branches.

Validation commands:

```bash
pytest -q tests/test_repoqa_surfaces.py tests/test_repoqa_tools.py
pytest -q tests/test_adaptive_policy.py
pytest -q tests/test_repoqa_surfaces.py tests/test_repoqa_tools.py \
  tests/test_adaptive_policy.py tests/test_provisioning_configurations.py \
  tests/test_artifact_contracts.py tests/test_dataset_provenance_artifacts.py \
  tests/test_util_artifacts.py
git diff --check
```

Final acceptance result: **127 passed**; whitespace validation passed.
The adaptive file contains 61 focused tests (including parameterized cases).
No provider execution/evaluation, dependency installation or lockfile changes.

Compatibility: CLI, canonical artifacts, RepoQA scoring and phase separation
remain unchanged; no artifact migration is needed. Internal ad hoc consumers
must supply explicit bins and context-fit assessments and replace caller-controlled
adaptive/evaluation flags with policy.observe(). Actual prompt/tool budgeting,
episode execution, delay injection, calibration and sidecar writing remain later
slices. Caller-provided context-fit estimates must remain traceable when those
components are integrated.

## Resumable A–E workflow implementation — 2026-10-08

Implemented reproducible catalogs/workloads, durable episode execution, replay and
uncertain-call recovery, controlled local-MCP delays, calibration/freeze operations,
and saved-episode analysis. See `repoqa-resumable-workflow.md` and
`specs/006-repoqa-adaptive-resume/` for the executable protocol and slice history.

Final targeted suite: **159 passed**, covering all four arms under both scenarios,
interruption/resume equivalence, terminal errors/unserved observations, canonical
artifact/evaluation compatibility, input drift/corruption/locking, calibration
qualification/provenance, token coverage, paired target bootstrap and interruption
sensitivity. Compilation and `git diff --check` passed. Real scorer smoke returned
best_match with similarity 1.0 after repairing an ignored local venv interpreter link.
No provider experiments, dependency installation or lockfile changes were performed.
Development token usage remains unavailable. Paid calibration and study gates remain
unexecuted; unknown prior expenditure after uncertain attempts is not imputed.

## 2026-10-15 — SEAMS v2, S0: v1 provenance

Plan: `docs/development/seams2027-plan.md`. The v1 long64 baseline and studies were
measured with commit `2a97eb6`, now tagged `seams-v1-studies`. Strict
`llmctxbench study status studies/repoqa-long64-latency` verified against it.
Untracked v1 artifacts (sha256 prefixes): `baselines/repoqa-long64/frozen.json`
`9f854dab2215c164`; prepared studies budget `e205d5518a18cee1`, latency
`2f348d2b66e9476c`, reliability `5f6eae7d756b25d5`.

Added `--allow-source-drift` to `study status`/`analyze` (read-only; experiment,
dataset and frozen-artifact hashes still checked; drifted sources reported as
`sourceDrift`). Found and fixed nondeterministic paired-bootstrap intervals
(set iteration under hash randomisation); v1 `analysis.json` files were
regenerated deterministically with 1000 replicates, seed 42. Means unchanged;
intervals shifted slightly (budget vs mcp-lean now [-916, -16] ms).
Validation: `pytest tests/test_study_protocol.py` 12 passed; `pytest -k cli` 68 passed.

## 2026-10-15 — SEAMS v2, S1: correctness fixes

Opt-in options (defaults reproduce v1): `incumbentScope` (router/reliability),
`resetOnRecovery` (reliability), `unknownUsage` and `forecast` (budget). Prepare now
records `tokenQuantiles` and `calibrationSizeMix`, and episode IDs cover all
behaviour-changing inputs. Only non-fingerprinted files changed
(`adaptive/study_policy.py`, `studies/{models,study}.py`), so the v1 baseline still
verifies strictly. Validation: `tests/test_study_protocol.py` 19 passed; new
`tests/test_study_v1_regression.py` replays every recorded v1 decision identically
(3 studies, 42 episodes).

## 2026-10-15 — SEAMS v2, S2: router detection and recovery

Opt-in router options: `estimator: pooled-ratio`, `minimumObservations`,
`estimateTtlRequests`, `probeMode: targeted` + `avoidedProbeInterval`,
`latencyQuantile`, and `switchOnObjectiveMiss`. The last one fixes a deviation from
the documented contract (an incumbent missing the objective could only be replaced
by a cheaper alternative). Replaying v1 shows that bug never triggered there. The v1
recovery stall came from stale estimates instead: at request 90 of seed 202 the
adaptive router still estimated inline at 7.0–9.0 s (actual about 2.8 s) after one
fresh inline observation in 30 requests, because round-robin probes rotated across
both MCP arms. Validation: `pytest -k "adaptive or study"` 157 passed; v1 decisions
still replay identically.

## 2026-10-15 — SEAMS v2, S3b: cascade policy

Added `type: cascade` (primary + one fallback on observed trigger failures, optional
`primaryMaxSteps` and repository `memory`). `adaptive/study_runner.py` now runs
attempts through one helper; non-cascade packets keep their exact v1 layout. Cascade
packets record per-attempt trials, results and observations, and every attempt is
projected as a canonical trial. Analysis gained `fallbacks`, `tokensLowerBound` and
`wastedTokensLowerBound`. This changes a fingerprinted file: the v1 baseline now
needs `--allow-source-drift` for `status`/`analyze`, and v2 collection needs the
v2 baseline (S6a). New `tests/test_study_cascade.py`: 9 tests (trigger-only fallback,
canonical projection, step override, source memory, resume between attempts,
explicit retry during fallback, replay, validation, analysis).

## 2026-10-15 — SEAMS v2, S3: reference policies and effects

Added `schedule` (phase oracle), `random-eligible` and budget `mode: pace` policies,
plus `fault` and `token-quota` scenario effects. Scenario entries without `kind`
remain delays. Decision records now use `schemaVersion` 4 with `quotaWaitMs`,
`faultsInjected` and `controllerMs`. This is the last planned change to the
fingerprinted runner before the S6a code freeze. New `tests/test_study_effects.py`: 8 tests.

## 2026-10-15 — SEAMS v2, S4: replay and opportunity finder

Added `study replay` (`src/ctxbench/studies/replay.py`) and `study counterfactual`.
Replay drives the real `Controller` over calibration observations, joined to
recorded tool calls and steps. Fidelity check: replaying the v1 latency scenario
from v1 calibration gives deadline misses per episode of inline 32.5, frozen 35.1
and adaptive 44.1, against live v1 values of 30, 34 and 46. The counterfactual
lean→default cascade reproduces 0 failures and ≥8.77k tokens per request.
Exploratory S-A sweep (v1 calibration, untuned v2): at 10–12 s limits with ≥2 s
per tool-call delay, adaptation roughly halves frozen's misses at modest token cost.
At an 8 s limit, MCP's own tail violates the limit and frozen already prefers inline,
so there is no opportunity (the C3 case). Untuned v2 is not consistently better than v1.
Note: running slow CLI tests while editing files can trip the legacy adaptation
CLI's "uncommitted files changed" guard; rerun those tests on a quiet tree.

## 2026-10-15 — SEAMS v2, S5: analysis and figures

Added all-request pass rate, switches, probe cost, controller overhead, per-phase
summaries, reaction/recovery lags, arm aggregates, and paired cluster-bootstrap
intervals for misses, tokens, failures and pass. Latency intervals are unchanged
(v1 adaptive vs frozen, inline-delay: [689, 1235] ms). New v1 evidence from the paired
metrics: adaptive vs frozen in inline-delay has +12.5 points deadline-miss rate
[8.0, 17.7] and −2.1 points pass rate [−5.2, 0.0]. Recovery lag was 16.5 requests
in 2 of 3 seeds; the third never returned. Plots were redrawn as labelled small
multiples plus a cost/miss trade-off plot, rendered with librsvg and inspected. The
palette is the dataviz reference instance; the validator was not run (no node).
