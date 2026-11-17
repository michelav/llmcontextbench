# Benchmark experiments

A benchmark runs every combination of task, instance, model, configuration and repeat declared
in a definition. The field reference is in [benchmark definition](reference/definition-benchmark.md).

## Inspect the dataset

```console
llmctxbench dataset inspect examples/datasets/fake
```

A remote or archived dataset is materialised first; archive fetches require a trusted checksum:

<!-- docs-test: skip (downloads from a remote URL) -->
```shell
llmctxbench dataset fetch --dataset-url https://example.org/path/to/dataset.tar.gz \
  --sha256 <trusted-sha256> --cache-dir ./.ctxbench/datasets
```

## Plan

```console
llmctxbench plan examples/benchmark/static-minimal.json --output outputs/bench
llmctxbench status outputs/bench
```

`plan` resolves the definition (including `extends`), the dataset and the surfaces, writes
`trials.jsonl`, `resolved.json` and `manifest.json`, and computes the execution fingerprint. The
output directory must be new or empty.

## Execute

```console
llmctxbench execute outputs/bench/trials.jsonl
```

`execute` checks the fingerprint first: a changed plan, implementation or dataset is refused.
Each invocation is stored as a durable attempt under `execution-records/`; an interrupted run is
resumed by running the same command again. A `started` attempt without a result may have reached
the provider and is retried only with `--retry-uncertain`. `--force` creates a new attempt even
when the latest one is complete.

Selectors restrict a phase to a subset of trials: `--model`, `--provider`, `--instance`,
`--task`, `--configuration`, `--strategy`, `--representation`, `--surface`, `--repetition`,
`--trial`, `--trial-file`, and the matching `--not-*` options.

```console
llmctxbench execute outputs/bench/trials.jsonl --task task_role
```

## Evaluate

`eval` runs the judges declared in `evaluation.judges` and writes `evals.jsonl` (aggregated
outcome per response) and `judge_votes.jsonl` (one vote per judge):

<!-- docs-test: skip (calls the configured judge providers) -->
```shell
llmctxbench eval outputs/bench/responses.jsonl
llmctxbench eval outputs/bench/responses.jsonl --judge <judge-id> --status ok
```

Provider batch APIs are available with `--batch`, `--batch-id`, `--wait` and `--poll-interval`.

## Export and metrics

```console
llmctxbench export outputs/bench/responses.jsonl --output outputs/bench/results.csv
llmctxbench metrics outputs/bench
llmctxbench status outputs/bench --by configuration
```

`export` writes one CSV row per response; evaluations and judge votes are added when present.
`--id <trialId>` prints one response as JSON instead. `metrics` writes the tables described in
[metrics](reference/metrics.md); it groups by `dataset_id,configurationId` by default
(`--group-by` changes it) and accepts several run directories.

Configuration IDs are kept in exports and metrics; metrics reject conflicting definitions of
one configuration ID across experiments. A strategy-only summary may pool several configurations
and says so.

## Real providers

The Lattes and RepoQA examples in `examples/benchmark/` use real providers and may incur cost
when executed. Provider credentials are configured as the provider SDKs require.
