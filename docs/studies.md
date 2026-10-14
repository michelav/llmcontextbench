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
| `budget` | `forecast` | `lookahead`, `expected` | `expected` forecasts remaining demand as remaining request count × calibration-mix expected tokens, without reading future request sizes. `lookahead` uses the actual remaining workload (a batch-workload assumption). |

Prepared plans also record calibration token quantiles (`tokenQuantiles`) and the
calibration size-bin mix (`calibrationSizeMix`). Episode IDs now hash the policy
configuration, scenario, workload and study settings (baseline digest,
configurations, latency limit, token budget, quality floor), so IDs no longer
collide between studies that reuse policy names and seeds. Previously prepared
studies keep their sealed IDs.
