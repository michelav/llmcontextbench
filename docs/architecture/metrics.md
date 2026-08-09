# Specification: `llmctxbench metrics`

> Design reference for the already-shipped `llmctxbench metrics` command. Relocated
> from a root-level, untracked `ctxbench_metrics_spec.md` into `docs/architecture/`
> for consistency with the rest of the architecture documentation; not re-run through
> the `specs/` spec-driven-development workflow.

## 1. Feature Summary

Implement a new `llmctxbench metrics` command that computes reproducible benchmark metrics from existing LLMContextBench experiment artifacts.

The command must be deterministic, artifact-only, and must not call model providers, MCP servers, external APIs, deterministic scorers, or any other external service. It must only read artifacts already produced by the benchmark lifecycle and materialize canonical metric artifacts.

The metrics model must be organized around five core dimensions inspired by HELM's multi-metric evaluation philosophy and adapted to LLMContextBench:

1. **Effectiveness**
2. **Efficiency**
3. **Robustness / Stability**
4. **Evaluation Reliability**
5. **Observability**

The initial implementation must support only these five core dimensions. Dataset-specific metrics and plot-specific datasets are out of scope.

---

## 2. Motivation

LLMContextBench already produces structured lifecycle artifacts through its main workflow:

```text
llmctxbench plan
  -> trials.jsonl + manifest.json

llmctxbench execute
  -> responses.jsonl + execution traces

llmctxbench eval
  -> evals.jsonl + judge_votes.jsonl + evaluation traces

llmctxbench export
  -> results.csv
```

However, the analysis of benchmark results may still depend on notebooks or ad hoc scripts that recompute metrics from raw artifacts. This makes results harder to reproduce and harder to compare across datasets, models, strategies, and papers.

The `llmctxbench metrics` command must make metrics a first-class artifact of the benchmark. It should transform raw lifecycle artifacts into stable, canonical metric files that can be consumed by notebooks, scripts, dashboards, papers, and CI checks.

The intended workflow is:

```text
benchmark lifecycle artifacts
  -> llmctxbench metrics
  -> canonical metric artifacts
  -> notebooks/scripts generate paper tables and figures
```

The command must not generate plot-specific data. Notebooks and external scripts are responsible for transforming metric artifacts into paper-specific tables and figures.

---

## 3. Design Principles

### P1. Artifact-only

`llmctxbench metrics` must only read existing artifacts.

It must not:

- execute trials;
- re-evaluate responses;
- call LLM providers;
- call remote MCP servers;
- call external APIs;
- invoke dataset scorers;
- mutate benchmark lifecycle artifacts.

### P2. Deterministic

Running the command twice over the same input artifacts must produce the same metric values.

Generated timestamps and command-line provenance in `metrics-manifest.json` may differ between runs.

### P3. Multi-dimensional

The command must not collapse the benchmark into a single score.

It must expose five core dimensions:

```text
effectiveness
efficiency
robustness
evaluation_reliability
observability
```

### P4. Dataset-agnostic core

The first implementation must not contain dataset-specific metric providers for Lattes, RepoQA, or any other dataset.

The command may normalize the primary effectiveness value from known evaluation methods, such as `judge` and `repoqa-scorer`, but it must not generate dataset-specific tables or metrics.

### P5. No plot-specific outputs

The command must not generate a `plot_data/` directory.

It must not generate files whose schema is designed for a specific figure, table, article, or notebook.

Plotting and paper-specific transformations must be implemented outside the CLI, using notebooks or scripts that consume the canonical metrics.

### P6. Missing values are valid

When a metric cannot be computed reliably, the command must emit:

- empty cells in CSV;
- `null` in JSON.

The command must not invent values.

### P7. Evaluation method awareness

The command must support heterogeneous evaluation methods.

The first implementation must support at least:

```text
judge
repoqa-scorer
```

It must normalize them into a common primary effectiveness interface:

```text
primary_metric_name
primary_success
primary_score
```

---

## 4. CLI Contract

### 4.1 Basic usage

```bash
llmctxbench metrics outputs/lattes_baseline
```

Default output directory:

```text
outputs/lattes_baseline/metrics/
```

### 4.2 Explicit output directory

```bash
llmctxbench metrics outputs/lattes_baseline \
  --output outputs/lattes_baseline/metrics
```

### 4.3 Multiple experiment directories

```bash
llmctxbench metrics outputs/lattes_baseline outputs/repoqa_baseline \
  --output outputs/paper_metrics
```

When multiple experiment directories are provided, the command must merge all trial-level rows into one `trial_metrics.csv` and compute aggregate metrics across all provided inputs.

Merge rules:

- Each input directory must independently contain `trials.jsonl`.
- If a single input directory is provided and `trials.jsonl` is missing, the command must fail with a clear error.
- If multiple input directories are provided and `trials.jsonl` is missing for one or more directories, the command must warn, skip those directories, and continue with the remaining valid inputs.
- If no valid input directories remain after skipping missing `trials.jsonl` inputs, the command must fail with a clear error.
- `experimentId` is preserved unchanged from each input's artifacts (it is already a string such as `datasets/repoqa` in current outputs).
- If the same `trialId` appears in more than one input directory, the command must fail with a clear error. Distinct experiments must not share trial identifiers.

### 4.4 Grouping

```bash
llmctxbench metrics outputs/lattes_baseline \
  --group-by dataset_id,configuration
```

Default grouping:

```text
dataset_id,configuration
```

Supported grouping fields for the first implementation:

```text
experimentId
dataset_id
dataset_version
provider
modelId
modelName
strategy
format
configuration
instanceId
taskId
taskTags
repeatIndex
evaluation_method
primary_metric_name
```

### 4.5 Selectors

The command should reuse the existing selector model used by `execute`, `eval`, and `export`.

Supported selectors:

```text
--model
--provider
--instance
--task
--strategy
--format
--repetition
--trial
--trial-file

--not-model
--not-provider
--not-instance
--not-task
--not-strategy
--not-format
--not-repetition
```

The command must support `--status` and `--not-status` reused from the existing selector infrastructure. Because each trial-level row joins execution and evaluation state, the selector must be unambiguous. The command must implement two distinct metrics-specific status filters:

```text
--execution-status / --not-execution-status
  Filters by the response-phase status (responses.jsonl.status).

--evaluation-status / --not-evaluation-status
  Filters by the evaluation-phase status (evals.jsonl.status).
```

The shorter aliases `--status` / `--not-status` must be accepted as synonyms for `--execution-status` / `--not-execution-status`, since the metrics command is response-driven and this matches the dominant existing usage in `eval` and `export`.

Implementation rule:

- Use the existing `RunSelector` for shared fields (`model`, `provider`, `instance`, `task`, `strategy`, `format`, `repetition`, `trial`, and their negations).
- Represent `--execution-status`, `--not-execution-status`, `--evaluation-status`, and `--not-evaluation-status` in a small metrics-specific selector wrapper.
- Apply `RunSelector` to the joined trial-row representation, with `status` populated from `execution_status`.
- Apply evaluation status filters explicitly against `evaluation_status`.
- Do not extend `RunSelector` with evaluation-specific fields unless a separate accepted spec changes the shared selector contract.

### 4.6 Other options

```text
--output DIR
  Directory where metrics artifacts will be written.

--group-by FIELD[,FIELD...]
  Comma-separated grouping fields used for aggregate_metrics.csv and dimension files.

--force
  Delete the entire target metrics directory tree and recreate it.
  Without --force, the command must fail when the target directory exists
  and is non-empty.

--verbose
  Enable verbose logging. Implementations should reuse the existing
  PhaseLogger (src/ctxbench/util/logging.py) used by `llmctxbench export` so
  that log output is consistent across commands.
```

The command must not include `--no-plot-data`, because plot-specific outputs are not part of this command.

---

## 5. Input Artifacts

For each experiment output directory, the command should attempt to read:

```text
manifest.json
trials.jsonl
responses.jsonl
evals.jsonl
judge_votes.jsonl
traces/executions/
traces/evals/
```

### 5.1 Required artifact

```text
trials.jsonl
```

Without `trials.jsonl`, the command cannot determine the planned trial universe. The command must follow the single-input and multi-input behavior defined in §4.3.

### 5.2 Recommended artifact

```text
manifest.json
```

If missing, the command should warn and continue when possible.

### 5.3 Optional artifacts

```text
responses.jsonl
evals.jsonl
judge_votes.jsonl
evals-summary.json
traces/
```

The command must support partially completed experiments.

`evals-summary.json` is produced by the current evaluation pipeline. The metrics command must ignore it for metric computation: all aggregates must be recomputed from `evals.jsonl` and `judge_votes.jsonl` to keep metrics provenance under the metrics command's control. The file may be read only to cross-check counts in debug logs.

Examples:

- If only `trials.jsonl` exists, generate planning and pending metrics.
- If `responses.jsonl` exists but `evals.jsonl` does not, generate execution, efficiency, and partial observability metrics.
- If `evals.jsonl` exists, generate effectiveness and evaluation reliability metrics.

---

## 6. Output Structure

The command must generate the following structure:

```text
metrics/
  metrics-manifest.json
  trial_metrics.csv
  aggregate_metrics.csv
  dimension_summary.csv
  summary.json
  failure_cases.csv

  dimensions/
    effectiveness.csv
    efficiency.csv
    robustness.csv
    evaluation_reliability.csv
    observability.csv
```

The command must not generate:

```text
metrics/plot_data/
```

All files listed above must always be written, even when the input is partial (planning-only, executed-but-not-evaluated, etc.). When a file has no data rows, the command must still write it with the canonical header row. Downstream consumers must not need to check for file existence — they may only need to check for empty results.

---

## 7. Core Data Model

### 7.0 Field mapping from artifacts to output columns

The command transforms artifact fields (mostly camelCase, sometimes nested) into output columns. To avoid implementation drift, the following mapping is normative:

| Output column / field | Source artifact | Source path |
|---|---|---|
| `dataset_id` | `trials.jsonl` | `dataset.id` |
| `dataset_version` | `trials.jsonl` | `dataset.version` |
| `experimentId` | `trials.jsonl` | `experimentId` (unchanged) |
| `trialId`, `instanceId`, `taskId`, `taskTags` | `trials.jsonl` | top-level (unchanged) |
| `provider`, `modelId`, `modelName`, `strategy`, `format`, `repeatIndex` | `trials.jsonl` | top-level (unchanged) |
| `execution_status` | `responses.jsonl` | `status` |
| `error_message` | `responses.jsonl` | `errorMessage` |
| `input_tokens`, `output_tokens`, `total_tokens` | `responses.jsonl` | `metricsSummary.inputTokens`, `metricsSummary.outputTokens`, `metricsSummary.totalTokens` |
| `cached_input_tokens` | `responses.jsonl` | `metricsSummary.cachedInputTokens` |
| `cached_read_tokens` | `responses.jsonl` | `metricsSummary.cacheReadInputTokens` |
| `reserved_tokens` | `responses.jsonl` | `metricsSummary.reservedTokens` |
| `reasoning_tokens` | `responses.jsonl` | `usage.reasoningTokens` |
| `model_duration_ms` | `responses.jsonl` | `metricsSummary.modelDurationMs` |
| `tool_duration_ms` | `responses.jsonl` | `metricsSummary.toolDurationMs` |
| `duration_ms` | `responses.jsonl` | `metricsSummary.totalDurationMs` |
| `duration_sec` | derived | `duration_ms / 1000.0` |
| `model_calls`, `tool_calls`, `function_calls`, `mcp_tool_calls`, `steps` | `responses.jsonl` | `metricsSummary.modelCalls`, `metricsSummary.toolCalls`, `metricsSummary.functionCalls`, `metricsSummary.mcpToolCalls`, `metricsSummary.steps` |
| `evaluation_method` | `evals.jsonl` | `evaluationMethod` |
| `evaluation_status` | `evals.jsonl` | `status` |
| `evaluation_input_tokens`, `evaluation_output_tokens`, `evaluation_duration_ms` | `evals.jsonl` | `evaluationInputTokens`, `evaluationOutputTokens`, `evaluationDurationMs` |
| `judge_count`, `judge_error_count` | `evals.jsonl` | `judgeCount`, `judgeErrorCount` |

The command must use exactly these source paths. Implementers must not introduce alternative sources without updating this table.

`duration_ms` deliberately uses `metricsSummary.totalDurationMs` as the canonical source. Other candidate fields (`strategyDurationMs`, `benchmarkDurationMsEstimated`) are not equivalent and must not be silently substituted.

### 7.1 `trial_metrics.csv`

`trial_metrics.csv` must contain one row per planned trial, even if the trial has no response or evaluation yet.

Required columns:

```text
experimentId
dataset_id
dataset_version
trialId
instanceId
taskId
taskTags
provider
modelId
modelName
strategy
format
configuration
repeatIndex

response_present
execution_status
evaluation_present
evaluation_status
evaluation_method
evaluation_method_consistent

input_tokens
output_tokens
total_tokens
cached_input_tokens
cached_read_tokens
reserved_tokens
reasoning_tokens

duration_ms
duration_sec
model_duration_ms
tool_duration_ms

model_calls
tool_calls
function_calls
mcp_tool_calls
steps

primary_metric_name
primary_success
primary_score

evaluation_input_tokens
evaluation_output_tokens
evaluation_duration_ms
judge_count
judge_error_count
judge_agreement_mean
judge_unanimous

trace_available
execution_trace_available
eval_trace_available
raw_response_available
tool_calls_observable
native_mcp_observable
server_mcp_observable
usage_observable
error_observable

error_message
response_excerpt
```

### 7.2 `configuration` field

The `configuration` field is derived from `strategy` and `format` using:

```text
configuration = f"{strategy}_{format}"   if both strategy and format are present
configuration = strategy                 if format is null or empty
configuration = "unknown"                if strategy is null or empty
                                         (and the command must warn)
```

`format` is taken verbatim from the trial. No normalization is applied (e.g., `code`, `json`, `html`, `xml` are all kept as-is).

Examples (using actual values observed in current artifacts):

```text
inline_code           (RepoQA inline trials)
inline_json
inline_html
local_function_json
local_function_code
local_mcp_json
local_mcp_code
remote_mcp_json
```

### 7.3 Tags

If a trial has multiple tags, `taskTags` must be serialized as a pipe-separated string in CSV (for example: `code|repository|retrieval`). The pipe character is used instead of comma because individual tags may legitimately contain commas in some datasets, and pipe is reserved.

If any tag contains a `|` character, the command must fail with a clear error pointing at the offending trial. Tag normalization is the responsibility of the dataset pipeline, not the metrics command.

In JSON outputs (e.g., `summary.json`, `metrics-manifest.json`), `taskTags` must remain as a JSON array.

### 7.4 Naming policy

Columns and field identifiers in CSV outputs follow a hybrid convention:

- Identifier fields that already exist in lifecycle artifacts (`trialId`, `instanceId`, `taskId`, `taskTags`, `experimentId`, `modelId`, `modelName`, `repeatIndex`) are preserved in their original camelCase to ease cross-referencing.
- Derived or computed fields (success rates, token counts, observability flags, status normalizations) use snake_case.

The mapping table in §7.0 is normative for which fields fall in which category.

### 7.5 Computation conventions

The following conventions apply to all metric computations and outputs. They exist to make P2 (Determinism) operational.

#### 7.5.1 Row ordering

All CSV outputs must be written with a deterministic row order:

- `trial_metrics.csv`: sorted by `(dataset_id, experimentId, trialId)`.
- `aggregate_metrics.csv` and each dimension file: sorted by the tuple of group field values, with stable secondary ordering by axis name when the file contains a `robustness_axis` column.
- `failure_cases.csv`: sorted by `(dataset_id, experimentId, trialId)`.
- `dimension_summary.csv`: sorted by `(dimension, group_key, metric)`.

Within each sort key, ties must be broken using lexicographic ordering of the next non-null column.

#### 7.5.2 CSV dialect

- Unix newlines (`\n`).
- No BOM.
- UTF-8 encoding.
- `null` values are written as empty cells.
- Booleans serialize to `true` / `false` (lowercase).
- Floats: at most 6 significant digits, no scientific notation unless absolute value < 1e-4.
- No trailing whitespace.

#### 7.5.3 Percentiles

All percentile metrics (e.g., `total_tokens_p95`, `duration_sec_p95`) must use linear interpolation, equivalent to `numpy.percentile(arr, q, method="linear")`. When fewer than two values are available, percentile metrics must be `null`.

#### 7.5.4 Standard deviation

All standard deviation metrics use the sample estimator (`ddof=1`), equivalent to `numpy.std(arr, ddof=1)`. When fewer than two values are available, stddev must be `null`.

#### 7.5.5 Means with empty input

When a mean is computed over zero values, the result must be `null`, not zero or NaN.

#### 7.5.6 `response_excerpt`

`response_excerpt` is derived from `responses.jsonl.response`:

```text
response_excerpt = response[:280]                if len(response) <= 280
response_excerpt = response[:280] + "…"          otherwise
response_excerpt = null                          if response is missing or null
```

The truncation length is fixed at 280 characters so that `failure_cases.csv` remains human-scannable.

### 7.6 Present / absent decision rules

The following columns reflect artifact presence rather than status:

```text
response_present     = a row with this trialId exists in responses.jsonl
evaluation_present   = a row with this trialId exists in evals.jsonl
```

Both are independent of `status`. A trial whose response has `status = error` still has `response_present = true`. A trial whose evaluation has `status = skipped` still has `evaluation_present = true`.

When `response_present = false`, all execution-derived columns (tokens, durations, calls, error_message, response_excerpt) must be empty/null. When `evaluation_present = false`, all evaluation-derived columns must be empty/null.

---

## 8. Core Dimension: Effectiveness

### 8.1 Importance

Effectiveness indicates whether the strategy produced a useful or correct output according to the evaluation method used by the dataset.

It adapts HELM's accuracy dimension to LLMContextBench's heterogeneous evaluation methods.

### 8.2 What it indicates

It indicates the primary quality outcome of a trial.

The common interface is:

```text
primary_metric_name
primary_success
primary_score
```

### 8.3 Evaluation rules

#### For `evaluation_method = judge`

Use the aggregate evaluation outcome from `evals.jsonl`.

Expected fields:

```text
outcome.correctness.rating
outcome.completeness.rating
```

Rating mapping:

```text
meets   -> 1.0
partial -> 0.5
misses  -> 0.0
```

Any other rating value (including `null`) must map to `null`, and the command must emit a single warning per unknown rating value seen (not per occurrence).

Rules:

```text
primary_metric_name = "judge_meets"

primary_success =
  correctness.rating == "meets"
  AND completeness.rating == "meets"

primary_score =
  mean(score(correctness.rating), score(completeness.rating))
```

#### For `evaluation_method = repoqa-scorer`

Use the persisted deterministic scorer output from `evals.jsonl`.

Expected fields:

```text
details.outcome.passed
details.repoqa.bestSimilarScore
```

Rules:

```text
primary_metric_name = "pass"
primary_success = details.outcome.passed
primary_score = details.repoqa.bestSimilarScore
```

The command must not re-run the RepoQA scorer.

#### For unknown evaluation methods

Rules:

```text
primary_metric_name = null
primary_success = null
primary_score = null
```

The command should warn but continue.

#### Evaluation method consistency

Each trial has a planned evaluation method (`trials.jsonl.validationType`) and, if evaluated, an actual evaluation method (`evals.jsonl.evaluationMethod`). When both are present and differ, the command must:

- trust `evals.jsonl.evaluationMethod` as the authoritative value for `evaluation_method`;
- emit a warning naming the affected `trialId` and both values;
- set a per-trial boolean column `evaluation_method_consistent = false` in `trial_metrics.csv`.

When only one of the two is present, `evaluation_method_consistent` must be `true`. When neither is present, it must be `null`.

### 8.4 Aggregated metrics

For each group:

```text
n_trials
n_evaluated
primary_metric_name
primary_success_count
primary_success_rate
primary_score_mean
primary_score_median
primary_score_stddev
```

If a group contains multiple `primary_metric_name` values, set:

```text
primary_metric_name      = "mixed"
primary_score_mean       = null
primary_score_median     = null
primary_score_stddev     = null
```

`primary_success_count` and `primary_success_rate` may still be reported for mixed groups because `primary_success` is a comparable boolean across methods. Score-based aggregates are not comparable across methods (judge mean-of-rating-scores vs. RepoQA similarity), so they must be `null`.

### 8.5 Output file

```text
metrics/dimensions/effectiveness.csv
```

Required columns:

```text
group_fields...
n_trials
n_evaluated
primary_metric_name
primary_success_count
primary_success_rate
primary_score_mean
primary_score_median
primary_score_stddev
```

### 8.6 Interpretation

High `primary_success_rate` indicates strong task effectiveness according to the dataset's primary evaluation method.

High `primary_score_mean` with moderate `primary_success_rate` may indicate partial quality: the strategy often gets close but fails strict success.

Effectiveness must not be interpreted alone. It should be interpreted together with efficiency, stability, evaluation reliability, and observability.

---

## 9. Core Dimension: Efficiency

### 9.1 Importance

Efficiency indicates the operational cost of obtaining benchmark results.

It adapts HELM's efficiency dimension to context provisioning strategies.

### 9.2 What it indicates

Efficiency captures:

```text
token cost
latency cost
interaction cost
```

### 9.3 Trial-level data

From responses and traces:

```text
input_tokens
output_tokens
total_tokens
cached_input_tokens
cached_read_tokens
reserved_tokens
reasoning_tokens

duration_ms
duration_sec
model_duration_ms
tool_duration_ms

model_calls
tool_calls
function_calls
mcp_tool_calls
steps
```

`reasoning_tokens` is populated from `responses.jsonl.usage.reasoningTokens` and is null when the provider does not report it.

### 9.4 Aggregated metrics

For each group:

```text
input_tokens_sum
output_tokens_sum
total_tokens_sum

input_tokens_mean
output_tokens_mean
total_tokens_mean

total_tokens_median
total_tokens_p95

cached_input_tokens_sum
cached_read_tokens_sum

duration_sec_mean
duration_sec_median
duration_sec_p95
duration_sec_sum

model_duration_ms_mean
tool_duration_ms_mean

model_calls_mean
tool_calls_mean
function_calls_mean
mcp_tool_calls_mean
steps_mean
total_calls_sum

tokens_per_primary_success
duration_sec_per_primary_success
calls_per_primary_success
```

Derived rules:

```text
tokens_per_primary_success =
  total_tokens_sum / primary_success_count

duration_sec_per_primary_success =
  duration_sec_sum / primary_success_count

calls_per_primary_success =
  total_calls_sum / primary_success_count

total_calls =
  model_calls + tool_calls + function_calls + mcp_tool_calls
```

`duration_sec_sum` is the sum of non-null `duration_sec` values in the group.

`total_calls_sum` is the sum of per-trial `total_calls` values where at least one call-count component is non-null. Missing call-count components within an otherwise observable call-count row are treated as zero for this sum.

If `primary_success_count == 0`, per-success metrics must be `null`.

### 9.5 Output file

```text
metrics/dimensions/efficiency.csv
```

Required columns:

```text
group_fields...
n_trials
n_responses
primary_success_count

total_tokens_mean
total_tokens_median
total_tokens_p95
total_tokens_sum
tokens_per_primary_success

duration_sec_mean
duration_sec_median
duration_sec_p95
duration_sec_sum
duration_sec_per_primary_success

model_calls_mean
tool_calls_mean
function_calls_mean
mcp_tool_calls_mean
steps_mean
total_calls_sum
calls_per_primary_success
```

### 9.6 Interpretation

A strategy is more efficient when it uses fewer tokens, lower latency, and fewer calls for the same or better effectiveness.

The most useful efficiency metrics are normalized by success, especially:

```text
tokens_per_primary_success
duration_sec_per_primary_success
calls_per_primary_success
```

Execution tokens and evaluation tokens must be kept separate. Primary cost metrics must reflect the response generation phase, not the later evaluation phase.

---

## 10. Core Dimension: Robustness / Stability

### 10.1 Importance

Robustness / Stability indicates whether a strategy behaves consistently across tasks, instances, formats, models, and repetitions.

It adapts HELM's robustness dimension to LLMContextBench's experimental factors.

### 10.2 What it indicates

It indicates sensitivity to benchmark factors.

A strategy with high average effectiveness but large variation across tasks may be less dependable than a slightly weaker but more stable strategy.

### 10.3 Evaluation approach

The first implementation should compute stability from observed variation. It does not need to implement perturbation-based robustness tests.

Compute variation over the following axes when enough data exists:

```text
task
instance
repeat
model
format
```

Required robustness axes:

```text
task:
  group by dataset_id, configuration, taskId

instance:
  group by dataset_id, configuration, instanceId

repeat:
  group by dataset_id, configuration, taskId, instanceId, repeatIndex

model:
  group by dataset_id, configuration, modelId

format:
  group by dataset_id, strategy, format
```

### 10.4 Aggregated metrics

For each high-level group and robustness axis:

```text
robustness_axis
n_groups

primary_success_rate_mean
primary_success_rate_min
primary_success_rate_max
primary_success_rate_range

primary_score_mean
primary_score_stddev

duration_sec_stddev
total_tokens_stddev
```

Rules:

```text
primary_success_rate_range =
  primary_success_rate_max - primary_success_rate_min
```

If there are fewer than two subgroups for an axis, variation metrics must be `null`.

### 10.5 Output file

```text
metrics/dimensions/robustness.csv
```

Required columns:

```text
group_fields_without_axis...
robustness_axis
n_groups

primary_success_rate_mean
primary_success_rate_min
primary_success_rate_max
primary_success_rate_range

primary_score_mean
primary_score_stddev

duration_sec_stddev
total_tokens_stddev
```

### 10.6 Interpretation

Low variation indicates stability.

High variation indicates sensitivity to tasks, instances, models, formats, or repetitions.

A strategy may have strong average effectiveness but poor stability. This should be interpreted as a trade-off rather than a simple failure.

---

## 11. Core Dimension: Evaluation Reliability

### 11.1 Importance

Evaluation Reliability indicates whether the evaluation process itself is complete, consistent, and trustworthy.

This dimension is necessary because LLMContextBench may use LLM-as-judge, deterministic scorers, exact match, tests, or other evaluation methods.

### 11.2 What it indicates

It indicates whether effectiveness results should be trusted.

It measures:

```text
evaluation coverage
evaluation errors
skipped evaluations
judge failures
judge agreement
evaluation cost
```

### 11.3 Trial-level data

From `evals.jsonl` and `judge_votes.jsonl`:

```text
evaluation_present
evaluation_status
evaluation_method
evaluation_input_tokens
evaluation_output_tokens
evaluation_duration_ms
judge_count
judge_error_count
judge_agreement_mean
judge_unanimous
```

### 11.4 Judge agreement

For `evaluation_method = judge`, compute agreement from available aggregate outcome fields and/or per-judge votes. Current artifacts may encode `outcome.correctness.agreement` and `outcome.completeness.agreement` as booleans or numeric `0`/`1` values. The metrics command must normalize both representations to booleans before computing agreement.

#### Trial-level `judge_agreement_mean`

```text
judge_agreement_mean =
  mean(int(correctness.agreement), int(completeness.agreement))
```

This computation applies only when both `outcome.correctness.agreement` and `outcome.completeness.agreement` are non-null booleans or numeric `0`/`1` values. Otherwise `judge_agreement_mean = null`. The result is in `{0.0, 0.5, 1.0}`.

#### Trial-level `judge_unanimous`

Definition: a trial is unanimous when all non-error judges agree on both criteria.

Computation rules, in priority order:

1. If `judge_votes.jsonl` is available and the trial has at least two non-error votes:
   - `judge_unanimous = true` iff all non-error votes share the same `criterias.correctness.rating` AND the same `criterias.completeness.rating`.
   - `judge_unanimous = false` otherwise.
2. If `judge_votes.jsonl` is not available but aggregate `outcome.correctness.agreement` and `outcome.completeness.agreement` are both non-null booleans or numeric `0`/`1` values:
   - `judge_unanimous = (correctness.agreement == true) AND (completeness.agreement == true)`.
3. Otherwise:
   - `judge_unanimous = null`.

A trial with fewer than two non-error votes (e.g., single judge or all errors) must have `judge_unanimous = null`, since unanimity is not meaningful at N<2.

If the evaluation method is not `judge`, all judge-specific fields (`judge_count`, `judge_error_count`, `judge_agreement_mean`, `judge_unanimous`) must be `null`.

### 11.5 Aggregated metrics

For each group:

```text
evaluation_coverage_rate
evaluation_success_rate
evaluation_error_rate
evaluation_skipped_rate
n_evaluation_status_other

judge_count_mean
judge_error_rate
judge_agreement_mean
judge_unanimity_rate

evaluation_tokens_mean
evaluation_duration_sec_median
```

Definitions:

```text
evaluation_coverage_rate =
  n_trials_with_evaluation_present / n_trials

evaluation_success_rate =
  n_evaluation_status_in_{evaluated, partial} / n_trials

evaluation_error_rate =
  n_evaluation_status_error / n_trials

evaluation_skipped_rate =
  n_evaluation_status_skipped / n_trials

judge_error_rate =
  total_judge_errors / total_judge_votes
```

The recognized values of `evaluation_status` are:

```text
evaluated   - evaluation completed normally
partial     - evaluation completed but partial outcome only (e.g. one criterion ok)
error       - evaluation failed
skipped     - evaluation was skipped intentionally
```

`partial` is folded into the success bucket because it represents a completed evaluation with a usable outcome. Any other status value must be counted toward `n_evaluation_status_other` and warned about; the coverage and success rates above do not include it.

`evaluation_coverage_rate` counts any row present in `evals.jsonl` regardless of its status, including `error` and `skipped`. It measures whether the evaluation phase ran for the trial at all, not whether it succeeded.

### 11.6 Output file

```text
metrics/dimensions/evaluation_reliability.csv
```

Required columns:

```text
group_fields...
evaluation_method
n_trials
n_evaluated

evaluation_coverage_rate
evaluation_success_rate
evaluation_error_rate
evaluation_skipped_rate
n_evaluation_status_other

judge_count_mean
judge_error_rate
judge_agreement_mean
judge_unanimity_rate

evaluation_tokens_mean
evaluation_duration_sec_median
```

### 11.7 Interpretation

High evaluation reliability means that most responses were evaluated, few evaluations failed, and judges or scorers behaved consistently.

Low evaluation coverage or high judge disagreement means effectiveness results should be interpreted with caution.

---

## 12. Core Dimension: Observability

### 12.1 Importance

Observability indicates whether benchmark behavior can be audited, explained, and reproduced.

This dimension is especially important for context provisioning strategies because different strategies expose different levels of runtime detail.

### 12.2 What it indicates

It indicates the availability of artifacts required for inspection:

```text
execution traces
evaluation traces
raw responses
usage metadata
tool calls
MCP traces
errors
```

### 12.3 Trial-level data

From `manifest.json`, `responses.jsonl`, `evals.jsonl`, and trace files:

```text
trace_available
execution_trace_available
eval_trace_available
raw_response_available
tool_calls_observable
native_mcp_observable
server_mcp_observable
usage_observable
error_observable
```

### 12.4 Detection rules

The command must consider an execution trace available when either:

```text
responses.jsonl[trialId].traceRef is non-empty
OR <experimentDir>/traces/executions/<trialId>.json exists
```

The command must consider an evaluation trace available when either:

```text
evals.jsonl[trialId].traceRef is non-empty
OR <experimentDir>/traces/evals/<trialId>.json exists
```

(The previous draft of this spec referenced `response.trace` and `eval.evaluationTrace`. Those fields are not produced by the current pipeline — `response` is a raw model output string — and must not be used.)

The command must consider usage observable when at least one of `metricsSummary.inputTokens`, `metricsSummary.outputTokens`, or `metricsSummary.totalTokens` is a non-null number for that trial.

The command must consider tool calls observable when `metricsSummary.toolCalls`, `metricsSummary.functionCalls`, or `metricsSummary.mcpToolCalls` is a non-null number, OR when the execution trace contains either:

```text
trace.toolCalls as a non-empty list
OR trace.aiTrace.events[] with type or name in {"mcp.tool_call", "mcp.tool_result"}
```

The command must consider native MCP observable when `metricsSummary.mcpToolCalls > 0` for a trial with `strategy in {local_mcp, remote_mcp}`, OR when the execution trace contains:

```text
trace.nativeMcp as a non-empty object
```

The command must consider server MCP observable when the execution trace contains:

```text
trace.serverMcp as a non-empty list
```

When traces are unavailable, `server_mcp_observable` must be `null`, not `false`, to distinguish "absent" from "unobservable".

### 12.5 Aggregated metrics

For each group:

```text
trace_coverage_rate
execution_trace_coverage_rate
eval_trace_coverage_rate
raw_response_coverage_rate

tool_call_observability_rate
native_mcp_observability_rate
server_mcp_observability_rate
usage_observability_rate
error_observability_rate
```

### 12.6 Output file

```text
metrics/dimensions/observability.csv
```

Required columns:

```text
group_fields...
n_trials

trace_coverage_rate
execution_trace_coverage_rate
eval_trace_coverage_rate
raw_response_coverage_rate

tool_call_observability_rate
native_mcp_observability_rate
server_mcp_observability_rate
usage_observability_rate
error_observability_rate
```

### 12.7 Interpretation

High observability means the benchmark run can be audited and explained.

Low observability does not necessarily invalidate a strategy, but it reduces confidence in diagnosing why the strategy behaved as it did.

This dimension is especially important when comparing local and remote strategies.

---

## 13. `aggregate_metrics.csv`

`aggregate_metrics.csv` must merge the main metrics from all five dimensions using the requested group fields.

Default group:

```text
dataset_id,configuration
```

Required columns:

```text
group_fields...

n_trials
n_responses
n_evaluated

primary_metric_name
primary_success_rate
primary_score_mean
primary_score_stddev

total_tokens_mean
total_tokens_median
total_tokens_p95
tokens_per_primary_success

duration_sec_median
duration_sec_p95
duration_sec_per_primary_success

model_calls_mean
tool_calls_mean
function_calls_mean
mcp_tool_calls_mean
calls_per_primary_success

primary_success_rate_range_by_task
primary_success_rate_range_by_instance
primary_success_rate_range_by_repeat
primary_success_rate_range_by_model
primary_success_rate_range_by_format

evaluation_coverage_rate
evaluation_success_rate
evaluation_error_rate
judge_agreement_mean
judge_unanimity_rate

trace_coverage_rate
tool_call_observability_rate
usage_observability_rate
```

`aggregate_metrics.csv` must surface a `primary_success_rate_range_by_<axis>` column for every robustness axis defined in §10.3. When an axis has fewer than two subgroups within a row's high-level group, the corresponding range column must be empty.

Effectiveness score-spread metrics (`primary_score_stddev`) appear once. Score-spread per robustness axis stays in `robustness.csv` and is not duplicated into the aggregate file.

---

## 14. `dimension_summary.csv`

`dimension_summary.csv` must provide a compact long-form view of the five dimensions.

Required columns:

```text
dimension
group_key
group_fields...
metric
value
```

`group_key` is a single string composed of the group field values joined by `|`, used for compact display and to key rows uniquely. The individual `group_fields` columns expand to whatever `--group-by` selected (default: `dataset_id`, `configuration`). This file's columns therefore vary with `--group-by`, and consumers must read the header rather than assume fixed columns.

Example rows:

```text
effectiveness,ctxbench/lattes:inline_json,ctxbench/lattes,inline_json,primary_success_rate,0.458
efficiency,ctxbench/lattes:inline_json,ctxbench/lattes,inline_json,tokens_per_primary_success,153900
robustness,ctxbench/lattes:inline_json,ctxbench/lattes,inline_json,primary_success_rate_range_by_task,0.75
evaluation_reliability,ctxbench/lattes:inline_json,ctxbench/lattes,inline_json,judge_unanimity_rate,0.62
observability,ctxbench/lattes:inline_json,ctxbench/lattes,inline_json,trace_coverage_rate,1.00
```

This file is useful for dashboards and quick comparison across dimensions.

---

## 15. `summary.json`

`summary.json` must provide a compact machine-readable overview.

Example:

```json
{
  "schemaVersion": "1.0",
  "experiments": 2,
  "datasets": ["ctxbench/lattes", "ctxbench/repoqa"],
  "n_trials": 1380,
  "n_responses": 1380,
  "n_evaluated": 1380,
  "primary_metric_name": "mixed",
  "primary_success_rate": 0.51,
  "total_tokens_sum": 52000000,
  "duration_sec_median": 4.5,
  "evaluation_success_rate": 0.98,
  "trace_coverage_rate": 1.0
}
```

If multiple primary metrics are present, `primary_metric_name` must be `"mixed"`.

---

## 16. `metrics-manifest.json`

`metrics-manifest.json` must record provenance.

Example:

```json
{
  "schemaVersion": "1.0",
  "generatedAt": "2026-06-04T12:00:00Z",
  "command": "llmctxbench metrics outputs/lattes outputs/repoqa --output outputs/paper_metrics",
  "metricFramework": {
    "inspiredBy": "HELM",
    "coreDimensions": [
      "effectiveness",
      "efficiency",
      "robustness",
      "evaluation_reliability",
      "observability"
    ]
  },
  "selectors": {
    "model": [],
    "provider": [],
    "instance": [],
    "task": [],
    "strategy": [],
    "format": [],
    "repetition": [],
    "trial": [],
    "executionStatus": [],
    "evaluationStatus": [],
    "notModel": [],
    "notProvider": [],
    "notInstance": [],
    "notTask": [],
    "notStrategy": [],
    "notFormat": [],
    "notRepetition": [],
    "notExecutionStatus": [],
    "notEvaluationStatus": []
  },
  "groupBy": ["dataset_id", "configuration"],
  "inputs": [
    {
      "experimentDir": "outputs/lattes",
      "experimentId": "lattes_baseline",
      "datasetId": "ctxbench/lattes",
      "datasetVersion": "2026-04-28",
      "datasetContentHash": "sha256:…",
      "datasetResolvedRevision": null,
      "trials": 1200,
      "responses": 1200,
      "evaluations": 1200,
      "judgeVotes": 3600
    },
    {
      "experimentDir": "outputs/repoqa",
      "experimentId": "repoqa_baseline",
      "datasetId": "ctxbench/repoqa",
      "datasetVersion": "2026-05-23",
      "datasetContentHash": null,
      "datasetResolvedRevision": null,
      "trials": 180,
      "responses": 180,
      "evaluations": 180,
      "judgeVotes": 0
    }
  ],
  "outputs": [
    "trial_metrics.csv",
    "aggregate_metrics.csv",
    "dimension_summary.csv",
    "summary.json",
    "failure_cases.csv",
    "dimensions/effectiveness.csv",
    "dimensions/efficiency.csv",
    "dimensions/robustness.csv",
    "dimensions/evaluation_reliability.csv",
    "dimensions/observability.csv"
  ]
}
```

The `selectors` block must serialize the parsed selector values that were actually applied, not the raw command-line strings. This preserves filter provenance independent of the user's shell quoting and working directory.

`groupBy` records the resolved grouping fields (default or `--group-by`) so downstream tools can reconstruct the file layouts.

`datasetContentHash` and `datasetResolvedRevision` are copied from each input's `manifest.json` `dataset` block. They may be `null` when the dataset pipeline did not record them.

---

## 17. `failure_cases.csv`

`failure_cases.csv` must include rows that require inspection.

Include a trial when any of the following is true:

```text
response_present == true AND execution_status != success
OR evaluation_status in error, skipped
OR primary_success == false
OR primary_success is null and evaluation_present == true
```

Planned-only rows (`response_present = false`) must not be included solely because `execution_status` is null. They may still be included if another rule applies.

Required columns:

```text
dataset_id
experimentId
trialId
taskId
instanceId
modelId
configuration
execution_status
evaluation_status
evaluation_method
primary_metric_name
primary_success
primary_score
error_message
response_excerpt
```

---

## 18. Implementation Plan

### 18.1 Add command handler

Create:

```text
src/ctxbench/commands/metrics.py
```

### 18.2 Add metrics package

Create:

```text
src/ctxbench/metrics/
  __init__.py
  io.py
  trial_rows.py
  primary.py
  aggregate.py
  writers.py
  dimensions/
    __init__.py
    effectiveness.py
    efficiency.py
    robustness.py
    evaluation_reliability.py
    observability.py
```

### 18.3 Update CLI

Update:

```text
src/ctxbench/cli.py
```

Add a `metrics` subcommand that calls `metrics_command`. Wire it using the same argparse-subparser + `set_defaults(func=...)` pattern that `plan`, `execute`, `eval`, and `export` already use.

### 18.3.1 Required helper reuse

The metrics command must reuse, not reimplement, the following existing utilities. Reinventing any of these without justification is out of scope:

- **JSONL I/O** — `src/ctxbench/util/jsonl.py::read_jsonl`. Stream lifecycle artifacts through this helper rather than custom open/loads loops.
- **Selector model** — `src/ctxbench/benchmark/selectors.py::RunSelector`, `matches_run_result`. Apply shared selectors to the joined trial-row representation with `status` populated from `execution_status`; apply metrics-specific evaluation status filters separately.
- **TrialId indexing** — pattern from `src/ctxbench/commands/export.py::_build_eval_index` and `_build_votes_index`. The metrics command must index responses, evals, and votes by `trialId` for O(1) joins.
- **CSV writer** — pattern from `src/ctxbench/commands/export.py::_write_csv`.
- **Phase logging** — `src/ctxbench/util/logging.py::PhaseLogger`, with phases such as `discover_inputs`, `load_artifacts`, `apply_selectors`, `build_trial_rows`, `compute_dimensions`, `write_outputs`.
- **Sibling-file discovery** — the pattern in `src/ctxbench/commands/export.py` where source artifacts are discovered relative to the input directory. The path helpers in `src/ctxbench/benchmark/paths.py` require an `Experiment` model and are not appropriate for this standalone command.

### 18.4 Internal flow

The command should:

```text
1. Parse CLI args.
2. Resolve input experiment directories.
3. Load trials.jsonl for each directory.
4. Load optional responses.jsonl, evals.jsonl, judge_votes.jsonl.
5. Build indexes by trialId.
6. Build one trial_metrics row for every planned trial.
7. Apply selectors.
8. Compute effectiveness dimension.
9. Compute efficiency dimension.
10. Compute robustness/stability dimension.
11. Compute evaluation reliability dimension.
12. Compute observability dimension.
13. Merge selected metrics into aggregate_metrics.csv.
14. Write dimension_summary.csv.
15. Write summary.json.
16. Write failure_cases.csv.
17. Write metrics-manifest.json.
```

---

## 19. Acceptance Criteria

### AC1. Metrics from planned-only experiment

Given an experiment directory with `trials.jsonl` and no `responses.jsonl`, `llmctxbench metrics` must generate the full output set listed in §6, including `metrics-manifest.json`, `dimension_summary.csv`, `failure_cases.csv`, and every file under `dimensions/`. Dimension files that have no data rows must still be written as header-only CSVs. The output layout must not vary with the level of artifact completeness.

All rows in `trial_metrics.csv` must have `response_present = false`, no effectiveness values, and pending execution reflected in aggregate metrics.

### AC2. Metrics from executed but unevaluated experiment

Given `trials.jsonl` and `responses.jsonl` but no `evals.jsonl`, the command must generate efficiency and observability metrics. Effectiveness and evaluation reliability fields that depend on evaluation must be empty/null.

### AC3. Judge evaluation support

Given `evals.jsonl` with `evaluationMethod = judge`, the command must compute:

```text
primary_metric_name = judge_meets
primary_success
primary_score
judge_agreement_mean
judge_unanimity_rate when votes are available
```

### AC4. RepoQA scorer support

Given `evals.jsonl` with `evaluationMethod = repoqa-scorer`, the command must compute:

```text
primary_metric_name = pass
primary_success = details.outcome.passed
primary_score = details.repoqa.bestSimilarScore
```

It must not re-run the RepoQA scorer.

### AC5. Multiple experiment support

Given two experiment directories, the command must merge all trials into one `trial_metrics.csv` and compute aggregate metrics across both.

### AC6. Group-by support

Given `--group-by dataset_id,configuration,modelId`, `aggregate_metrics.csv` and the non-robustness dimension files (`effectiveness.csv`, `efficiency.csv`, `evaluation_reliability.csv`, `observability.csv`) must aggregate by those fields.

`robustness.csv` uses `--group-by` only for its high-level group fields. The robustness axes themselves (§10.3) remain fixed (`task`, `instance`, `repeat`, `model`, `format`) regardless of `--group-by`, because they exist to measure variation along those experimental factors. Implementations must not re-derive the axes from `--group-by`.

### AC7. Determinism

Running the command twice over the same artifacts must produce identical CSV metric values.

### AC8. Missing values

If a metric cannot be computed, the CSV cell must be empty and the JSON value must be `null`.

### AC9. No external calls

The command must not call LLM providers, MCP servers, HTTP endpoints, or deterministic scorer subprocesses.

### AC10. No plot-specific outputs

The command must not generate a `plot_data/` directory or any plot-specific CSV files.

---

## 20. Non-goals for Initial Version

The initial implementation must not include:

```text
dataset-specific metric providers
Lattes-specific tables
RepoQA-specific tables
plot_data directory
automatic figure generation
paper-specific table generation
report.md generation
HTML/PDF reports
statistical significance tests
calibration metrics
fairness metrics
bias metrics
toxicity metrics
safety metrics
human annotation workflows
```

These can be added later after the five core dimensions are stable.

---

## 21. Expected Value

After this feature, notebooks and paper scripts should consume:

```text
metrics/trial_metrics.csv
metrics/aggregate_metrics.csv
metrics/dimensions/*.csv
metrics/dimension_summary.csv
```

instead of recalculating benchmark metrics from raw lifecycle artifacts.

The expected result is:

```text
benchmark execution artifacts
  -> llmctxbench metrics
  -> canonical metric artifacts
  -> notebooks/scripts generate figures and paper tables
```

This makes the evaluation workflow more reproducible, more aligned with a multi-metric evaluation philosophy, and more suitable for comparing context provisioning strategies across heterogeneous datasets.
