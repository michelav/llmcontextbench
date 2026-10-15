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

## 2026-10-15 — SEAMS v2, S6 (draft): scenario selection and pre-registration

Added `tools/seams/make_grids.py`, which generates the replay grids
(`examples/studies/replay/*.grid.json`), the live definitions
(`study.seams-{cascade,degradation}.json`) and the pilots
(`pilot.{cascade,degradation}.json`), all pointing at the future v2 baseline.
Exploratory replay on v1 calibration (`studies/replay-v1calib/`, untracked) gives this
opportunity map: S-A at 10–12 s limits with ≥ 2 s per-call delay shows opportunity, and
v2 roughly halves v1's misses. An 8 s limit (C3), the S-B quota flip and S-C MCP faults
vs functions (C1) are negative. Live collection therefore narrows to S-D cascade and
S-A degradation (about 5.8k requests instead of 7.2k). Draft pre-registration:
`docs/development/seams2027-preregistration.md`.

## 2026-10-15 — SEAMS v2, S6a: v2 baseline and binding parameter selection

**v2 baseline.**
- Prepared from the unchanged baseline definition at tag `seams-v2-freeze`.
- Executed with real provider calls: 720 requests, 30 episodes × 24.
- Evaluated with the deterministic RepoQA scorer: 719 evaluated, 1 skipped (a failed `local-mcp-lean` response).
- Frozen; `frozen.json` sha256 `dc9d1cf0…`.

**Drift versus v1 calibration** (`tools/seams/compare_baselines.py` → `baselines/repoqa-long64-v2/drift-v1-v2.json`):
- MCP default mean latency rose 32–43 %, with p90 going from 8–10 s to 13–14 s;
- the other configurations rose 0–19 %;
- tokens and pass rates are essentially unchanged.

**The pre-registered S-A rule failed closed.**
- At 10–12 s, MCP default is infeasible even without delay; opportunity is negative at every eligible point.
- The S-A rule was amended before any pilot, using calibration data only:
  - the pair is inline + MCP lean;
  - the limit is fixed as the smallest grid limit covering lean's per-bin calibration p90.
- **Selected:** L14000, 3000 ms per tool call on requests 31–60, policy `v2-rr10-ttl8` (the only candidate within the stationary token cap). Replay estimates misses per episode as frozen 15.4, v2 7.2, oracle 0.8, and tokens per episode as v2 0.85M against inline 1.56M.
- **Inline + function lean** (request-scope delay of 6000/9000 ms) also fails closed: v2 spends about 1.5 × frozen tokens when nothing is disturbed. By your decision, it is a replay-only negative case (C5).

Tooling changes:
- `select_parameters.py` gained `--limits`, `--delays`, `--feasible-config`/`--baseline`, and fail-closed on a non-positive gap.
- `make_grids.py` generates per-pair grids and takes `--selection PAIR=RECORD`.
- New `compare_baselines.py`.

The pre-registration is now binding (see its deviation record and digests). The four definitions prepare cleanly against the v2 baseline, provider-free.

## 2026-10-15 — SEAMS v2: within-run latency variation in the calibration runs

`tools/seams/within_run.py` (output `baselines/repoqa-long64-v2/within-run.json`) shows where the v1→v2 drift came from.

**v1 run.** It was flat for 75 minutes: MCP default median 5.9–7.2 s, with at most 4 % of requests above 10 s.

**v2 run (88 minutes, all configurations interleaved).**
- MCP default had slow periods of 15–30 minutes, each spanning roughly 100–250 requests:
  - median 10.0–10.4 s, with 50–61 % of requests above 10 s;
  - in between and at the end it recovered (6.3 s in the last window, about v1's level).
- Function lean had one slow window (15–30 min: median 10.7 s, 58 % of requests above 10 s).
- MCP lean and function default stayed stable.
- Inline sped up (4.4 → 2.6 s) and reached 100 % cached input after the first 15 minutes.

**Where the time goes.** The slowdown is in model-call time:
- tools take about 10 ms per request, with no retries and no rate-limit waits;
- output (about 54 tokens per call), input sizes and cache shares are similar across configurations;
- yet MCP default took 39–47 ms per output token, against 30–35 ms for function default.

The cause is not identified.

**Implications.**
- The frozen v2 baseline recorded MCP default during slow periods, so its knowledge is biased by when calibration ran. This is natural evidence for C1, C2 and C4.
- The live S-A pair (MCP lean) was stable, so the injected delay remains necessary.
- Natural slow periods during collection are a threat to validity. Shuffled arm order and wall-clock records (already pre-registered) mitigate it; report them.

**Fix: `pace` budget policy.**
- **Symptom.** `pace` stopped serving as soon as spending reached the expected reserve for the remaining requests. In replay, at an 800k cap it left 63 requests unserved and spent only 445k tokens.
- **Cause.** A single large request costs more than the mean reserve, which made it look unaffordable.
- **Fix.** `pace` now serves that request with the cheapest configuration (reason `paced_reserve`). It stops only when even the cheapest no longer fits.
- **Scope.** The change is in `adaptive/study_policy.py`, which is not fingerprinted, and no pre-registered study uses `pace`.

## 2026-10-15 — SEAMS v2: S-E inline degradation added before the pilots

Exploratory replay of two further scenarios on v2 calibration (pair inline + MCP lean):

**Inline degradation (S-E): added.**
- Setup: at a 10 s limit, lean is infeasible at its p90, so every router keeps inline. Inline is then delayed per request.
- At +9 s: frozen 28.4 misses / 1.47M tokens, v2 15.7 / 1.19M, oracle 5.9.
- v2 beats frozen on both misses and tokens. Fixed lean (16.9 misses / 0.55M) is a strong competitor only while the disturbance lasts.
- +3 s gives no opportunity.
- The selection rule (`--infeasible-config`) picks L10000, +9000 ms and `v2-t10-ttl10`. The pre-registration records the addition, the digests and pilot P3.

**Token cap: replay-only negative case.**
- A static per-size rule matches the `pace` policy, which uses feedback from the token ledger, because cost is predictable from request size (C2 fails).

## 2026-10-15 — SEAMS v2: why tool configurations are slower (interaction patterns)

`tools/seams/interaction_patterns.py` (output `baselines/repoqa-long64-v2/interaction-patterns.json`) reads the calibration execution traces.

**Where the time goes.**
- Tool-configuration latency is almost entirely model time: tools take about 10 ms per request and the harness about 30 ms.
- Tool configurations make about 3.9 sequential model calls per request; inline makes 1.

**Cost per model call** (least-squares fit, about 2,370 calls per run):

| Run | Fixed cost per call | Per 1k input tokens | Per 100 output tokens | R² |
|---|---|---|---|---|
| v1 | 1.28 s | about 0.01 s | 0.68 s | 0.55 |
| v2 | 1.52 s | about 0.01 s | 0.81 s | 0.45 |

- Inline pays the fixed cost once; tool configurations pay it about 4 times.
- So a provider-wide slowdown in the fixed cost affects tool configurations about 4 × more than inline.

**Interaction pattern.**
- The dominant sequence is `list_files > list_symbols > get_symbol` → answer: 62–83 % of requests, depending on configuration.
- `list_files` returns the same information for a repository every time, yet costs a full round trip.
- Parallel tool calls are allowed but are used in only 4–17 of 144 requests, because each step depends on the previous one.
- Lean's median is similar to default's. Its tail comes from exploration loops: repeated `list_symbols` in 5–8 calls takes 13–16 s, and the same loops cause its step-limit failures.

**MCP vs functions.** No per-call difference in v1 (1.32, 1.56 and 1.75 s for both). The v2 gap comes from the slow periods.

**Scope.** The surface code (`adapters/repoqa/{tools,mcp_server,provider}.py`) is fingerprinted. A redesigned surface therefore needs a new baseline. It is deferred until after the pre-registered collection, in a separate worktree.

## 2026-10-15 — v2 pilots, direct surface, v3 baseline

**v2 pilots P1–P3** (`tools/seams/run_pilots.sh`, gates `tools/seams/pilot_gates.py`): 480 requests, 5.3M answer tokens, 74 min. All three missed at least one pre-registered gate; details in the pre-registration ("Pilot outcomes on v2").
- P1 cascade: 0 final failures, but 1.48 × default tokens. Lean failed 6 of 6 on `rs_004`.
- P2 MCP-lean degradation: lags passed; delay-phase misses 5 against frozen's 8 (gate 4).
- P3 inline degradation: MCP lean is too slow to be a fallback at a 10 s limit; recovery lag 9.

**Direct surface.** The redesign parked earlier was brought forward as the one allowed fix, in a worktree (`exp/direct-surface`), then merged (`734b092`).
- `find_symbol` ranks callable symbols by BM25 over name, documentation and code.
- Offline (no provider calls): target in the top 5 for 110 of 120 instances.
- Mini-check on the calibration targets (`experiment.repoqa-direct-check.json`, 96 requests, 0.94M tokens): direct 48/48 pass, median 4.0 s, p90 6.0 s, 2.19 calls, 3.2k tokens per request; inline 48/48, 3.5 s, 5.0 s, 16.3k.
- Lesson: plain `execute` records request duration at 1 s resolution; use provider-reported model time for fine comparisons.
- Lesson: a `pgrep -f` waiter whose own command line contains the pattern never exits; wait on the job itself instead.

**v3 baseline.** Six configurations (v2 plus `local-mcp-direct`), same split and seeds; tag `seams-v3-freeze` (`5c09994`). 864 requests, started 10:48 UTC.

## 2026-10-15 — v3 selection, decisions and P3′ re-pilot

- v3 replay and selection (`studies/replay-v3calib/`, rules committed before the replays): S-E′ selected (L7000, inline +9 s, `v2-t10-ttl10`); S-F fails closed on probing cost; S-B′ selected with 15 % capture and made replay-only by decision; round-trip map replay-only. Details in the pre-registration.
- S-B′ low capture traced with `tools/seams/quota_attribution.py`: bursty quota stalls, and waits caused by inline's consumption fall on direct requests (attribution).
- S-E′ is the only live study (seeds 301–305); S-D is reported from P1 and the v1 counterfactual.
- P3′ (v3 re-pilot, 192 requests): GO on all gates. v2 delay-phase misses 5 against frozen's 14; recovery lag 2; 452k tokens against 774k. P3 on v2 (lean fallback) had 11 against 14 and recovery lag 9.
- `tools/seams/run_study.sh` added for detached, resumable collection (session jobs stop at 2 h).
