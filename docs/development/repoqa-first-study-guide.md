# RepoQA adaptive study: concepts, execution and reproduction

This guide explains and reproduces the current RepoQA adaptive research protocol.
Read it alongside [the resumable workflow reference](repoqa-resumable-workflow.md).
It describes implementation behavior, not observed experimental benefits. No paid
experiment is implied to have been completed by this document.

The sequence is:

```text
fixed experiment + dataset + code revision
  -> prepare: split targets, pair candidates, order workloads, assess context fit
  -> baseline calibration: measure both configurations
  -> delayed calibration: measure four controlled MCP disturbances
  -> freeze: lock estimates, latency objective and selected disturbance
  -> episodes: compare four policies across seeds and permitted scenarios
  -> eval: score answers outside the controller
  -> export + metrics: produce standard benchmark tables
  -> analyze: join routing, outcomes, quality, resources and recovery history
```

## 1. Concepts and experimental units

| Concept | Meaning | Connection |
|---|---|---|
| Study | Fixed code, dataset, configuration, preparation and calibration | Contains all comparison episodes |
| Target | A target function identified by `baseId` | All its context variants stay together in the split |
| Instance / variant | One target embedded in a 2k, 4k, 8k or 16k context | An input to a scheduled request |
| Task | `snf_retrieve_function`, the retrieval instruction | Shared across instances |
| Configuration | Strategy + representation + surface | A concrete action available to a policy |
| Candidate trial | Immutable specification for a configuration/input/repeat | Each request has inline and MCP candidates |
| Request | One input at one position in a workload | Executes at most one selected candidate |
| Repeat | Another calibration execution of an input | Two repeats are built into each calibration condition |
| Seed | Reproducible pseudorandom-generator initialization | Determines splits or workload orders, not LLM generation randomness |
| Policy / arm | Rule selecting configurations | Four arms share the same candidate catalog |
| Scenario | Environmental condition | Stationary or degradation/recovery |
| Episode | One policy processing one ordered workload under one scenario | Identified by scenario, seed and policy |
| Comparison block | Four policy episodes for one scenario/seed | Holds workload and disturbance schedule constant |
| Observation | Execution status, duration and tokens | Updates adaptive estimates |
| Probe | Scheduled execution of an alternative eligible configuration | Observes an otherwise inactive option |
| Frozen calibration | Immutable baseline estimates, objective and disturbance choice | Shared initialization for held-out routers |

For example, target T has a 16k instance. An episode seed places that instance at
request 27. In degradation/recovery, position 27 is disturbed. A policy selects
one configuration and executes it; the adaptive policy uses its observation when
making later decisions. Every arm sees the same input at position 27, but each
arm executes independently.

The current dataset has 20 targets, each with four variants: 80 instances. A fixed
language-stratified split selects four calibration targets and 16 held-out targets.
All variants of a target remain on one side of the split. This is target-level
separation, not an explicit guarantee of repository-disjoint populations.

| Stage | Inputs | Repeats | Scheduled executions |
|---|---|---:|---:|
| Baseline calibration | 16 calibration variants | 2 | 32 inline + 32 local MCP |
| Each delayed calibration | Same 16 variants | 2 | 32 local MCP |
| Each held-out episode | 64 held-out variants | 1 | 64 |

Preparation creates 320 **candidate specifications**: 80 instances × two
configurations × two repeats. It does not execute 320 requests.

Three different seed uses must remain distinct:

- Split seed `20260929`: chooses calibration targets, one per language. Calibration
  workload ordering also uses this fixed seed.
- Episode seeds `20261001`, `20261002`, `20261003`: order the same held-out population.
  Every four-request block contains one variant of each size. Seeds also determine
  the recorded counterbalanced policy execution order.
- Bootstrap seed `20260929`: makes statistical resampling reproducible.

Episode seeds measure order sensitivity as well as repeated live execution
variability. They do not create new independent repositories, seed the answering
model, or make provider responses deterministic.

## 2. Prerequisites and study settings

Run commands from the repository root in the existing benchmark Python environment.
Examples use Bash and `jq`. Required inputs are:

- `experiment.repoqa-adaptive.json`, finalized for the intended model and parameters;
- the materialized RepoQA dataset at the experiment's `dataset.root` (currently
  `datasets/repoqa`), including its index and context artifacts;
- provider credentials in the environment, such as `OPENAI_API_KEY` for OpenAI;
- the existing isolated RepoQA scorer environment. The wrapper defaults to
  `tools/repoqa/.venv/bin/python`; `REPOQA_PYTHON` can select an existing alternative.

Do not put credentials in experiment files, logs or documentation. This guide does
not install dependencies.

The experiment must retain exactly two calibration repeats, both supported
configurations, and one answering provider/model. Choose the actual model context
limit and an output cap large enough to return the requested function. Verify model
limits separately; the values in the shorter workflow reference are examples.

Set these shell variables once, replacing the placeholders with integers:

```bash
STUDY=runs/repoqa-first-study
CONTEXT_LIMIT='<verified-model-context-limit>'
OUTPUT_RESERVATION='<chosen-output-token-cap>'
```

Choose a fresh study directory. Finalize and preferably commit configuration and
code changes **before** preparation. Record the Git revision and environment used.
After preparation, keep the revision, relevant source files, experiment and dataset
unchanged. Even a new commit changes the recorded revision. Continue old studies
on their original revision or prepare a new study; never bypass fingerprints.

A provider-free scorer preflight is:

```bash
python - <<'PY'
import runpy
cli = runpy.run_path('tools/repoqa/run_adaptation.py')
print(cli['scorer_smoke']())
PY
```

`prepare`, `freeze`, exports, metrics and analysis make no generation calls.
`calibrate` and `episode` execute the configured provider and spend tokens; MCP
requests can make multiple model calls. Invoking those commands expresses execution
intent. There is no `--execute-providers` option. An agent launching paid calls on
your behalf still needs explicit prompt authorization.

## 3. Prepare the immutable inputs

```bash
python tools/repoqa/run_adaptation.py prepare \
  --experiment experiment.repoqa-adaptive.json \
  --output "$STUDY" \
  --context-limit "$CONTEXT_LIMIT" \
  --output-reservation "$OUTPUT_RESERVATION"
```

Preparation pairs candidates, selects targets, generates workloads, computes initial
context-fit assessments and records source/configuration/dataset fingerprints.
The output reservation also becomes the model generation output cap.

Output: `$STUDY/prepared.json`. This is a sealed envelope; inspect `.payload`:

```bash
jq '.payload | {
  split, budget, costProjection,
  candidateTrials: (.trials | length),
  calibrationVariants: (.calibrationOrder | length),
  heldOutRequestsPerSeed: (.heldOut | map_values(length))
}' "$STUDY/prepared.json"
```

Check 320 candidates, 16 calibration variants, 64 held-out requests per seed and
four/16 calibration/held-out targets. Inspect the budget assumptions. A local
tokenizer is used when available and supported; otherwise UTF-8 bytes provide a
conservative estimate. Serialization allowance remains estimated. Context fit
covers the initial prompt, not all future MCP tool-loop growth.

This phase validates experimental design, not performance. Preparation refuses to
overwrite an existing prepared study.

## 4. Measure baseline calibration

**Provider-backed step:** 64 scheduled executions, with potentially multiple model
calls per MCP execution.

```bash
python tools/repoqa/run_adaptation.py calibrate \
  --prepared "$STUDY/prepared.json" \
  --output "$STUDY"
```

One invocation performs both repeats for both fixed arms. Do not invoke it twice
to obtain the two repeats.

Outputs:

```text
$STUDY/calibration/baseline/always-inline/
$STUDY/calibration/baseline/always-local-mcp/
```

Each folder uses the episode artifact structure in section 8. Inspect a compact
summary rather than entire response or trace files:

```bash
CAL="$STUDY/calibration/baseline/always-local-mcp"
jq -s '{
  requests: length,
  statuses: (group_by(.status) | map({status: .[0].status, count: length})),
  durationCoverage: ([.[] | select(.endToEndDurationMs.value != null)] | length),
  tokenCoverage: ([.[] | select(.tokens.value != null)] | length)
}' "$CAL/decisions.jsonl"
```

Expect 32 completed decisions per arm. Check errors and missing measurements;
compare duration and tokens by configuration and size bin. Small means 2k/4k;
large means 8k/16k. These are nominal variant bins, not bins dynamically derived
from measured bytes.

All 64 baseline executions must be successful and have durations for freezing.
Initial routing estimates use the last five successful observations in each
configuration/bin group. Objective and disturbance qualification use broader
baseline samples. Calibration metadata uses an objective of zero: do not interpret
its deadline-miss rate as a held-out result.

Optionally evaluate completed calibration responses with `llmctxbench eval` to
inspect pilot quality. Those scores never feed routing or freeze logic. If the
pilot exposes invalid settings, correct them and start a fresh prepared study.
Do not selectively rerun completed failures to improve a calibration history.

## 5. Measure delayed calibration

**Provider-backed step:** four conditions × 32 local-MCP executions = 128 executions.

```bash
for delay in 100 250 500 1000; do
  python tools/repoqa/run_adaptation.py calibrate \
    --prepared "$STUDY/prepared.json" \
    --output "$STUDY" \
    --delay-ms "$delay" || break
done
```

Outputs:

```text
$STUDY/calibration/delay-100/always-local-mcp/
$STUDY/calibration/delay-250/always-local-mcp/
$STUDY/calibration/delay-500/always-local-mcp/
$STUDY/calibration/delay-1000/always-local-mcp/
```

“Repeat calibration with delays” means repeat the workload under different
experimental conditions. Each condition already includes two repeats.

Delay applies before **each tool invocation**, not once per request. Four tool
calls at 250 ms add approximately one second of waiting, on top of model and tool
execution. Discovery is not delayed. This is controlled local tool-service
degradation, not a reproduction of every property of remote MCP.

Inspect completion, success, duration distributions and tool-call counts. The
resulting request duration depends on how many calls the model makes. Delayed
calibration selects disturbance severity; it does not provide the routers' initial
performance estimates.

The current CLI reads all four delay histories when freezing and rejects missing
or incomplete histories. Finish all five calibration conditions first. Complete
but unsuccessful delayed conditions cannot qualify. Total calibration is 192
scheduled executions, not necessarily 192 API calls.

## 6. Freeze initialization and experimental conditions

Use the default objective if this study has no externally justified application
latency requirement:

```bash
python tools/repoqa/run_adaptation.py freeze \
  --prepared "$STUDY/prepared.json" \
  --output "$STUDY"
```

Alternatively, choose a meaningful application objective **before** viewing
held-out results and add `--application-slo-ms <objective-in-milliseconds>` to that
command. Run only one freeze command; existing frozen output is not overwritten.

Output: `$STUDY/frozen.json`.

```bash
jq '.payload | {
  objectiveSource, latencyObjectiveMs, baselineLocalP95Ms,
  qualification, selectedDelayMs, scenarios, estimates, costProjection
}' "$STUDY/frozen.json"
```

Without an explicit application objective, the objective is the pooled baseline
nearest-rank p90 across both configurations. This is a benchmark-derived objective,
not evidence of a real application's service requirement.

The smallest delay qualifies when:

1. All 32 delayed observations are successful local-MCP executions with durations.
2. Delayed local-MCP p95 is at least 1.25 × baseline local-MCP p95.
3. At least one delayed duration exceeds the objective.

If `selectedDelayMs` is null, only stationary episodes are permitted. A qualifying
delay does not guarantee a routing change: MCP might already be disfavored, or
its mean-based estimate might remain within the objective.

Check starting estimates, objective provenance, each condition's qualification,
and projected cost. The token projection extrapolates baseline mean tokens to
1536 held-out requests; it is approximate, has no currency price provenance, and
retains that full-schedule count even if only stationary episodes are allowed.
A stationary-only schedule has 768 requests. Do not interpret projections as
provider billing or API-call counts.

Frozen settings lock shared initialization for the routers. Moving-average size,
minimum sample count, cooldown and improvement threshold are fixed implementation
parameters, not parameters selected by this calibration command.

## 7. Execute held-out comparison episodes

**Provider-backed step:** each comparison block schedules 256 requests.

For one fresh block:

```bash
python tools/repoqa/run_adaptation.py episode \
  --prepared "$STUDY/prepared.json" \
  --output "$STUDY" \
  --seed 20261001 \
  --scenario stationary \
  --policy all
```

| Policy | Behavior |
|---|---|
| `always-inline` | Uses inline when eligible; does not substitute MCP |
| `always-local-mcp` | Uses MCP when eligible; does not substitute inline |
| `frozen-router` | Uses baseline estimates throughout |
| `adaptive-router` | Updates estimates from successful runtime observations |

The routers first exclude ineligible candidates. Among those predicted to meet
the objective, they prefer lower estimated tokens. If none meets it, they prefer
lower estimated latency. An objective is a selection criterion, not an enforced
cancellation deadline.

The adaptive router uses the latest five successful observations per
configuration/bin, replacing calibration for a metric after at least three usable
runtime samples. Switching ordinarily requires 10% improvement and respects a
five-request cooldown. Objective compliance has priority, subject to cooldown.
Errors remain recorded but do not become successful performance samples.

Both routers probe the alternative eligible configuration at positions 10, 20,
30, 40, 50 and 60. Probes are temporary executions; distinguish the normal incumbent
from the actual probe selection. They are included in resource and quality results.
Each episode starts with independent state and the same frozen initialization.

Outputs: `$STUDY/episodes/<scenario>/<seed>/<policy>/`.

For degradation/recovery, the frozen delay applies automatically:

| Positions | Local-MCP condition |
|---|---|
| 1–20 | Normal |
| 21–44 | Delayed per tool invocation |
| 45–64 | Normal again |

Do not pass `--delay-ms` to `episode`. The controller receives observations rather
than phase labels. Each phase contains both size bins.

For a fully fresh study, the following Bash subshell runs all allowed blocks and
stops on failure. Use this **instead of** the single-block command above if no
block has been executed yet:

```bash
(
  set -e
  SCENARIOS=$(jq -r '.payload.scenarios[]' "$STUDY/frozen.json")
  for seed in 20261001 20261002 20261003; do
    for scenario in $SCENARIOS; do
      python tools/repoqa/run_adaptation.py episode \
        --prepared "$STUDY/prepared.json" \
        --output "$STUDY" \
        --seed "$seed" \
        --scenario "$scenario" \
        --policy all
    done
  done
)
```

Both scenarios give 24 episodes and 1536 held-out requests. Stationary only gives
12 episodes and 768 requests. These counts exclude calibration. Different arms
execute separately; results are not replayed as substitutes for live measurements.
OpenAI cache keys are partitioned by arm/seed/scenario, but keys do not guarantee
provider-side cache isolation. Execution order is counterbalanced, not concurrent.

## 8. Inspect episode artifacts and completion

Calibration and held-out folders contain:

| Artifact | Meaning and use |
|---|---|
| `manifest.json` | Configuration definitions and artifact settings |
| `adaptive-run.json` | Policy, seed, scenario, objective and provenance |
| `trials.jsonl` | Selected execution specifications |
| `responses.jsonl` | Executed outcomes and answers |
| `traces/executions/<trialId>.json` | Detailed execution trace for a selected trial |
| `decisions.jsonl` | Features, candidates, estimates, reasons, probes and outcomes |
| `controller-timings.jsonl` | Selection/observation durations |
| `lifecycle.json` | Sessions, completion, interruption and recovery events |
| `recovery/identity.json` | Sealed episode fingerprint and immutable inputs |
| `recovery/request-NNNN.json` | Durable selection/outcome record for each request |

Recovery packets are the durable source for repairing projections. Do not edit
them. An unserved request has a decision but no executed trial/response; 64 decisions
does not imply 64 response rows.

```bash
EPISODE="$STUDY/episodes/stationary/20261001/adaptive-router"
jq '{completed, sessions, events}' "$EPISODE/lifecycle.json"
jq -s 'length' "$EPISODE/decisions.jsonl"
jq -c '
  select(.decision.features.sequenceIndex >= 18
         and .decision.features.sequenceIndex <= 25)
  | {
      requestId, status,
      index: .decision.features.sequenceIndex,
      selected: .decision.selectedConfiguration,
      normal: .decision.normalConfiguration,
      probe: .decision.probe,
      reason: .decision.reason,
      durationMs: .endToEndDurationMs.value,
      tokens: .tokens.value
    }
' "$EPISODE/decisions.jsonl"
```

Expect `completed: true` and 64 decisions for a held-out episode (32 for each
calibration arm). Investigate anomalies using one request and its linked trace.
Do not print complete response files or entire trace trees.

## 9. Recover interruptions

Repeat the exact interrupted calibration/episode command with `--resume`. For
example:

```bash
python tools/repoqa/run_adaptation.py episode \
  --prepared "$STUDY/prepared.json" \
  --output "$STUDY" \
  --seed 20261001 \
  --scenario stationary \
  --policy all \
  --resume
```

Resume validates fingerprints, locks the episode directory, reconstructs decisions
and observations, repairs projections and continues unfinished work. Completed
successes, errors and unserved outcomes remain final. A completed episode is
verified without further model calls.

With `--policy all`, resume is applied to every arm. If an interruption prevented
later arm directories from being created, those fresh arms cannot be resumed.
Resume existing arms individually using `--policy <arm> --resume`, then execute
missing arms individually without `--resume`, following the recorded
`cachePolicy.counterbalancedOrder` in an existing arm's `adaptive-run.json`.

Only add `--retry-uncertain` when an execution-start marker has no durable outcome
and you accept possible duplicate provider expenditure. Prior uncertain usage
remains unavailable. Recovery does not restore provider cache, network, rate-limit,
conversation or tool-session state. Downtime does not advance request-index phases.

After a failed batch, inspect which directories exist and continue the appropriate
commands. Do not blindly restart the fresh-study loop. Independent replication
requires a new study; resume is not another replicate.

## 10. Evaluate completed answers

```bash
llmctxbench eval "$EPISODE/responses.jsonl"
```

RepoQA uses the deterministic scorer, not paid LLM judges. Outputs include
`$EPISODE/evals.jsonl` and `$EPISODE/evals-summary.json`; evaluation traces follow
trace settings. Judge-vote artifacts are not needed for this scoring method.

Check usable pass/fail outcomes for successful responses. Investigate truncation,
malformed answers and incorrect matches. Missing evaluation is not a zero score.
The adaptive analysis treats execution errors/unserved requests as quality failures
and leaves the complete pass rate unavailable when successful answers lack scores.
Evaluation feedback never reaches the controller. Keep execution and evaluation
resource accounting separate.

## 11. Export and calculate standard benchmark metrics

```bash
llmctxbench export "$EPISODE/evals.jsonl" \
  --output "$EPISODE/results.csv"
llmctxbench metrics "$EPISODE"
```

Outputs are `results.csv` and `metrics/`, including `trial_metrics.csv`,
`aggregate_metrics.csv`, `dimension_summary.csv`, `failure_cases.csv`, dimension
CSVs, `summary.json` and `metrics-manifest.json`.

These derive tables from saved artifacts without generating answers. Standard
metrics describe executed trials; use adaptive analysis for the full scheduled
request denominator, including unserved requests. Retain scenario/seed/policy and
episode path when combining data: trial IDs can recur across episodes.

After all scheduled episodes are complete, this subshell processes every expected
folder and stops if one is missing or incomplete:

```bash
(
  set -e
  SCENARIOS=$(jq -r '.payload.scenarios[]' "$STUDY/frozen.json")
  for seed in 20261001 20261002 20261003; do
    for scenario in $SCENARIOS; do
      for policy in always-inline always-local-mcp frozen-router adaptive-router; do
        EPISODE="$STUDY/episodes/$scenario/$seed/$policy"
        jq -e '.completed == true' "$EPISODE/lifecycle.json" >/dev/null
        llmctxbench eval "$EPISODE/responses.jsonl"
        llmctxbench export "$EPISODE/evals.jsonl" \
          --output "$EPISODE/results.csv"
        llmctxbench metrics "$EPISODE"
      done
    done
  done
)
```

A nonempty metrics directory causes a rerun to stop. To regenerate safely without
provider execution, select a fresh derived output directory, for example
`llmctxbench metrics "$EPISODE" --output "$EPISODE/metrics-recomputed"`.
The `--force` option replaces the target metrics directory; use it only deliberately.

## 12. Analyze the adaptive study

```bash
python tools/repoqa/run_adaptation.py analyze --output "$STUDY"
```

Outputs:

```text
$STUDY/analysis/summary.json
$STUDY/analysis/timeline.jsonl
$STUDY/analysis/timeline.csv
$STUDY/analysis/timeline-<scenario>-<seed>-<policy>.svg
```

SVGs require already-installed matplotlib; CSV/JSONL analysis works without it.
Analysis validates completed episode artifacts and joins decisions, responses,
evaluations, traces, controller timings and recovery history. It never invokes
providers or the scorer. Incomplete discovered episodes cause analysis to fail;
missing comparison partners are reported rather than invented.

```bash
jq '.episodes[] | {
  policy, scenario, seed, scheduledRequests, errors, unserved,
  qualityCoverage, allRequestPassRate, timingCoverage, p50Ms, p95Ms,
  deadlineMissRate, tokenCoverage, knownTotalTokens, resourceTotalsComplete,
  normalSwitches, probes, reaction, interrupted
}' "$STUDY/analysis/summary.json"
jq '{primary, uninterruptedCompleteBlocks}' "$STUDY/analysis/summary.json"
```

Analyze in this order:

1. **Completeness:** errors, unserved requests, metric coverage and uncertain usage.
   Missing timing/tokens remain unavailable. Known partial sums are not complete
   resource totals.
2. **Stationary control:** does adaptation add overhead, unnecessary switching or
   quality loss when infrastructure is stable?
3. **Degradation:** compare deadline misses and latency during requests 21–44.
4. **Recovery:** inspect normal routing after request 45, separating probes from
   incumbent changes. Recovery need not mean returning to MCP if it remains worse.
5. **Quality/resources:** check whether efficiency improvements harm answers or
   increase tokens elsewhere.
6. **Adaptive versus frozen:** compare matched scenario/seed/request outcomes.

Paired differences are adaptive minus frozen. Negative deadline-miss, duration and
token differences favor adaptation; positive pass differences favor adaptation.
The 95% percentile bootstrap resamples target groups within languages, retaining
variants and seeds together (10,000 replicates by default). This does not establish
repository-level independence or compensate for a small target population.

Reaction counts requests through the first non-probe normal routing change relative
to the phase-entry incumbent. No change is censored, not zero reaction time. The
summary's uninterrupted sensitivity includes only complete four-arm blocks without
resumed episodes. Compare it with primary results, which retain resumed episodes.

## 13. Interpretation limits and reproduction record

- Outer execution duration includes executor preparation/execution but excludes
  controller selection/observation and persistence. Controller timing measures
  selection plus observation separately; replay and projection overhead are outside
  it. Do not label either value total application response time.
- Probe executions contribute to episode resources and quality. Probe counts and
  timeline flags exist, but a dedicated probe-resource subtotal is not summarized.
- Candidate eligibility is saved, but default summaries do not stratify requests
  where both configurations fit versus only one. Produce that breakdown before
  attributing capacity-driven gains to adaptive feedback.
- The controller optimizes operational estimates, not measured answer correctness.
  Error-rate circuit breakers, mid-request fallback and deadline cancellation are
  outside this prototype.
- Context-fit fallback counting and some token values are estimated. Preserve
  `reported`, `measured`, `derived`, `estimated` and `unavailable` provenance.
- Live executions are needed for claims about provider latency and adaptive benefit.
  Replay establishes controller consistency, not real service performance.

Archive the exact experiment configuration, dataset identity/hash, Git revision,
Python/dependency environment, commands, chosen limits and objective rationale,
`prepared.json`, calibration histories, `frozen.json`, every episode's durable and
canonical artifacts, evaluations and analysis outputs. Keep credentials out of the
archive. Saved exports/metrics/analysis can be regenerated without answering-model
calls; exact live provider responses and timing cannot be guaranteed on repetition.

For implementation verification without providers:

```bash
pytest -q tests/test_adaptive_policy.py tests/test_adaptive_calibration.py \
  tests/test_repoqa_surfaces.py
pytest -q tests/test_adaptive_runner.py tests/test_adaptation_analysis.py
```

Tests verify mechanics and safeguards; they are not empirical evidence that the
adaptive policy outperforms the baselines.
