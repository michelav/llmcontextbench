# Metrics design

`llmctxbench metrics` (API: `Run.metrics`) turns run artifacts into metric tables. This document
states the rules the metrics follow; the column-by-column reference is the guide's metrics
reference (`docs/guide/reference/metrics.md`). Code: `ctxbench/metrics/` and
`AdaptiveWorkflow.write_metrics`.

## Principles

- **Artifact-only.** Metrics read existing artifacts. They never execute, re-evaluate, call a
  provider, MCP server, external API or dataset scorer, and never modify lifecycle artifacts.
  (Adaptive metrics rebuild the `responses.jsonl` projection from canonical records.)
- **Deterministic.** The same artifacts give the same values. Only timestamps and command
  provenance in `metrics-manifest.json` may differ.
- **Multi-dimensional.** No single score. Benchmark metrics are organised in five dimensions:
  effectiveness, efficiency, robustness, evaluation reliability, observability.
- **Dataset-agnostic.** No dataset-specific tables. Known evaluation methods are normalised into
  one primary effectiveness interface.
- **No plot-specific outputs.** Figures and paper tables are built by scripts from the canonical
  tables.
- **Missing is not zero.** A value that cannot be computed is an empty CSV cell or JSON `null`.
- **Phase separation.** Generation usage, online assessor usage and offline evaluation (judge)
  usage are kept in separate columns and never summed together.

## Provenance

Every metric value belongs to one provenance class:

| Class | Meaning | Examples |
|---|---|---|
| `reported` | Returned by a provider API, SDK or authoritative runtime. | Input and output tokens from the provider. |
| `measured` | Measured by benchmark-controlled instrumentation. | Durations, model and tool call counts, injected failure counts. |
| `derived` | Computed deterministically from reported or measured values. | Sums, means, percentiles, `failed`, `accepted`, applied disturbance delay, goal status. |
| `estimated` | Approximated by heuristics, tokenizers or incomplete information. | Token counts estimated when the provider does not report them. |
| `unavailable` | Not available and not responsibly estimated. | Reasoning tokens from a provider that does not report them. |

Estimated values are never presented as reported or measured, and an unavailable value is never
written as zero. Where a column can mix classes, a companion `…Provenance` column states the
class per row.

## Benchmark metrics

**Inputs.** `manifest.json` and `trials.jsonl` (required: they define the planned trial
universe); `responses.jsonl` (rebuilt from execution records), `evals.jsonl`,
`judge_votes.jsonl` and traces when present. Partial runs are supported: a planned-only run gives
planning and pending metrics; an unevaluated run gives execution, efficiency and partial
observability metrics. `evals-summary.json` is not used for computation.

**Outputs** (always written, with headers even when empty), under `metrics/`:
`metrics-manifest.json`, `trial_metrics.csv`, `aggregate_metrics.csv`, `dimension_summary.csv`,
`summary.json`, `failure_cases.csv`, and `dimensions/{effectiveness,efficiency,robustness,
evaluation_reliability,observability}.csv`.

**Primary effectiveness.** Each evaluation method maps to `primary_metric_name`,
`primary_success` and `primary_score`:

| Method | `primary_metric_name` | `primary_success` | `primary_score` |
|---|---|---|---|
| `judge` | `judge_meets` | correctness and completeness both `meets` | mean of the two ratings, `meets`=1, `partial`=0.5, `misses`=0 |
| `repoqa-scorer` | `pass` | `details.outcome.passed` | `details.repoqa.bestSimilarScore` |
| other | `null` | `null` | `null` (with a warning) |

When the planned and the actual evaluation method differ, the actual one is used and
`evaluation_method_consistent` is `false`.

**Judge votes and agreement.** Individual judge votes (`judge_votes.jsonl`), the majority
outcome (`evals.jsonl`) and unanimity are reported separately. `judge_unanimous` is `true` when
all non-error votes (at least two) agree on both criteria; it falls back to the aggregate
agreement flags when votes are absent, and is `null` with fewer than two votes.

**Robustness** is the observed variation over the axes task, instance, repeat, model and
representation; no perturbation tests are run.

**Observability** records whether execution and evaluation traces, token usage, tool calls,
native MCP and server MCP activity were observable per trial. Absent traces give `null`, not
`false`.

## Adaptive metrics

Adaptive runs have two units, and metrics keep them apart:

- **Request rows** (`adaptive_request_metrics.csv`): one per planned request — state, terminal
  reason, delivery, failure category, policy, decision, request duration; delivered-attempt
  usage, non-delivered usage, assessor usage and offline evaluation usage in separate column
  groups; one `labels.<key>` column per request label.
- **Attempt rows** (`adaptive_attempt_metrics.csv`): one per execution attempt — status,
  timing, generation usage with provenance, failure category, acceptance, injected disturbance
  effects, assessor cost, the implementation digest, and one column per signal with a
  `<signal>Provenance` column.
- **Goal rows** (`adaptive_goal_metrics.csv`): one per terminal request and goal — status
  (`met`, `violated`, `unknown`), value, provenance and sample counts. Goals are evaluated from
  the request records alone with the same window and statistics code the policies use
  (`adaptive/state.py`, `adaptive/goals.py`), with the window ending at and including the
  request.

`metrics-manifest.json` (`schemaVersion: "4.0-adaptive"`) reports request and attempt counts,
request states, `privileged`, the set of `implementationDigests` and `mixedImplementations`.
Attempt `durationMs` is wall time including online assessment; `generationDurationMs` (the
`latency_ms` signal) excludes it.

## Run analysis

Two artifact-only functions in `ctxbench/analysis/`, exposed through `ctxbench.api`:

- `summarize(runs, signals=...)`: one row per run with identity (labels, policy, seed,
  `privileged`, `mixedModels`, rate-limit settings, workload digest), counts per state and
  failure category, per-signal sums and means over all attempts and over delivered requests
  (each with provenance and missing count), and goal violation counts. Runs are comparable
  request by request only when their workload digests are equal. Pairing and statistics are left
  to scripts.
- `headroom(run, signal=..., objective=..., by=None)`: over a benchmark matrix, compares the
  best static candidate with a per-request oracle, with coverage of missing cells. All outputs
  are `derived`. The oracle knows each request, so it is an upper bound that request-blind
  policies cannot reach, and a stationary matrix says nothing about disturbances.

## Conventions

- Row order is deterministic (benchmark trials by dataset, experiment and trial ID; adaptive
  requests by sequence index; attempts by request and attempt index).
- CSV: UTF-8 without BOM, `\n` newlines, empty cells for `null`, lowercase booleans.
- Percentiles use linear interpolation (`metrics/aggregate.py::percentile`) and are `null`
  with fewer than two values; standard deviation uses the sample estimator and is `null` with
  fewer than two values; a mean over no values is `null`.
