# Metrics reference

`llmctxbench metrics <run>` (API: `Run.metrics()`) writes metric tables under `<run>/metrics/`
(or `--output`). The rules behind them are in
[metrics design](../../architecture/metrics-design.md).

**Provenance classes.** Each value is `reported` (returned by a provider or authoritative
runtime), `measured` (measured by the tool), `derived` (computed from recorded values),
`estimated` (approximated) or `unavailable` (empty cell). The **Class** column below gives the
class of each column; "per row" means a companion provenance column states it for each row.
An empty cell means the value is unavailable — never zero.

## Benchmark runs

Files: `metrics-manifest.json`, `trial_metrics.csv`, `aggregate_metrics.csv`,
`dimension_summary.csv`, `summary.json`, `failure_cases.csv`, and
`dimensions/{effectiveness,efficiency,robustness,evaluation_reliability,observability}.csv`.
All files are written even for partial runs, with headers when they have no rows.

### `trial_metrics.csv` — one row per planned trial

| Columns | Meaning | Class |
|---|---|---|
| `experimentId`, `dataset_id`, `dataset_version`, `trialId`, `instanceId`, `taskId`, `taskTags`, `provider`, `modelId`, `modelName`, `strategy`, `representation`, `surface`, `configurationId`, `repeatIndex` | Trial identity, from the plan. | — |
| `response_present`, `evaluation_present` | A response / evaluation row exists for the trial (independent of status). | derived |
| `execution_status`, `evaluation_status` | Status of the response and of the evaluation. | — |
| `evaluation_method`, `evaluation_method_consistent` | Actual evaluation method; `false` when it differs from the planned one. | derived |
| `input_tokens`, `output_tokens`, `total_tokens` | Generation token usage. | reported or estimated, per row (`total_tokens_provenance`) |
| `known_total_tokens`, `total_tokens_provenance`, `usage_completeness` | Known partial total when the total is incomplete; provenance of `total_tokens`; completeness of usage reporting. | derived |
| `cached_input_tokens`, `cached_read_tokens`, `reserved_tokens`, `reasoning_tokens` | Provider-specific token detail; empty when the provider does not report it. | reported |
| `duration_ms`, `duration_provenance`, `duration_sec` | Execution duration (`metricsSummary.totalDurationMs`) and its provenance. | measured, per row |
| `model_duration_ms`, `tool_duration_ms` | Time in model calls and in tool calls. | measured |
| `model_calls`, `model_attempts`, `failed_model_attempts` | Model calls, provider attempts including retries, and failed attempts. | measured |
| `model_attempt_duration_ms`, `model_attempt_duration_provenance` | Time across provider attempts and its provenance. | measured, per row |
| `tool_calls`, `function_calls`, `mcp_tool_calls`, `steps` | Tool activity and loop steps. | measured |
| `primary_metric_name`, `primary_success`, `primary_score` | Normalised effectiveness: `judge_meets` for judges, `pass` for the RepoQA scorer. | derived |
| `evaluation_input_tokens`, `evaluation_output_tokens`, `evaluation_duration_ms` | Judge usage and time; never mixed with generation usage. | reported / measured |
| `judge_count`, `judge_error_count`, `judge_agreement_mean`, `judge_unanimous` | Judge votes, failed votes, mean agreement over the two criteria, unanimity (needs ≥ 2 votes). | derived |
| `trace_available`, `execution_trace_available`, `eval_trace_available`, `raw_response_available` | Whether traces and the raw response exist. | derived |
| `tool_calls_observable`, `native_mcp_observable`, `server_mcp_observable`, `usage_observable`, `error_observable` | Whether each kind of activity was observable; empty when traces are absent. | derived |
| `error_message`, `response_excerpt` | Error text and the first 280 characters of the response. | — |

### Dimension files and `aggregate_metrics.csv` — one row per group

Rows are grouped by `--group-by` (default `dataset_id,configurationId`; allowed fields:
`configurationId`, `dataset_id`, `dataset_version`, `evaluation_method`, `experimentId`,
`instanceId`, `modelId`, `modelName`, `primary_metric_name`, `provider`, `repeatIndex`,
`representation`, `strategy`, `surface`, `taskId`, `taskTags`). All values are `derived`.
Percentiles and standard deviations are empty with fewer than two values.

| File | Columns |
|---|---|
| `dimensions/effectiveness.csv` | `n_trials`, `n_evaluated`, `primary_metric_name`, `primary_success_count`, `primary_success_rate`, `primary_score_mean`, `primary_score_median`, `primary_score_stddev` |
| `dimensions/efficiency.csv` | `n_trials`, `n_responses`, `primary_success_count`, `total_tokens_mean`, `total_tokens_median`, `total_tokens_p95`, `total_tokens_sum`, `tokens_per_primary_success`, `duration_sec_mean`, `duration_sec_median`, `duration_sec_p95`, `duration_sec_sum`, `duration_sec_per_primary_success`, `model_calls_mean`, `tool_calls_mean`, `function_calls_mean`, `mcp_tool_calls_mean`, `steps_mean`, `total_calls_sum`, `calls_per_primary_success` |
| `dimensions/robustness.csv` | `robustness_axis` (task, instance, repeat, model, representation), `n_groups`, `primary_success_rate_mean`, `primary_success_rate_min`, `primary_success_rate_max`, `primary_success_rate_range`, `primary_score_mean`, `primary_score_stddev`, `duration_sec_stddev`, `total_tokens_stddev` |
| `dimensions/evaluation_reliability.csv` | `evaluation_method`, `n_trials`, `n_evaluated`, `evaluation_coverage_rate`, `evaluation_success_rate`, `evaluation_error_rate`, `evaluation_skipped_rate`, `n_evaluation_status_other`, `judge_count_mean`, `judge_error_rate`, `judge_agreement_mean`, `judge_unanimity_rate`, `evaluation_tokens_mean`, `evaluation_duration_sec_median` |
| `dimensions/observability.csv` | `n_trials`, `trace_coverage_rate`, `execution_trace_coverage_rate`, `eval_trace_coverage_rate`, `raw_response_coverage_rate`, `tool_call_observability_rate`, `native_mcp_observability_rate`, `server_mcp_observability_rate`, `usage_observability_rate`, `error_observability_rate` |
| `aggregate_metrics.csv` | A cross-dimension selection: `n_trials`, `n_responses`, `n_evaluated`, `primary_metric_name`, `primary_success_rate`, `primary_score_mean`, `primary_score_stddev`, `total_tokens_mean`, `total_tokens_median`, `total_tokens_p95`, `tokens_per_primary_success`, `duration_sec_median`, `duration_sec_p95`, `duration_sec_per_primary_success`, `model_calls_mean`, `tool_calls_mean`, `function_calls_mean`, `mcp_tool_calls_mean`, `calls_per_primary_success`, `primary_success_rate_range_by_task`, `primary_success_rate_range_by_instance`, `primary_success_rate_range_by_repeat`, `primary_success_rate_range_by_model`, `primary_success_rate_range_by_representation`, `primary_success_rate_range_by_surface`, `evaluation_coverage_rate`, `evaluation_success_rate`, `evaluation_error_rate`, `judge_agreement_mean`, `judge_unanimity_rate`, `trace_coverage_rate`, `tool_call_observability_rate`, `usage_observability_rate` |

`dimension_summary.csv` and `summary.json` restate the dimension values in long and nested form.

### `failure_cases.csv` — one row per failing trial

A trial is included when its response is not a success, its evaluation errored or was skipped,
`primary_success` is `false`, or it was evaluated without a primary outcome. Columns:
`dataset_id`, `experimentId`, `trialId`, `taskId`, `instanceId`, `modelId`, `configurationId`,
`execution_status`, `evaluation_status`, `evaluation_method`, `primary_metric_name`,
`primary_success`, `primary_score`, `error_message`, `response_excerpt`.

## Adaptive runs

Files: `adaptive_request_metrics.csv`, `adaptive_attempt_metrics.csv`,
`adaptive_goal_metrics.csv`, `metrics-manifest.json`. Generation, assessor and evaluation usage
are always in separate columns.

### `adaptive_request_metrics.csv` — one row per planned request

| Columns | Meaning | Class |
|---|---|---|
| `requestId`, `sequenceIndex`, `taskId`, `instanceId`, `labels.<key>` | Request identity and labels. | — |
| `state`, `terminalReason`, `delivered`, `failureCategory` | Outcome: `delivered`, `failed` or `started`; `delivered`, `attempt_failed` or `response_too_short`. | derived |
| `privileged` | The run used an assessor with reference data. | — |
| `policyId`, `policyVersion`, `candidateId`, `executionId`, `attemptId`, `attemptCount` | Decision and attempt identity. | — |
| `requestDurationMs`, `requestDurationProvenance` | Decision to terminal state. | measured, per row |
| `generationDurationMs`, `generationDurationProvenance` | Runtime-measured generation time, without online assessment. | measured, per row |
| `generationInputTokens`, `generationOutputTokens`, `generationTotalTokens`, `generationTotalTokensProvenance`, `generationUsageCompleteness` | Generation usage of the request's attempt. | reported or estimated, per row |
| `assessorDurationMs`, `assessorDurationProvenance`, `assessorTotalTokens`, `assessorTokenProvenance`, `knownAssessorTotalTokens` | Online assessor cost. | per row |
| `nonDeliveredAttemptCount`, `knownNonDeliveredInputTokens`, `knownNonDeliveredOutputTokens`, `knownNonDeliveredTotalTokens`, `nonDeliveredUsageCompleteness` | Usage of attempts that were not delivered (known values only). | derived |
| `deliveredInputTokens`, `deliveredOutputTokens`, `deliveredTotalTokens`, `deliveredTokenProvenance` | Usage of the delivered attempt. | per row |
| `evaluationInputTokens`, `evaluationOutputTokens`, `evaluationTotalTokens`, `evaluationTokenProvenance`, `evaluationDurationMs`, `evaluationStatus`, `evaluationMethod` | Offline evaluation (`eval`) of the delivered response. | per row |
| `correctnessRating`, `correctnessAgreement`, `completenessRating`, `completenessAgreement` | Majority judge outcome and agreement. | derived |

### `adaptive_attempt_metrics.csv` — one row per execution attempt

| Columns | Meaning | Class |
|---|---|---|
| `requestId`, `candidateId`, `executionId`, `attemptId`, `attemptIndex` | Attempt identity. | — |
| `implementationDigest` | Implementation that executed the attempt. | — |
| `executionStatus`, `startedAt`, `finishedAt`, `durationMs` | Attempt status and wall time, including online assessment. | measured |
| `generationDurationMs`, `generationDurationProvenance` | Generation time without assessment. | measured, per row |
| `inputTokens`, `outputTokens`, `totalTokens`, `tokenProvenance` | Generation usage. | per row |
| `delivered`, `failureCategory`, `accepted` | Outcome and failure category. | derived |
| `injectedDelayMs`, `injectedFailures` | Disturbance effects: configured delay × affected calls, and injected failures. | derived / measured |
| `assessorDurationMs`, `assessorDurationProvenance`, `assessorTotalTokens`, `assessorTokenProvenance`, `knownAssessorTotalTokens` | Online assessor cost. | per row |
| `<signal>`, `<signal>Provenance` | One column per built-in and declared signal (for example `latency_ms`, `total_tokens`, `quality.<metric>`) with its provenance. | per row |

### `adaptive_goal_metrics.csv` — one row per terminal request and goal

`requestId`, `sequenceIndex`, `goalId`, `signal`, `statistic`, `scope`, `window`, `status`
(`met`, `violated`, `unknown`), `value`, `provenance`, `sampleCount`, `missingCount`,
`boundType` (`upper` or `lower`), `bound`. The window ends at and includes the request. Values
are `derived`; `unknown` means the reading was unavailable.

### `metrics-manifest.json`

`schemaVersion` (`"4.0-adaptive"`), `workflowKind`, `inputDirectory`, `requestCount`,
`attemptCount`, `privileged`, `implementationDigests`, `mixedImplementations`,
`requestStates`, `outputs`.
