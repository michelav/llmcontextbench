# CLI reference

The command is `llmctxbench` (the Python package is `ctxbench`). Lifecycle commands: `plan`,
`execute`, `eval`, `export`, `metrics`, `status`. Supporting commands: `dataset fetch`,
`dataset inspect`. `llmctxbench <command> --help` lists every option.

| Command | Input | Calls providers | Writes |
|---|---|---|---|
| `plan PATH` | benchmark or adaptive definition | no | run directory |
| `execute PLAN` | `<run>/trials.jsonl` or `<run>/adaptive-plan.json` | generation | execution records, `responses.jsonl`, adaptive records |
| `eval RESPONSES` | `<run>/responses.jsonl` | judges | `evals.jsonl`, `judge_votes.jsonl`, `evals-summary.json` |
| `export FILE` | `<run>/evals.jsonl` or `<run>/responses.jsonl` | no | `results.csv` |
| `metrics RUN...` | one or more run directories | no | `metrics/` |
| `status RUN` | run directory | no | nothing |

## `plan`

```text
llmctxbench plan PATH [--output DIR] [--cache-dir DIR] [--plugin-path DIR]... [--verbose] [--progress]
```

Selects the workflow from the definition (`workflowKind: "adaptive"`, otherwise benchmark).
`--output` overrides the definition's `output/<id>/`; the directory must be new or empty.
`--plugin-path` adds a directory to the import path for external policies and assessors.

## `execute`

```text
llmctxbench execute PLAN [--retry-uncertain] [--force] [selectors] [--plugin-path DIR]... [--verbose] [--progress]
```

Resumes when run again. `--retry-uncertain` retries an attempt that may have been interrupted
after reaching the provider. Benchmark only: `--force` creates a new attempt even when the
latest one is complete, and selectors restrict the trials. Adaptive runs reject `--force` and
selectors. Adaptive runs with external plug-ins need the same `--plugin-path` as at `plan`.

## `eval`

```text
llmctxbench eval RESPONSES [--force] [--judge ID]... [--not-judge ID]... [--batch] [--batch-id ID]
                 [--wait] [--poll-interval SECONDS] [--continue-on-error] [selectors] [--status S]
```

Runs the judges declared in the definition. `--judge`/`--not-judge` select judges by ID, model
or provider. `--batch` uses provider batch APIs.

## `export`

```text
llmctxbench export FILE [--to csv] [--output PATH] [--by KEY=VALUE]... [--id TRIAL_ID] [selectors] [--status S]
```

Writes one CSV row per response (default `results.csv` next to the input). Evaluations and judge
votes are added when present. `--id` prints one response as JSON.

## `metrics`

```text
llmctxbench metrics RUN... [--output DIR] [--group-by FIELDS] [--force] [selectors]
                    [--status S] [--execution-status S] [--evaluation-status S] [and --not-* forms]
```

Writes the tables in [metrics](metrics.md). Several benchmark runs can be combined. `--force`
replaces an existing metrics directory.

## `status`

```text
llmctxbench status RUN [--by FIELD]
```

Benchmark: execute and eval counts per phase. Adaptive: request states, attempts and whether
attempts span several implementations. `--by` breaks counts down by `model`, `configuration`,
`representation`, `strategy`, `instance`, `task`, `candidate` or `judge`.

## Selectors

Benchmark `execute`, `eval`, `export` and `metrics` accept: `--model`, `--provider`,
`--instance`, `--task`, `--configuration`, `--strategy`, `--representation`, `--surface`,
`--repetition` (comma-separated or repeated), `--trial ID,...|-`, `--trial-file PATH`, and
`--not-*` forms of each.

## `dataset`

```text
llmctxbench dataset inspect DATASET_REF [--json] [--cache-dir DIR]
llmctxbench dataset fetch (--descriptor-url URL | --descriptor-file PATH | --dataset-url URL
                           | --dataset-file PATH | --dataset-dir DIR)
                          [--id ID] [--version VERSION] [--sha256 SHA | --sha256-url URL | --sha256-file PATH]
                          [--force] [--cache-dir DIR]
```

`inspect` reports a dataset's identity and capabilities without provider calls; `DATASET_REF` is
a path or `<dataset-id>@<version>`. `fetch` materialises a dataset into the cache from a
descriptor, an archive or a directory; archive fetches require a trusted checksum.

## Exit codes and output

Commands print a one-line summary on success and a structured error line on failure, and exit
non-zero on failure.
