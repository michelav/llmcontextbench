# Reusable RepoQA baselines and adaptation studies

Definitions live in `examples/studies/`; generated JSON Schemas live in
`schemas/studies/`. The experiment owns dataset, model, configurations, operation
surfaces and evaluation. `baseline.json` adds a language-stratified target split,
integer workload seeds, repetitions and context budget. `study.json` references a
frozen baseline and supplies policies, held-out seeds, repetitions, scenarios and
comparison pairs. Paths are relative to the declaring definition.

## Long64 study suite

The current long64 suite uses `experiment.repoqa-long64.json`, dataset version
`2026-10-13-long64.1`, answer model `gpt-6-luna`, and five configurations:
`inline-code-full`, default and lean local MCP, and default and lean local
function. The three current long64 study definitions explicitly select the
inline and MCP configurations; the function arms are calibrated in the baseline
but are outside those study comparisons. The older
`baseline.repoqa-five.json`, `study.budget.json`, `study.latency.json`, and
`study.reliability.json` remain examples for the earlier dataset. Do not mix
their frozen baseline with the long64 definitions.

The long64 split reserves one of five targets per language for calibration.
That is 24 calibration requests and 96 held-out requests per episode, with the
same six nominal sizes for each target. The baseline definition requests three
seeds, two repeats, and five configurations: 30 calibration episodes, or 720
provider-backed requests before evaluation. Prepare and inspect it without
calling a provider:

```bash
llmctxbench study baseline prepare \
  --definition examples/studies/baseline.repoqa-long64.json \
  --output baselines/repoqa-long64
jq '{dataset: .payload.manifest.dataset, split: .payload.split,
     configurations: .payload.configurations, episodeCount: (.payload.episodes | length),
     requestsPerEpisode: (.payload.episodes[0].workload | length)}' \
  baselines/repoqa-long64/prepared.json
```

`prepare` requires a fresh output directory and binds the exact experiment,
dataset and measurement-source hashes. The earlier run in
`outputs/repoqa-gpt3-v3` is pilot evidence; it is not a reusable frozen baseline
under this protocol. The five-arm experiment uses a new ID so its trial IDs do
not overlap that three-arm pilot. After reviewing the prepared matrix and
collection cost,
run the provider-backed calibration, evaluate each episode with the deterministic
RepoQA scorer, then freeze:

```bash
llmctxbench study baseline execute --prepared baselines/repoqa-long64/prepared.json
for responses in baselines/repoqa-long64/episodes/*/responses.jsonl; do
  llmctxbench eval "$responses"
done
llmctxbench study baseline freeze --prepared baselines/repoqa-long64/prepared.json
```

The generated matrix is configuration × seed × repeat. Each episode executes its
whole calibration workload once. Freeze requires terminal execution records and
evaluation records for every request. Failed responses remain in observations;
a successful response requires an evaluated result, while a failed response may
have a skipped evaluation. The immutable `frozen.json` contains raw artifact
hashes, per-request observations and all-sample estimates. Latency means use
successful requests; failure counts, usage coverage and known token totals are
separate. Evaluation usage is never counted as execution usage. The freeze is
bound to its experiment and source files: changing those inputs requires a new
baseline, not editing or resealing the frozen artifact.

Prepare each held-out study after freezing. First derive the inline degradation
from the frozen baseline. The checked-in latency definition contains a
provisional 5,000 ms treatment for schema validation; use the generated
definition for a held-out run. The selector verifies the frozen baseline and
writes a separate record of the calculation and baseline hash:

```bash
python tools/repoqa/select_long64_delay.py \
  --definition examples/studies/study.long64-latency.json \
  --output studies/definitions/study.long64-latency.json
cat studies/definitions/study.long64-latency.selection.json
```

For each size bin, the selector takes the mean successful inline latency and
the fastest selected MCP mean from the frozen calibration. It finds the delay
that puts inline at least 1,000 ms beyond both the 6-second study limit and
that alternative, then rounds the maximum required delay across bins up to a
whole second. This matches the mean-latency estimates used by the router. If
the alternative itself exceeds 6 seconds, the disturbance can still test
routing response but cannot establish that routing meets the limit. Review the
recorded per-bin evidence before collection. The pilot implies 5,000 ms by
this rule; the frozen calibration may select a different value.

The following preparation commands are provider-free and each output
directory must be fresh:

```bash
llmctxbench study prepare --definition examples/studies/study.long64-budget.json --output studies/repoqa-long64-budget
llmctxbench study prepare --definition studies/definitions/study.long64-latency.json --output studies/repoqa-long64-latency
llmctxbench study prepare --definition examples/studies/study.long64-reliability.json --output studies/repoqa-long64-reliability
llmctxbench study status studies/repoqa-long64-latency
jq '.payload.episodes | map({policyName, scenarioName, seed, repeat})' studies/repoqa-long64-latency/prepared.json
```

The budget study has four policies × three seeds = 12 episodes. The latency
study has three policies × two scenarios × three seeds = 18 episodes. The
reliability study has four policies × three seeds = 12 episodes. Each episode
plans 96 requests, though the budget policy can leave requests unserved. Review
the entire matrix before executing it. A complete collection can attempt up to
4,032 held-out requests in addition to the 720 calibration requests. Run one
episode explicitly to check the setup:

```bash
llmctxbench study episode --prepared studies/repoqa-long64-latency/prepared.json \
  --policy adaptive --scenario inline-delay --seed 201 --repeat 1
llmctxbench study status studies/repoqa-long64-latency
```

After reviewing the paid collection budget, run the remaining prepared episodes.
This Bash loop reads the sealed episode matrix, so policy names and disturbance
schedules come from the prepared definitions. `--resume` also accepts the single
episode already run above, without repeating completed requests:

```bash
for study_dir in studies/repoqa-long64-{budget,latency,reliability}; do
  while IFS=$'\t' read -r policy scenario seed repeat; do
    llmctxbench study episode --prepared "$study_dir/prepared.json" \
      --policy "$policy" --scenario "$scenario" --seed "$seed" --repeat "$repeat" --resume
  done < <(jq -r '.payload.episodes[] |
    [.policyName, .scenarioName, (.seed | tostring), (.repeat | tostring)] | @tsv' \
    "$study_dir/prepared.json")
done
```

For completed episodes, evaluate responses before interpreting pass rates, then
run provider-free analysis for each study:

```bash
for study_dir in studies/repoqa-long64-{budget,latency,reliability}; do
  for responses in "$study_dir"/episodes/*/responses.jsonl; do
    llmctxbench eval "$responses"
  done
  llmctxbench study status "$study_dir"
  llmctxbench study analyze "$study_dir"
done
```

The latency definition uses a 6-second limit and adds the selected delay to
inline requests 31–60 in its `inline-delay` scenario. That degradation is included
inside measured request time and is shared across policies at the same workload
positions. The stationary scenario has no injection. The budget definition
uses a 1,000,000-token episode cap and a 75% calibration pass floor. The
reliability definition uses a 15-second routing limit so lean MCP can be chosen
for larger bins; it monitors observed `step-limit` failures over ten selected
requests, with at least five observations and a 10% trigger. These are pilot-
informed exploratory settings, not validated optimal thresholds. The pilot had
nine lean MCP and one default MCP step-limit errors, clustered on two targets.
For the pilot's 96 instances outside this split's calibration targets, total
generation tokens were about 0.81M lean, 1.23M default, and 1.61M inline;
the budget sits between those observed totals. Future totals can differ, and
the calibration split can miss those targets. Inspect the frozen quality and
estimates before accepting these settings for a formal collection.

`study prepare` verifies the baseline digest and every frozen raw artifact. It
persists exact held-out workloads, estimates, definitions, resolved defaults and
the policy × scenario × seed × repeat matrix. The same frozen baseline can initialize
separate latency, budget and reliability studies. Identical seeds and repeats receive
identical workloads and disturbance schedules across arms; each arm has its own
controller state. Study and baseline episode directories contain standard
`manifest.json`, `trials.jsonl`, `responses.jsonl` and traces so the regular
`llmctxbench eval`, `export` and `metrics` commands can operate on each constituent
execution. The study commands do not evaluate automatically.

Router defaults are a five-request switch cooldown, 10% material improvement,
five-observation rolling updates and probes every ten requests, rotating among
eligible alternatives. Candidate declaration order breaks ties. Study values for
budgets, latency limits, delays, quality floors and reliability thresholds are
explicit scientific choices; the example numbers are illustrative and require
pilot justification before held-out collection. A budget is per episode. Forecasts
are estimates and can overshoot; unknown usage stops further budget-dependent
requests. The ledger records known consumption, uncertainty and overshoot. The
optional quality floor uses calibration pass rates only. Reliability monitors the
chosen execution failure classes over its declared window; wrong answers remain
offline evaluation outcomes. It changes future routing only, with no same-request
fallback. Operation errors can coexist with a successful final answer and do not
imply transport failure.

Request delays apply to the chosen configuration inside measured execution time,
including inline. Tool-call delays require local MCP and apply once per call.
Analysis reports planned and completed coverage, unserved requests, failures,
latency, deadline misses, token and evaluation coverage, probes, paired target
cluster comparisons and derived latency timelines. Targets and frozen baselines are
shared across arms and seeds, so they are not independent replications. Incomplete
matrices remain visible in the report.

Episode requests are sealed before execution. Resume replays completed packets and
refuses an uncertain provider attempt unless `--retry-uncertain` is explicit.
Such a retry may duplicate a charged call, so its prior consumption remains unknown.
A budget policy stops further service after that uncertainty. Prepared/frozen
artifacts bind experiment, dataset and measurement source fingerprints; changing
those inputs requires a fresh compatible baseline. Historical adaptation commands
and runs remain readable under their legacy protocol. The older
`repoqa-lean-surface-plan.md` restriction excluding local functions from adaptation
is superseded for this V3 study protocol. Corrected MCP error flags require fresh
measurements; old traces are not rewritten.

No command in this guide should be run against a paid provider without a separately
approved collection budget. `prepare`, `freeze`, `status` and `analyze` are provider
free. The sample definitions do not establish a token, latency or reliability
benefit; compare individual policies with fixed configurations before considering
combined policies.

## Re-analysing studies after code changes

`prepare`, `episode`, `status` and `analyze` verify the measurement-source
fingerprint recorded in the frozen baseline. After a change to any listed source
(for example `src/ctxbench/adaptive/study_runner.py`), existing studies can still
be inspected read-only:

```bash
llmctxbench study status studies/repoqa-long64-latency --allow-source-drift
llmctxbench study analyze studies/repoqa-long64-latency --allow-source-drift
```

The flag skips only the source comparison; experiment, dataset and frozen
artifact hashes are still checked, and the report lists the changed sources under
`sourceDrift`. `prepare` and `episode` always require matching sources, so new
collection needs a compatible baseline. The v1 long64 baseline and studies were
measured at the tag `seams-v1-studies`; check it out to reproduce them exactly.

Paired bootstrap intervals iterate requests and target clusters in sorted order,
so `analyze` output is deterministic for a given seed. Analyses written before
this fix depended on Python hash randomisation; their mean differences are
unchanged but their intervals can differ slightly when regenerated.

## Policy options added for the v2 suite

Each option defaults to the v1 behaviour, so v1 definitions and sealed plans
replay unchanged (`tests/test_study_v1_regression.py`). New definitions should
set them explicitly.

| Policy | Option | Values (default first) | Effect |
|---|---|---|---|
| `router`, `reliability` | `incumbentScope` | `global`, `bin` | `bin` keeps the incumbent, cooldown and material-improvement test per size bin, so routing small and large requests differently is not blocked by cooldown. |
| `reliability` | `resetOnRecovery` | `false`, `true` | `true` closes the circuit after a clean recovery probe: failure rates are judged only from that probe onward. With `false`, old failures stay in the window and the configuration is re-excluded immediately. |
| `budget` | `unknownUsage` | `stop`, `bounded` | `bounded` keeps serving after a request with unknown usage. It charges the known partial count plus an estimated remainder up to the calibration p95 for that configuration and bin; the ledger reports `estimatedTokens` (provenance `estimated`) and `estimatedOvershoot` separately from `knownTokens`. |
| `router` | `estimator` | `per-bin-mean`, `pooled-ratio` | `pooled-ratio` tracks one observed/calibrated ratio per configuration across all size bins (trailing `updateWindow` successes) and scales each bin's calibration estimate by it, so a slowdown seen in any bin updates every bin. |
| `router` | `minimumObservations` | `3` | Runtime samples required before a runtime estimate replaces calibration (must not exceed `updateWindow`). |
| `router` | `estimateTtlRequests` | unset, positive integer | Observations older than this many requests are ignored; an avoided configuration falls back to its calibration estimate. |
| `router` | `probeMode`, `avoidedProbeInterval` | `round-robin`, `targeted` | `targeted` probes the configuration most recently switched away from every `avoidedProbeInterval` requests while it is avoided, then falls back to the round-robin `probeInterval` schedule. |
| `router` | `latencyQuantile` | unset, `0.5`, `0.75`, `0.9`, `0.95` | Routes on the calibration latency quantile (scaled by the current/calibrated mean ratio) instead of the mean, matching the per-request deadline. |
| `router` | `switchOnObjectiveMiss` | `false`, `true` | `true` implements the documented rule that meeting the latency objective outranks token cost: an incumbent predicted to miss the limit is replaced (after cooldown) by an alternative predicted to meet it, even if that alternative uses more tokens. With `false`, such a switch must also save ≥ `materialImprovement` tokens. |
| `budget` | `forecast` | `lookahead`, `expected` | `expected` forecasts remaining demand as remaining request count × calibration-mix expected tokens, without reading future request sizes. `lookahead` uses the actual remaining workload (a batch-workload assumption). |

A study may set `targets` to a subset of the baseline's held-out targets (never
calibration targets). The workload keeps balanced blocks of every context size, so
four targets give a 24-request long64 episode. Use this for pilots with their own
seeds; pilot episodes are never pooled with full collections.

Prepared plans also record calibration token quantiles (`tokenQuantiles`), latency
quantiles (`latencyQuantiles`) and the calibration size-bin mix (`calibrationSizeMix`). Episode IDs now hash the policy
configuration, scenario, workload and study settings (baseline digest,
configurations, latency limit, token budget, quality floor), so IDs no longer
collide between studies that reuse policy names and seeds. Previously prepared
studies keep their sealed IDs.

### Cascade policy (within-request fallback)

```json
"cascade-mcp": {"type": "cascade", "primary": "local-mcp-lean",
                "fallbacks": ["local-mcp-default"],
                "triggerFailureClasses": ["step-limit", "tool-use"]}
```

Each request first runs `primary`. If that attempt fails with one of
`triggerFailureClasses` (classified from the execution only, never from
evaluation), the single declared fallback runs for the same request. Optional
`primaryMaxSteps` lowers the primary attempt's `max_steps` (an early-abort
variant); optional `memory: "source"` sends later requests for a repository
whose primary attempt failed straight to the fallback (an ablation; it keys on the
repository, never the target function).

Every attempt is a canonical trial: both appear in `trials.jsonl`,
`responses.jsonl` and traces, and `llmctxbench eval` scores both. The request
outcome is the final attempt. Its latency is the sum of attempt durations, and its
tokens are the sum of attempt usage; if any attempt's usage is unknown, the total
is `unavailable` with the known lower bound in `knownPartial`. Decision records use
`schemaVersion` 4 and add `attempts`, `finalConfiguration` and `fallbackReason`.
Resume never repeats a completed attempt; an attempt interrupted after it started
requires `--retry-uncertain`, and its usage is then unknown.

`study analyze` reports `fallbacks`, `tokensLowerBound` (unknown totals counted at
their known partial usage) and `wastedTokensLowerBound` (failed attempts before a
fallback), next to `knownTokens`, which covers fully known requests only.

### Reference policies, budget pacing and scenario effects

| Policy | Definition | Purpose |
|---|---|---|
| `schedule` | `{"type": "schedule", "default": {"small": cid, ...}, "phases": [{"firstRequest": 31, "lastRequest": 60, "configurationBySize": {...}}]}` | Phase oracle. It is given the disturbance schedule by design, so it is an upper bound for comparison, never a deployable policy. |
| `random-eligible` | `{"type": "random-eligible", "seed": 7}` | Seeded uniform choice among eligible configurations; a sanity baseline. |
| `budget` with `mode: "pace"` | `{"type": "budget", "mode": "pace", "forecast": "expected", "unknownUsage": "bounded"}` | For each request, picks the fastest qualified configuration whose estimated cost still leaves enough budget to serve every remaining request with the cheapest qualified configuration. |

Scenario entries are effects. Entries without `kind` are delays, as before.

```json
{"kind": "fault", "configuration": "local-mcp-default", "toolErrorRate": 0.3, "seed": 11,
 "firstRequest": 31, "lastRequest": 60}
{"kind": "token-quota", "tokensPerMinute": 250000, "firstRequest": 49, "lastRequest": 72}
```

- `fault` (local MCP only): each tool call in the range returns a tool error result
  (`is_error`, so the model sees a failing service) with the given probability.
  Draws are seeded by `seed`, request position and call number, so they are
  identical across arms at the same position.
- `token-quota` (all configurations): a harness-simulated provider quota. Before
  each request in the range, the runner waits until tokens completed in the
  trailing 60 s fall below the quota. Unknown usage counts at its known partial
  value. The wait is inside the measured request duration. Quota history is kept
  in process memory and restarts empty after a resume.

Decision records (`schemaVersion` 4) add `quotaWaitMs`, `faultsInjected` and
`controllerMs` (policy decide/observe time, measured with `perf_counter`).

## Provider-free replay

`study replay` drives the real study controller over outcomes resampled from
frozen calibration observations, applying disturbances analytically. It is for
debugging and parameter selection; claims require live episodes.

```bash
llmctxbench study replay --baseline baselines/repoqa-long64/frozen.json \
  --grid examples/studies/replay/degradation.grid.json --output studies/replay/degradation.json
llmctxbench study counterfactual --study-dir studies/repoqa-long64-budget \
  --primary mcp-lean --fallback mcp-default
```

A grid (`schemaVersion` 1) declares `seeds`, `replicates`, optional `configurations`
(subset of the baseline), `base` study settings (`latencyLimitMs`, `tokenBudget`),
`policies` (same schema as study policies), and `points`. Each point has a `name`,
optional `latencyLimitMs`/`tokenBudget`, `effects` (same schema as scenario effects)
and optional per-point `policies` overrides, typically a `schedule` oracle that
matches the point's disturbance. Workloads use the held-out request order for each
seed, so only size bins are taken from held-out requests; outcomes come from the
calibration pool.

Disturbance model: a request delay adds `delayMs`; a tool-call delay adds `delayMs`
× the sampled execution's recorded tool calls; a fault adds one step's duration and
tokens per injected fault and fails with `step-limit` beyond 8 steps (an
assumption, not a measurement); a token quota uses a simulated clock.

Per point and policy, the report gives mean deadline misses, failures, pass rate,
latency (mean, p95), token lower bound, fallbacks, probes, switches, and reaction
and recovery lags. `opportunity` is the reference policy's metric minus the
`schedule` oracle's; `capture` is the share of that gap a policy recovers. The
reference is the non-adaptive router by default, so capture measures what runtime
feedback adds; fixed arms are reported for the cost side of the trade-off. The
report is marked `provenance: estimated`.

`study counterfactual` pairs two fixed arms of a completed study by seed and
request, charging the fallback only where the primary failed. It reuses held-out
executions and is marked `heldOutDebug: true`.

## Analysis outputs (`analysis.json` schema 3, additive fields)

Per episode, `summaries` add:
- `passRateAllRequests`: passed / planned, so failed and unserved requests count as not passed (`passRate` remains the rate over evaluated requests);
- `tokensLowerBound`, `fallbacks`, `wastedTokensLowerBound`;
- `switches` (non-probe routing changes), `probeTokensLowerBound`, `probeDeadlineMisses`;
- `controllerMsP50`/`controllerMsP95`;
- `phaseSummaries`: misses, latency, tokens, failures and passes per scenario phase;
- `lags`: for each disturbance of a configuration that was in use just before it, `reactionLag` (requests from onset to the first non-probe request routed elsewhere) and `recoveryLag` (requests from the end to the first non-probe return); `null` means it never happened.

`arms` aggregates each policy and scenario over episodes (mean, minimum, maximum).
Each comparison adds `metrics` with paired differences and target-cluster
bootstrap intervals for `latencyMs`, `deadlineMiss`, `tokensLowerBound`, `failure`
and `passed`; the original latency fields are unchanged. Plots are labelled SVGs:
`latency-*.svg` (one panel per policy with the latency limit, disturbance bands and
a strip of executed configurations) and `tradeoff-*.svg` (token lower bound per
request against deadline-miss rate, or failure rate when no limit is set).

## SEAMS v2 suite: command sequence

The pre-registration (`docs/development/seams2027-preregistration.md`) fixes the
selection rules and gates. Code is frozen at tag `seams-v2-freeze`; a change to any
measurement source after that needs a new baseline.

1. v2 baseline (provider-backed, about 720 requests):
   ```bash
   llmctxbench study baseline prepare --definition examples/studies/baseline.repoqa-long64.json \
     --output baselines/repoqa-long64-v2
   llmctxbench study baseline execute --prepared baselines/repoqa-long64-v2/prepared.json
   for r in baselines/repoqa-long64-v2/episodes/*/responses.jsonl; do llmctxbench eval "$r"; done
   llmctxbench study baseline freeze --prepared baselines/repoqa-long64-v2/prepared.json
   ```
2. Parameter selection (provider-free). Apply the pre-registered rule, set `V2` and
   `SA_*` in `tools/seams/make_grids.py`, then regenerate:
   ```bash
   llmctxbench study replay --baseline baselines/repoqa-long64-v2/frozen.json \
     --grid examples/studies/replay/degradation.grid.json --output studies/replay-v2calib/degradation.json
   python tools/seams/make_grids.py
   ```
3. Pilots (provider-backed, about 290 requests), each followed by eval and analyze:
   ```bash
   llmctxbench study prepare --definition examples/studies/pilot.cascade.json --output studies/pilot-cascade
   llmctxbench study prepare --definition examples/studies/pilot.degradation.json --output studies/pilot-degradation
   ```
   Run every episode in each prepared matrix with the episode loop above, then
   `llmctxbench eval` each `responses.jsonl` and `llmctxbench study analyze` each
   directory. Check the go criteria before continuing.
4. Collection (provider-backed, about 5.8k requests): prepare
   `study.seams-cascade.json` into `studies/seams-cascade` and
   `study.seams-degradation.json` into `studies/seams-degradation`, run the episode
   loop (seed-major, arm order shuffled within each seed), then evaluate and analyze.
