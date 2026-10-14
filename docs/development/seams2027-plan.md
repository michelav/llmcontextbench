# SEAMS 2027 plan: adaptive context provisioning, v2 studies

## Context

The v1 long64 RepoQA studies (`studies/repoqa-long64-{latency,budget,reliability}`) ran end to end but did not justify runtime adaptation:
- **Latency:** the fallback (MCP, about 6.7 s) could not meet the 6 s limit. The adaptive router reacted 13–30 requests late and recovered later still. It was worse than both frozen and inline.
- **Budget:** the policy stopped serving after its first request with unknown token usage (9% of requests served).
- **Reliability:** the circuit breaker never closed. The gain over frozen was modest.
- **Overall:** inline code dominates stationary RepoQA, so there is no runtime trade-off to exploit.

Code review found the causes:
- cooldown applied across size bins;
- per-bin estimators;
- round-robin probes;
- fail-closed budget handling;
- the reliability window is never reset;
- the budget forecast reads future requests;
- episode IDs collide across studies.

**Goal:** by 23 Oct 2026, deliver a SEAMS research paper with:
1. a characterization of *when* adaptation of context provisioning pays off;
2. live evidence from scenarios that meet those conditions, compared with fixed configurations, a frozen router and a phase-oracle upper bound;
3. adaptation cost and lag;
4. lessons from v1.

Everything stays in RepoQA, with the long64 dataset, `gpt-6-luna`, and the existing frozen baseline. Lattes is post-SEAMS work (see the end of this plan).

## Paper claims and research questions

- **RQ1. When does runtime adaptation pay off?** An opportunity map from provider-free replay, testing five conditions:
  - C1: the best configuration changes over time (non-stationarity);
  - C2: the change can't be predicted from request features;
  - C3: a feasible fallback exists;
  - C4: the disturbance lasts longer than the controller's detection lag;
  - C5: probing is cheap.
- **RQ2. When the conditions hold, does feedback-driven adaptation reduce SLO violations and cost?** Live paired episodes against fixed, frozen and phase-oracle arms.
- **RQ3. How fast does it react, and what does it cost?** Reaction and recovery lag, switches, probe cost, controller overhead.
- **RQ4. Which MAPE-K design choices matter?** v1 vs v2 controller, live; component ablations in replay.

Claims stay within: one task (Search Needle Function), one model, 16 held-out targets, controlled injected disturbances. v1 is reported as found.

**Headline candidate: lean-first cascade (within-request fallback).**

This comes from a provider-free counterfactual on the v1 fixed arms (`studies/repoqa-long64-budget`, 3 seeds × 96 requests):

| Arm | Pass | Tokens per request | Mean latency | p95 latency |
|---|---|---|---|---|
| mcp-lean | 91.0% | 8.0k | 7.0 s | 12.0 s |
| mcp-default | 99.0% | 13.7k | 6.8 s | 9.8 s |
| inline | 99.7% | 16.8k | 2.8 s | 4.0 s |
| **lean→default cascade** | **100%** | **≥8.8k** | 7.6 s | 18.2 s |

- The tokens are a lower bound: the failed lean attempts have only partial usage counts (`unavailable`, about 14.7k known on average).
- **Where lean fails:** 26 of 26 lean failures are step-limit errors (`max_steps=8`) on two functions (`rs_004`, `py_005`), at every context size.
- **Why only feedback can handle it:** the failure can't be predicted from the size bin, and calibration missed it (lean passed 97.9% there). It meets C2 and C3 without any injected disturbance.
- **Repository memory adds nothing here:** routing a repository straight to default after a failure gives the same 8.8k tokens per request.
- **Caveats:**
  - this is exploratory: it was found on held-out logs and depends on two targets, so report results per target;
  - inline remains far faster, so the claim is about cost and quality, not latency.

## Provenance constraint (drives the sequencing)

- **The v1 baseline pins the code it was measured with.** `verify()` (`src/ctxbench/studies/baseline.py:64`) is called by study `prepare`, `episode`, `status` and `analyze`. It refuses to run if any file in `measurement_sources()` (`baseline.py:23`) has changed. That list covers:
  - `adaptive/study_runner.py`;
  - `adapters/repoqa/*.py`;
  - `studies/baseline.py`;
  - `src/ctxbench/ai/**`;
  - `tools/repoqa/**`;
  - `pyproject.toml`, `uv.lock`.
- **The plan has to touch one of those files.** The cascade, fault and quota work changes `study_runner.py`. A **v2 baseline** is therefore required (S6a), with a **code freeze** on fingerprinted files once it is prepared. Changing them later means another baseline.
- **Keep new logic outside fingerprinted files where possible:** `adaptive/study_policy.py`, `studies/{models,study,replay}.py` and `tools/seams/`. Example: the pilot `targets` subset is passed from `studies/study.py` into the unchanged `ordered_workload`.
- **v1 was frozen against uncommitted code.** Its sources match the current uncommitted working tree (`src/ctxbench/adapters/repoqa/study.py`, `workload.py`, `studies/baseline.py`, `tools/repoqa/*` are all modified). Before any change, commit and tag that state (S0).

## Implementation slices

Every slice:
- runs `pytest -k "adaptive or study"` plus its focused tests;
- makes no provider calls;
- keeps v1 behaviour reproducible when the new options aren't set;
- leaves canonical `trials`/`responses`/`evals` schemas unchanged.

### S0: Preserve v1 provenance (Oct 15, first; about 1 h)

- **Commit and tag.** With your approval, commit the current working tree (v1 code, docs, study definitions, `tools/repoqa/select_long64_delay.py`, tests). Tag it `seams-v1-studies`. Large `studies/`, `baselines/` and `runs/` artifacts stay untracked unless you decide otherwise; record their hashes in the worklog instead.
- **Read-only analysis of old studies.** Add `--allow-source-drift` to `llmctxbench study analyze` and `study status` (`src/ctxbench/studies/study.py`, `src/ctxbench/commands/study.py`; neither file is fingerprinted).
  - It skips only the source-fingerprint check. Experiment, dataset and frozen-artifact hashes are still verified.
  - Reports produced this way include `sourceDrift: true`.
  - `prepare` and `episode` keep strict verification.
  - This lets the new analysis metrics be applied to v1.
- **Tests:** analyze with drift fails without the flag and succeeds, marked, with it; episode still refuses.
- **Docs:** add a "v1 provenance and source drift" note in `docs/studies.md`.
- **Commit:** `feat(study): allow read-only analysis under source drift`

### S1: Correctness fixes (Oct 15)

All in `src/ctxbench/adaptive/study_policy.py` unless noted.
- **F1 reliability circuit breaker.** In `_reliability` and `observe`: after a successful `recovery_probe`, clear `observed[(cid,'all')]` history for the decision window (or keep only observations after recovery) and close the circuit. Remove the duplicated unused `_rank` call at line 133.
- **F2 budget unknown usage.** New `BudgetPolicy.unknownUsage: "stop" | "bounded"` (default `stop`). With `bounded`:
  - charge `knownPartial` + (calibration p95 tokens for that configuration and bin − `knownPartial`, floored at 0);
  - mark the ledger `estimatedCharge`;
  - keep serving.
  
  The ledger exposes `knownTokens` and `estimatedTokens` separately.
- **F3 budget forecast.** New `BudgetPolicy.forecast: "lookahead" | "expected"` (default `lookahead`). With `expected`: remaining count × expected tokens per request, weighted by the calibration size-bin mix (stored in the plan at `prepare`).
- **F4 cooldown scope.** New `RouterPolicy.incumbentScope: "global" | "bin"` (default `global`). With `bin`: `current`/`last_switch` are kept per size bin, and cooldown and material improvement apply only within a bin.
- **F5 episode ID.** In `src/ctxbench/studies/study.py` `prepare`: the identity also hashes `policy` config, scenario effects, `latencyLimitMs`, `tokenBudget` and the definition digest. This only affects newly prepared studies. Analysis of the old directories still works because their prepared.json is sealed.
- **Tests:** `tests/test_study_protocol.py` and `tests/test_adaptive_policy.py`:
  - circuit closes after a successful probe and re-opens on a new failure;
  - bounded charging keeps serving, with provenance `estimated`;
  - the `expected` forecast doesn't touch future instances;
  - the per-bin incumbent lets large and small route differently without cooldown;
  - IDs differ when only `latencyLimitMs` differs.
- **Commit:** `fix(study): close reliability circuit, bounded budget charging, per-bin incumbent, unique episode ids`

### S2: Router options for detection and recovery (Oct 15–16)

`RouterPolicy` in `src/ctxbench/studies/models.py`; logic in `study_policy.py` `_estimate`, `_probe`, `_rank`. Policy version moves from 2 to 3, recorded in `resolved` of the plan.
- **`estimator: "per-bin-mean" | "pooled-ratio"`.** Pooled ratio = trailing mean of observed/calibrated latency (and tokens) per configuration across bins, over `updateWindow` successes. The estimate is calibration value × ratio. It needs `minimumObservations` (default 3).
- **`probeMode: "round-robin" | "targeted"` and `avoidedProbeInterval`.** Targeted mode probes the most recently abandoned configuration every `avoidedProbeInterval` requests while it is being avoided, and falls back to round-robin at `probeInterval` otherwise.
- **`estimateTtlRequests`.** Observations older than N requests are dropped. With none left, the estimate falls back to calibration (half-open state).
- **`latencyQuantile`** (for example 0.9). Routing compares the quantile estimate with `latencyLimitMs`. Calibration quantiles are added per configuration and bin in `prepare` from frozen `observations`. The runtime quantile is the pooled ratio × calibration quantile.
- **Defaults** reproduce v1 exactly.
- **Tests:**
  - pooled ratio detects a ×2 slowdown within ≤4 observations;
  - targeted probes hit the abandoned configuration;
  - TTL expiry restores calibration;
  - the quantile route excludes a configuration whose mean is within the limit but whose p90 is not;
  - **v1 regression:** re-drive the `Controller` with v1 `decisions.jsonl` observations from `studies/repoqa-long64-latency` and assert identical selections.
- **Commit:** `feat(study): pooled estimator, targeted probing, estimate ttl and quantile routing`

### S3: New policies and disturbance effects (Oct 16)

**Policies** (in `models.py` and `study_policy.py`):
- **`schedule` (phase oracle).** `phases: [{firstRequest, lastRequest, configurationBySize: {small, medium, large}}]`. It is given the phase schedule by design; reported only as an upper bound. Assignments are chosen from replay as the best fixed choice per phase and bin (S4).
- **`random-eligible`.** Seeded random choice; a sanity baseline.
- **`budget` with `mode: "pace"`.** For each request, choose the fastest qualified eligible configuration *c* such that spent + estimate(*c*) + cheapest expected forecast for the remaining requests ≤ budget. Uses the S1 `expected` forecast and `bounded` charging.

**Effects:** generalize `Delay` into a discriminated union `Effect`, with `kind` defaulting to `delay` for backward compatibility. Phases are derived from all effects.
- `delay` (existing `request`/`tool-call` scopes).
- `fault`: `configuration`, `toolErrorRate`, `seed`, request range. Implemented in a `FaultyRuntime` decorator next to `MeasuredToolDelay` in `src/ctxbench/adaptive/study_runner.py`, reusing `local_mcp_runtime_decorator`. It returns a tool error result (`isError`), not a transport exception, so the model sees the failure. Injected counts are recorded.
- `token-quota`: `tokensPerMinute`, request range; applies to every configuration.
  - The runner keeps `(monotonic_end, tokens)` for completed requests.
  - Before each execution inside the range, it sleeps until the trailing 60 s total is below the quota.
  - The wait goes into `durationMs` and is recorded as `quotaWaitMs`.
  - Known-partial tokens count toward the quota.
- **Workload shape** (optional, for budget pacing): study-level `workloadShape: {"phases": [{"until": 48, "sizeWeights": {...}}]}`. It is applied in `studies/study.py` as a seeded reordering of the `ordered_workload` output, leaving the fingerprinted adapter untouched. It only reorders the same 96 requests within a seed, so the request set stays the same.
- **Overhead (RQ3):** time `Controller.decide` and `observe` with `perf_counter`. Add `controllerMs` to the decision record (sidecar `schemaVersion` 3 → 4, additive).
- **Tests:** schedule decisions; pace never plans beyond the budget and serves all requests in a synthetic run; fault rate is deterministic under a seed; quota wait uses a fake clock and sleeper (as `run(..., monotonic=, sleeper=)` already allows); old definitions still validate.
- **Commit:** `feat(study): phase-oracle and pacing policies, fault and token-quota effects, controller overhead`

### S3b: Cascade policy with within-request fallback (Oct 16; must-have)

- **Policy definition.** New `CascadePolicy` in `src/ctxbench/studies/models.py`:
  - `type: "cascade"`;
  - `primary` (e.g. `local-mcp-lean`);
  - `fallbacks` (ordered; at most 1 for SEAMS, e.g. `local-mcp-default` or `inline-code-full`);
  - `triggerFailureClasses` (default `["step-limit", "tool-use"]`, from `classify_failures` in `study_runner.py`);
  - optional `primaryMaxSteps` (an early-abort variant; overrides the attempt's `max_steps` param read in `ai/strategies/local_mcp.py:26`);
  - optional `memory: "none" | "source"`, keyed by repository identity, never the target function. This is an ablation only.
- **Runner** (`src/ctxbench/adaptive/study_runner.py`):
  - A request may execute up to 2 attempts. Each attempt uses the already-planned trial for that configuration (`plan['requests'][instance]['trials'][cid]`), so trial IDs stay canonical and distinct.
  - The packet gets an `attempts` list, with per-attempt `executionStarted` for resume and uncertain-retry handling.
  - Both responses go into `responses.jsonl`.
  - The decision record (sidecar `schemaVersion` 4) adds `attempts[{configuration, status, durationMs, tokens, failures}]`, `fallbackReason` and `finalConfiguration`.
  - Request duration = the sum of attempt durations. Tokens = the sum; if any attempt is `unavailable`, the total is marked `estimated`, with the known lower bound kept separately.
- **Controller** (`study_policy.py`): `decide` returns the primary. A new `decide_fallback(index, failed_observation)` returns a fallback or `None`. `observe` records each attempt.
- **Analysis** (`studies/study.py`):
  - quality = the final attempt's evaluation;
  - cost and latency = all attempts summed;
  - new metrics: fallback rate, wasted tokens (failed attempts, lower bound), per-target breakdown.
- **Replay** (S4): add a `--counterfactual-fixed <study_dir>` mode that pairs fixed-arm logs by seed and request, reproducing the table in the headline section above. Mark it as held-out exploratory.
- **Tests:**
  - fallback only on trigger classes;
  - at most one fallback;
  - the final attempt determines quality;
  - token sums keep provenance;
  - resume works after a crash between attempts (fake execution);
  - the memory key is the repository, never the instance ID.
- **Commit:** `feat(study): cascade policy with bounded within-request fallback`

### S4: Replay simulator and opportunity sweep (Oct 16–17)

New `src/ctxbench/studies/replay.py`; CLI `llmctxbench study replay` in `src/ctxbench/commands/study.py`.
- **Inputs:**
  - `--prepared` (any prepared study; provides plan, estimates and workload sizes);
  - `--pool` (default: the frozen baseline `observations` for the calibration targets);
  - `--grid` JSON (effect parameters × policies × seeds);
  - `--replicates`.
- **Observation pool:**
  - per configuration and size bin: `durationMs`, `tokens`, `status`, `failures`;
  - `toolCalls`/`steps`, joined by `trialId` from baseline episode `responses.jsonl` (`metricsSummary`).
- **Simulation:**
  - for each synthetic episode, draw the chosen configuration's observation from the bin pool with a seeded RNG;
  - apply effects analytically: request delay; tool-call delay × `toolCalls`; fault (Bernoulli per call → error, `tool-use` class); quota on a simulated clock;
  - feed the real `Controller.decide`/`observe`, so the same code runs in replay and live.
- **Metrics per policy and grid point** (same definitions as `analyze`): misses, tokens, failures, unserved, switches, probes, reaction and recovery lag.
- **Derived:**
  - `opportunity` = best fixed − phase oracle;
  - `capture` = (best fixed − adaptive) / opportunity;
  - frozen-vs-adaptive gap.
- **Output:** `replay.json` and heatmap SVGs (x = disturbance magnitude, y = disturbance duration in requests, colour = capture / miss reduction), with axes and labels.
- **Leakage guard:** default pool = calibration targets only. A `--pool episodes:<study_dir>` option is available for debugging, and its output is marked `heldOutDebug: true`.
- **Tests:**
  - deterministic under a seed;
  - with no effects, fixed arms reproduce pool means;
  - the v1 latency parameters reproduce the v1 qualitative result (adaptive v1 ≤ frozen);
  - an S-A-like grid point shows opportunity > 0.
- **Commit:** `feat(study): provider-free replay simulator and opportunity sweep`

### S5: Analysis and figures (Oct 17, finalized Oct 19)

In `src/ctxbench/studies/study.py` `analyze` and `_timeline_plots`; additive to `analysis.json` (`schemaVersion` 3 → 4).
- **Metrics:**
  - all-request pass rate, alongside the existing pass rate over evaluated requests;
  - per-phase summaries;
  - target-cluster bootstrap intervals (language-stratified, reusing the existing bootstrap) for deadline misses, tokens, failures and pass, as well as latency;
  - regret against `schedule`;
  - reaction lag (requests from phase onset to the first non-probe switch away from the degraded configuration) and recovery lag;
  - switches, probe count and probe cost (tokens and misses caused by probes);
  - controller overhead (p50/p95 `controllerMs`).
- **Plots (SVG, with ticks and labels):**
  1. Timeline: X = request position, Y = latency in seconds, with limit line, phase bands, and a strip showing each arm's chosen configuration.
  2. Pareto: X = tokens per request, Y = miss rate, with interval bars per arm and scenario.
  3. Phase bars.
- **Paper scripts:** `tools/seams/make_figures.py` and `make_tables.py` read `analysis.json` and `replay.json` and write PDF/SVG figures and LaTeX tables into `paper/`. The paper location is to be decided; default `docs/seams2027/`.
- **Tests:** extend `tests/test_adaptation_analysis.py` with a synthetic two-arm study (intervals, lag computation, all-request pass counts unserved requests as failures).
- **Commit:** `feat(study): per-phase metrics, cluster CIs, lag/regret and labelled plots`

### S6: Pre-registration, scenario selection and definitions (Oct 17)

- **Sweep.** Run `study replay` on the calibration pool across:
  - S-A (MCP tool-call delay): delay 500–3000 ms/call; limit 8–12 s; duration 12–36 requests;
  - S-B (opposing forces): MCP delay phase followed by token-quota phase; quota 150k–400k TPM;
  - budget pacing: cap 0.8–1.3M; workload shape;
  - S-C (transport, MCP vs function, fault rate 0.2–0.6).
  
  Arms: inline, mcp-default, frozen, adaptive-v1, adaptive-v2, schedule.
- **Selection rule (written down before any live run):** for live runs, select the grid points with the highest capture among those with opportunity ≥ 15% miss-rate reduction. Also keep one stationary control and one low-opportunity point, which is reported as a negative case.
- **Write `docs/development/seams2027-preregistration.md`:**
  - hypotheses H1–H4 mapped to RQ1–RQ4;
  - the chosen parameters and the replay evidence for them;
  - arms, seeds (301–303, new), metrics and primary contrast (adaptive-v2 vs frozen on miss rate in the disturbed phase);
  - secondary contrasts;
  - a stopping rule: no parameter changes after live collection begins.
- **Definitions in `examples/studies/`:**
  - `study.seams-stationary.json`: pair `inline-code-full` + `local-mcp-default`; arms inline, mcp-default, frozen, adaptive-v1, adaptive-v2; scenario `stationary`.
  - `study.seams-disturbed.json`: same pair; arms plus `schedule`; scenarios `mcp-degraded` (S-A) and `opposing` (S-B; four 24-request phases: normal, MCP degraded, quota, normal).
  - Optional: `study.seams-transport.json` (S-C), `study.seams-budget.json` (pacing).
- Regenerate `schemas/studies/study.schema.json`.
- **Commit:** `docs(seams): pre-register v2 scenarios and add study definitions`

### S6a: Code freeze and v2 baseline (Oct 17; cost approval gate)

- **Code freeze.** All changes to fingerprinted files (mainly `adaptive/study_runner.py`) must be merged and tested first. Commit and tag `seams-v2-freeze`.
- **Baseline definition and inputs.** Use the unchanged `examples/studies/baseline.repoqa-long64.json`: seeds 101–103, 2 repeats, split seed 42, so the calibration targets are the same. Also unchanged: `experiment.repoqa-long64.json` (it already contains all 5 configurations, including the function arms) and the dataset.
- **Prepare** (provider-free):
  ```bash
  llmctxbench study baseline prepare --definition examples/studies/baseline.repoqa-long64.json --output baselines/repoqa-long64-v2
  ```
- **Execute, evaluate, freeze:** about 720 requests, about 7.5M tokens (the v1 baseline's known total), about 1–1.5 h.
  ```bash
  llmctxbench study baseline execute --prepared baselines/repoqa-long64-v2/prepared.json
  for r in baselines/repoqa-long64-v2/episodes/*/responses.jsonl; do llmctxbench eval "$r"; done
  llmctxbench study baseline freeze --prepared baselines/repoqa-long64-v2/prepared.json
  ```
- **Wiring.** All v2, pilot and replay definitions reference `../../baselines/repoqa-long64-v2/frozen.json`. Compare the v1 and v2 calibration estimates (latency, tokens, pass per configuration and bin) in the worklog; this documents drift.
- **After this point,** any fingerprinted change requires a new baseline. Bug fixes go to non-fingerprinted modules or wait for after the paper.

### S6b: Validation pilots (Oct 17–18, before S7; each has go/no-go criteria)

**Pilot support (small code change).**
- Add optional `targets: list[str]` to `Study` (`src/ctxbench/studies/models.py`). It must be a subset of the baseline `split.heldOut`.
- `prepare` (`src/ctxbench/studies/study.py`) passes the subset as the `targets` argument to the unchanged `ordered_workload` (`src/ctxbench/adapters/repoqa/study.py:87`, which is fingerprinted). That function already builds balanced six-size blocks, so any target subset keeps the size mix.
- Effect ranges are validated against the shorter workload. Under F5, the subset is part of the episode ID.
- Test: a 4-target subset gives 24 requests, balanced by size.

**Pilot rules.**
- Seeds 901+, never reused or pooled into final results.
- Output in `studies/pilot-*`; reported as pilots in the paper or the artifact.
- No parameter change after a pilot passes. If a pilot fails: at most one fix and re-pilot, then drop the scenario.

| Pilot | Workload | Arms | Requests (≈ tokens) | Go criteria |
|---|---|---|---|---|
| P0 provider-free | replay + tests | all | 0 | default options reproduce v1 decisions; counterfactual cascade reproduces 100% / ≥8.8k; replay sweep shows opportunity > 0 for S-A and S-B points |
| P1 cascade | 4 targets: `rs_004`, `py_005` (known lean failures) + `java_002`, `ts_001` = 24 requests | mcp-lean, mcp-default, cascade-mcp, function-lean | 96 (~1M) | cascade has 0 final failures; tokens ≤ 0.8× default; fallbacks only on trigger classes; two attempts logged with provenance; kill-and-`--resume` between attempts works; function-lean fails on the same targets (surface, not transport) |
| P2 MCP degradation (S-A) | 8 targets (2 per language) = 48 requests; tool-call delay on MCP for requests 17–32 | mcp-default, frozen, adaptive-v1, adaptive-v2 | 192 (~2.5M) | adaptive-v2 switches ≤5 requests after onset and returns ≤8 after recovery; misses in the degraded phase ≤50% of frozen; stationary phases: tokens within 10% of frozen |
| P3 opposing forces (S-B) | the same 48 requests; phases 1–12 normal, 13–24 MCP delay, 25–36 token quota, 37–48 normal | inline, frozen, adaptive-v2 | 144 (~2M) | `quotaWaitMs` and delays recorded; adaptive-v2 switches in both directions; fewer misses than frozen and fewer tokens than inline over the episode |
| P4 fixed policies (optional) | 24 requests | reliability v2, budget `pace` with the cap scaled to 24 requests | 48 (~0.5M) | the circuit closes after a clean probe; pace serves all requests within the cap; bounded charging marked `estimated` |

- **Totals:** about 480 live requests, roughly 6M tokens, about 1 hour.
- Each pilot is followed by `llmctxbench eval`, `study analyze`, and a check of the timeline plot and decision logs.
- **Gate:** only scenarios that pass their pilot go to S7.
- **Pilot definitions:** `examples/studies/pilot.{cascade,degradation,opposing,policies}.json`.

### S7: Live collection (Oct 18; cost approval gate)

- `llmctxbench study prepare` for each definition into fresh `studies/seams-*` directories (provider-free); then `status`.
- **Only scenarios that passed their S6b pilot are collected.** The pilots replace a separate smoke run.
- **Cascade study (S-D; first priority).** `examples/studies/study.seams-cascade.json`, seeds 301–303, scenario `stationary`, latency limit 15 s (needed by the routers only). Arms:
  - fixed: `inline-code-full`, `local-mcp-default`, `local-mcp-lean`, `local-function-default`, `local-function-lean`;
  - cascades: `cascade-mcp` (lean→default), `cascade-mcp-inline` (lean→inline), `cascade-fn` (function lean→function default).
  
  That is 8 arms × 3 seeds = 24 episodes, about 2.4k requests and roughly 25M tokens. The function arms give:
  - a 2×2 of surface (lean/default) × transport (MCP/function), showing whether lean failures come from the surface or the transport (calibration: function-lean also failed 2/144);
  - a cascade that doesn't depend on MCP.
- **Cost estimate, then explicit approval:**

  | Study | Episodes | Requests |
  |---|---|---|
  | Cascade S-D (8 arms × 3 seeds) | 24 | 2,304 |
  | Stationary (5 arms × 3 seeds) | 15 | 1,440 |
  | Disturbed (6 arms × 2 scenarios × 3 seeds) | 36 | 3,456 |
  | **Total** | **75** | **7,200** |

  That is roughly 85–95M answer tokens and about 10–12 hours run sequentially. Run order: S-D first, then stationary, then disturbed. If time or budget is short, cut the disturbed scenarios that were weakest in their pilots.
- **Run order:** the existing seed-major loop from `docs/studies.md` with `--resume`. Shuffle arm order within each seed to reduce drift bias, and record wall-clock start and end per episode.
- Evaluate (`llmctxbench eval`), then `study analyze`.
- **Optional, if time and budget allow:** S-C and budget pacing (about 12–24 episodes each).

### S8: Paper package and artifact (Oct 19–22)

- **Figures:**
  1. MAPE-K architecture (controller around the existing executor; knowledge = frozen baseline + rolling state);
  2. replay opportunity heatmaps;
  3. live timelines for S-A and S-B;
  4. Pareto plot;
  5. v1 vs v2 lag comparison.
- **Tables:**
  1. scenarios and parameters;
  2. results per arm and scenario with intervals;
  3. overhead and lag;
  4. replay ablation (estimator / probing / incumbent scope / quantile, one at a time).
- **Artifact:** `docs/seams2027/ARTIFACT.md` with exact commands. Also:
  - hashes of the frozen baseline, prepared studies and dataset;
  - code revision;
  - an anonymized archive of definitions, prepared files, `analysis.json`, `replay.json`, decision logs and figure scripts. Large traces can be excluded or sampled.
- **Docs:** update `docs/studies.md` (new options, effects, replay command) and add a "v2 protocol" section to `docs/development/repoqa-adaptation-prototype.md`. Log the milestones in `docs/development/worklog.md`.
- **Paper outline:**
  1. Introduction
  2. Background (strategies; prior SBES findings)
  3. Approach (MAPE-K controller, configuration catalogue, monitors and estimators, probing)
  4. Study design (opportunity conditions, replay, scenarios, arms, metrics, metric provenance)
  5. Results RQ1–RQ4
  6. Lessons from v1
  7. Threats to validity
  8. Related work (self-adaptive LLM systems, model routing, circuit breakers)
  9. Conclusion
  
  Check the SEAMS CFP for page limit and double-blind rules.

### S9: Study configurations and guiding docs (alongside each slice; final pass Oct 19)

Use the `update-docs` skill. Docs describe the actual CLI with exact commands, and v1 material is kept but labelled historical.

**Configurations: unchanged (bound by hashes).**
- `experiment.repoqa-long64.json`;
- `examples/studies/baseline.repoqa-long64.json`;
- the dataset;
- the v1 study definitions (`examples/studies/study.long64-*.json`, `studies/definitions/*`);
- older `study.{budget,latency,reliability}.json`.

**Configurations: new.**
- `examples/studies/study.seams-cascade.json` (S-D), `study.seams-stationary.json`, `study.seams-disturbed.json` (S-A and S-B);
- optional `study.seams-transport.json` (S-C) and `study.seams-budget.json` (pacing);
- pilots `examples/studies/pilot.{cascade,degradation,opposing,policies}.json`;
- replay grids `examples/studies/replay/{degradation,opposing,budget,transport}.grid.json`;
- generated definitions (if a parameter selector is used) in `studies/definitions/seams-*.json`, with a `.selection.json` record, written by `tools/seams/select_effects.py`. It lives in `tools/seams/`, not `tools/repoqa/`, so it isn't fingerprinted.

**Schema.** Regenerate `schemas/studies/study.schema.json` from `Study.model_json_schema()`, and add a test asserting the checked-in schema matches the model.

**Docs.**
- `docs/studies.md` (main guide):
  - new "SEAMS v2 suite" section: v2 baseline commands, pilot workflow and go/no-go, full-collection loop, cost table;
  - option reference: router options, `cascade`, `schedule`, `random-eligible`, budget `pace` / `unknownUsage` / `forecast`, effects `fault` / `token-quota`, `targets`, `workloadShape`;
  - `study replay` usage;
  - v1→v2 behaviour changes (F1–F5) and the source-drift flag.
  
  The current long64 section moves under "v1 long64 suite (historical)".
- `README.md` (study section around lines 505–527): point to the v2 suite as current; keep v1 and earlier adaptation links as historical.
- `docs/repoqa.md` (around lines 120–135): which configurations the v2 definitions select (now including the function arms); document the observed lean step-limit concentration as surface behaviour.
- `docs/development/repoqa-adaptation-prototype.md`: add a "v2 protocol (policy version 3)" section with the contracts for estimators, probing, cascade attempts, effects, decision sidecar schema v4 and analysis schema v4.
- `docs/development/repoqa-lean-surface-plan.md`: status note on the held-out lean failure finding and its use in the cascade.
- New:
  - `docs/development/seams2027-plan.md` (this plan, copied on approval);
  - `docs/development/seams2027-preregistration.md` (S6);
  - `docs/seams2027/ARTIFACT.md` (S8).
- `docs/development/worklog.md`: milestones S0, code freeze, v2 baseline, pilots, collection, with commands and hashes.

**Per-slice rule:** each code slice updates the matching `docs/studies.md` option reference in the same commit.

**Validation:** the commands in docs are run provider-free where possible (`prepare`, `status`, `replay`, `analyze`); `pytest -k cli` passes.

**Commit:** `docs(study): document SEAMS v2 suite, options, pilots and replay`

## Timeline and cut lines

| Date | Work |
|---|---|
| Oct 15 | S0 (commit/tag v1, source-drift flag), S1, start S2. Author starts drafting intro, background and approach. |
| Oct 16 | S2, S3, S3b (cascade); docs updated per slice |
| Oct 17 | Morning: S4 replay, S5 core, pilot support → code freeze. Midday: S6a v2 baseline (about 1.5 h). Afternoon: P0 + S6 sweep and pre-registration on v2 calibration. |
| Oct 18 | Pilots P1–P3 (about 1 h) → go/no-go → approval → S7 live run (overnight, about 10–12 h) |
| Oct 19 | Analysis, figures, S9 final docs pass; optional extra studies |
| Oct 20–22 | Writing, internal review, artifact |
| Oct 23 | Submit |

- **Must (prerequisite):** S0, S6a v2 baseline.
- **Must (highest):** S3b cascade policy and the live S-D cascade study.
- **Must:** F4, F5; S2 pooled estimator + targeted probing + quantile routing; `schedule` policy; `token-quota` effect; S4 replay; S5 intervals and plots; live S-A and S-B.
- **Should:** F1–F3, pacing (replay-only results acceptable), `fault` effect, controller overhead.
- **Could:** live S-C transport pair, live budget pacing, live reliability v2.

**Fallback if the live results don't confirm replay:** report the opportunity map and v1/v2 lessons as the main contribution (RQ1, RQ4), with live results as they are.

## Risks

- **Provider latency drift** (mcp-default averaged 6.7 s in one run and 8.4 s in another). Mitigations: quantile routing, shuffled arm order, recorded timestamps, the drift reported as an observed threat.
- **Quota realism.** Sequential single-tenant runs; the quota is a simulated harness limit, labelled as such.
- **Same 16 held-out targets as v1.** Disclose the reuse; new seeds; parameters chosen on calibration data only.
- **Small samples.** Emphasize effect sizes and intervals; no significance claims beyond the intervals.
- **A fingerprinted change after the freeze forces another baseline** (about 1.5 h, about 7.5M tokens). Mitigation: put logic in non-fingerprinted modules, freeze early on Oct 17, and run the full test suite before freezing.
- **v2 calibration may differ from v1** (provider drift). Report both, and use v2 for all v2 decisions.

## Critical files

- `src/ctxbench/adaptive/study_policy.py`: `Controller` (all policy logic).
- `src/ctxbench/studies/models.py`: definition schema; regenerate `schemas/studies/study.schema.json`.
- `src/ctxbench/studies/study.py`: `prepare`, `analyze`, `_timeline_plots`.
- `src/ctxbench/adaptive/study_runner.py`: effect injection (`MeasuredToolDelay`, `local_mcp_runtime_decorator`), decision record.
- `src/ctxbench/adapters/repoqa/study.py`: `ordered_workload`, `digest`.
- `src/ctxbench/commands/study.py`: `replay` subcommand.
- New: `src/ctxbench/studies/replay.py`, `tools/seams/*.py`, `examples/studies/study.seams-*.json`, `examples/studies/pilot.*.json`, `examples/studies/replay/*.grid.json`, `docs/development/seams2027-{plan,preregistration}.md`, `docs/seams2027/ARTIFACT.md`.
- Docs: `docs/studies.md`, `README.md`, `docs/repoqa.md`, `docs/development/repoqa-adaptation-prototype.md`, `docs/development/repoqa-lean-surface-plan.md`, `docs/development/worklog.md`.
- Fingerprinted files (changes allowed only before the S6a freeze): `src/ctxbench/adaptive/study_runner.py` (cascade attempts, fault and quota effects, `controllerMs`).
- Tests: `tests/test_adaptive_policy.py`, `tests/test_study_protocol.py`, `tests/test_adaptation_analysis.py`, `tests/test_repoqa_study.py`, new `tests/test_study_replay.py`.

## Verification

- Per slice: `pytest -k "adaptive or study"` plus the new focused tests; the full `pytest` suite before S7.
- v1 regression: default options reproduce v1 `decisions.jsonl` selections, and v1 `study analyze` still runs on the existing `studies/` directories.
- Replay sanity: v1 latency parameters give the v1 qualitative outcome; the selected v2 points show opportunity > 0 and capture > 0.
- Before collection: provider-free `prepare` and `status`, then exactly one live smoke episode per scenario, then explicit cost approval.
- After collection: `study status` shows the matrix is complete; `llmctxbench eval` covers every response; `analysis.json` intervals and figure scripts regenerate deterministically.

## Optional: 128k pilot (decide on Oct 16; not on the critical path)

- **What exists.** All 8 long64 source repositories have roughly 300k–1.2M tokens of content (approximate), so 131072-token contexts are buildable with the same 20 needles.
- **Builder changes.**
  - Add a `long128` profile in `tools/repoqa/build_repoqa_dataset.py`: sizes long64 + 131072, a new version string, and a ≥95% budget check on the top size.
  - Add `SIZE_PROFILES['long128']` in `src/ctxbench/adapters/repoqa/study.py`.
  - Add an `xlarge` bin in `adaptive/types.py` (`SizeBin`) and `studies/baseline.py:243`.
- **Pilot only.** Run inline, mcp-default and mcp-lean on 128k for 8–16 needles with 1 repeat, through the plain `llmctxbench execute`/`eval` path. No new baseline.
- **Decision rule.**
  - Promote to a full long128 baseline (about 840 calibration requests) only if inline pass rate drops or latency rises materially at 128k.
  - Otherwise, use the pilot only to justify realistic `token-quota` numbers for S-B.

## Post-SEAMS: Lattes (thesis)

- **Why it's attractive:** real quality and cost trade-offs (inline 45.8% vs 35% tools; about 70k vs 10k tokens), a real remote MCP endpoint, freshness scenarios, 28 tagged tasks.
- **Why it's out of scope now:**
  - the study engine is RepoQA-coupled (`studies/baseline.py` imports `RepoQADatasetAdapter`, the language/target split and size bins);
  - quality is judged by LLMs offline, so it isn't observable at runtime;
  - only 5 curricula, so only 5 independent clusters;
  - judge cost.
- **Route:**
  1. Domain-neutral baseline and study hooks (split, features, evaluator) in the dataset adapter.
  2. Features derived from the question, not from task tags.
  3. Remote-MCP degradation, quality-aware budget pacing and freshness scenarios.
  4. More curricula.
