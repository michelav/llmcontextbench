# Benchmark workflow

The benchmark workflow runs a static matrix: every (task, instance, model, configuration,
repeat) combination is a trial, and all trials are known at plan time.

```text
definition (schemaVersion 3, kind "benchmark")
  → plan     → manifest.json + resolved.json + trials.jsonl
  → execute  → execution-records/ (one record per attempt) → responses.jsonl projection
  → eval     → evals.jsonl + judge_votes.jsonl
  → export / metrics / status
```

## Planning

`BenchmarkWorkflow.plan` resolves the definition (including `extends`), the dataset and the
surfaces, expands the trial matrix into `trials.jsonl`, and writes the manifest with a computed
`executionFingerprint` over `resolved.json`, `trials.jsonl`, the implementation digest and the
dataset digest ([manifest contract](../contracts/manifest.md)). Every trial has a stable
`trialId`.

## Execution

`execute` runs the selected trials through `TrialExecutionService`. It verifies the fingerprint
first: changed frozen artifacts, a changed implementation or a changed dataset are refused.
Each invocation is a durable attempt; `responses.jsonl` is rebuilt from the attempt records and
is not the recovery authority. `--force` and selectors are supported.

## Evaluation and analysis

`eval` judges responses and writes individual judge votes (`judge_votes.jsonl`) and aggregated
outcomes (`evals.jsonl`); judge usage stays in evaluation artifacts. `metrics` writes trial
rows and aggregates; `export` and `status` read artifacts only.

The benchmark matrix is also the input of `ctxbench.api.headroom`, which compares the best
static candidate with a per-request oracle over the same requests.
