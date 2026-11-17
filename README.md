# LLMContextBench

LLMContextBench is a Python command-line benchmark framework for comparing context provisioning
strategies in LLM-based systems: `inline` context, `local_function` tools, a `local_mcp` runtime,
or a `remote_mcp` server.

The dataset instances and tasks stay fixed while the way the model receives or retrieves context
varies. The tool records responses, token usage, timing, tool calls, traces, evaluations and
individual judge votes, with the provenance of every value, so runs can be inspected, compared
and reproduced. It supports two workflows:

- **benchmark**: a static matrix of tasks × instances × models × configurations;
- **adaptive**: a request-blind policy chooses a model and configuration for each request of an
  ordered workload, using only what earlier requests showed.

The command is `llmctxbench` (Python package `ctxbench`): `plan`, `execute`, `eval`, `export`,
`metrics`, `status`. [Demo video](https://youtu.be/nU_ZUGwrmP0).

## Install

Python 3.11 or 3.12. With Nix: `nix develop`. With `uv`:

```shell
uv sync --locked --extra dev
```

With `pip`: `pip install -e ".[dev]"`. Details: [getting started](docs/guide/getting-started.md).

## Quickstart

Provider-free, with the mock provider and the fake dataset in `examples/datasets/fake/`:

```console
llmctxbench plan examples/benchmark/static-minimal.json --output outputs/readme-benchmark
llmctxbench execute outputs/readme-benchmark/trials.jsonl
llmctxbench metrics outputs/readme-benchmark
llmctxbench status outputs/readme-benchmark

llmctxbench plan examples/adaptive/window-threshold.json --output outputs/readme-adaptive
llmctxbench execute outputs/readme-adaptive/adaptive-plan.json
llmctxbench metrics outputs/readme-adaptive
llmctxbench status outputs/readme-adaptive

python examples/adaptive/code_built.py outputs/readme-code-built
```

`plan` never calls a provider. `execute` runs answer generation and `eval` runs judge models;
with real providers configured, both may incur cost.

## Documentation

- [Guide](docs/guide/): [getting started](docs/guide/getting-started.md),
  [concepts](docs/guide/concepts.md), [benchmark experiments](docs/guide/benchmark-experiments.md),
  [adaptive experiments](docs/guide/adaptive-experiments.md),
  [experiments in code](docs/guide/experiments-in-code.md), datasets
  ([creating](docs/guide/datasets/creating-a-dataset.md),
  [external](docs/guide/datasets/using-external-datasets.md),
  [RepoQA](docs/guide/datasets/repoqa.md)), and reference
  ([CLI](docs/guide/reference/cli.md), [benchmark definition](docs/guide/reference/definition-benchmark.md),
  [adaptive definition](docs/guide/reference/definition-adaptive.md),
  [Python API](docs/guide/reference/python-api.md),
  [output artifacts](docs/guide/reference/output-artifacts.md),
  [metrics](docs/guide/reference/metrics.md)).
- [Architecture](docs/architecture/README.md): design, contracts and
  [decisions](docs/architecture/decisions/README.md).
- [Development](docs/development/): tests, [validation guide](docs/development/validation-guide.md),
  spec workflow.
- [Sprints](docs/sprints/README.md): development history.

See [docs/README.md](docs/README.md) for where each kind of content goes.

## Development

```shell
pytest -q
pytest -k "adaptive"
```

## Citing

Identify the exact code revision, dataset versions, experiment definition and artifact archive
used in your work.

## License

MIT; see [LICENSE](LICENSE).
