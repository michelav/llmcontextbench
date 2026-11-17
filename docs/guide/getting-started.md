# Getting started

This page installs LLMContextBench and runs both workflows end to end with the mock provider and
the small fake dataset in `examples/datasets/fake/`. Nothing here calls a real model provider.

## Install

Use Python 3.11 or 3.12.

With Nix (the flake builds the locked environment and puts `llmctxbench` on `PATH`):

```shell
nix develop
```

With `uv`:

<!-- docs-test: skip (installs the environment) -->
```shell
uv sync --locked --extra dev
uv run llmctxbench --help
```

With `venv` and `pip`:

```shell
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

On NixOS, RepoQA tooling needs the wrappers under `tools/repoqa/`; see
[RepoQA](datasets/repoqa.md).

## A benchmark run

A benchmark freezes every trial (task × instance × model × configuration × repeat) at plan time.
Run the commands from the repository root:

```console
llmctxbench plan examples/benchmark/static-minimal.json --output outputs/quickstart-benchmark
llmctxbench status outputs/quickstart-benchmark
llmctxbench execute outputs/quickstart-benchmark/trials.jsonl
llmctxbench export outputs/quickstart-benchmark/responses.jsonl --output outputs/quickstart-benchmark/results.csv
llmctxbench metrics outputs/quickstart-benchmark
llmctxbench status outputs/quickstart-benchmark
```

`plan` writes `manifest.json`, `resolved.json` and `trials.jsonl` and makes no provider call.
`execute` writes one durable record per attempt and rebuilds `responses.jsonl`. `export` writes a
CSV, and `metrics` writes the metric tables under `metrics/`.

Evaluation (`llmctxbench eval`) runs judge models. The example disables it, because the mock
provider does not act as a judge; see [benchmark experiments](benchmark-experiments.md#evaluate).

## An adaptive run

An adaptive experiment declares a catalogue of candidates and a policy; the policy picks a
candidate for each request at run time, using only what earlier requests showed.

```console
llmctxbench plan examples/adaptive/window-threshold.json --output outputs/quickstart-adaptive
llmctxbench execute outputs/quickstart-adaptive/adaptive-plan.json
llmctxbench status outputs/quickstart-adaptive
llmctxbench metrics outputs/quickstart-adaptive
```

Look at `outputs/quickstart-adaptive/adaptive-records/` for one record per request with the
decision, its reason and the readings the policy used, and at
`outputs/quickstart-adaptive/metrics/adaptive_goal_metrics.csv` for the goal statuses.
[Adaptive experiments](adaptive-experiments.md) walks through this example.

## Next

- [Concepts](concepts.md): datasets, tasks, instances, strategies, workflows.
- [Benchmark experiments](benchmark-experiments.md) and
  [adaptive experiments](adaptive-experiments.md).
- [Experiments in code](experiments-in-code.md): the Python API.
- Reference: [CLI](reference/cli.md), [benchmark definition](reference/definition-benchmark.md),
  [adaptive definition](reference/definition-adaptive.md), [Python API](reference/python-api.md),
  [output artifacts](reference/output-artifacts.md), [metrics](reference/metrics.md).
