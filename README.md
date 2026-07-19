# CTXBench

CTXBench is a Python command-line benchmark framework for comparing context
provisioning strategies in LLM-based systems.

The benchmark keeps the dataset instances and tasks fixed, then varies how the
model receives or retrieves context. It records the resulting responses,
metrics, traces, qualitative evaluations, judge votes, and analysis-ready
exports so runs can be inspected and reproduced.

Primary comparison dimensions include:

- answer quality
- token cost
- execution time
- tool usage
- traceability
- judge agreement
- reproducibility

## Repository Organization

The current public package and CLI name is `ctxbench`.

```text
.
├── README.md
├── flake.nix
├── pyproject.toml
├── uv.lock
├── src/ctxbench/
│   ├── cli.py
│   ├── commands/
│   ├── benchmark/
│   ├── dataset/
│   ├── adapters/
│   ├── ai/
│   └── util/
├── datasets/
│   ├── lattes/
│   └── repoqa/
├── docs/
│   ├── architecture/
│   ├── datasets/
│   └── development/
├── specs/
├── tests/
└── tools/repoqa/
```

Important areas:

- `src/ctxbench/cli.py` defines the `ctxbench` CLI and subcommands.
- `src/ctxbench/commands/` contains command handlers for `dataset`, `plan`,
  `execute`, `eval`, `export`, and `status`.
- `src/ctxbench/benchmark/` owns experiment loading, trial planning, execution,
  evaluation, selectors, checkpoints, and result construction.
- `src/ctxbench/dataset/` contains generic dataset contracts, resolution,
  caching, package validation, acquisition, payloads, and inspection.
- `src/ctxbench/adapters/` contains first-party dataset adapters. Current
  adapters include `ctxbench/lattes` and `ctxbench/repoqa`.
- `src/ctxbench/ai/` contains model integrations, execution strategies,
  runtime/tool-loop code, cache support, rate control, and trace collection.
- `datasets/` contains local dataset material used during development and
  experiments.
- `tests/fixtures/` contains provider-free fixtures used by tests.
- `tools/repoqa/` is an isolated RepoQA dataset-generation environment; it is
  not the main CTXBench runtime.

Detailed architecture documentation starts at
[`docs/architecture/README.md`](docs/architecture/README.md).

## Main Components

CTXBench is organized around a small lifecycle:

```text
experiment config
  -> ctxbench plan
  -> trials.jsonl + manifest.json
  -> ctxbench execute
  -> responses.jsonl + execution traces
  -> ctxbench eval
  -> evals.jsonl + judge_votes.jsonl + eval traces
  -> ctxbench export
  -> results.csv
```

The main commands are:

- `ctxbench dataset fetch`: materialize a dataset into a local cache.
- `ctxbench dataset inspect`: inspect a local or cached dataset package.
- `ctxbench plan`: expand an experiment configuration into planned trials.
- `ctxbench execute`: execute trials and collect model responses.
- `ctxbench eval`: evaluate responses using configured judge models.
- `ctxbench export`: export evaluation artifacts to CSV.
- `ctxbench status`: summarize experiment progress from artifacts.

`ctxbench execute` and `ctxbench eval` may call real model providers depending
on the experiment configuration. Treat them as provider-backed commands unless
the experiment explicitly uses mock providers or test fixtures.

## Installation

CTXBench supports two common development setups: Nix flakes for Nix/NixOS users
and a normal Python virtual environment for everyone else.

### Nix or NixOS

The repository includes a flake that builds a Python 3.12 environment from
`uv.lock` through `uv2nix`.

Enter the development shell:

```bash
nix develop
```

Inside the shell:

- `ctxbench` is available on `PATH`
- `python` uses the locked environment
- `PYTHONPATH` points at `src`
- `.venv` is created as a symlink to the Nix-provided virtual environment when
  possible

You can also run the packaged app through Nix:

```bash
nix run
```

For NixOS users working with RepoQA tooling, prefer the wrappers under
`tools/repoqa/`. They add runtime library paths needed by some binary wheels.
See [`docs/repoqa.md`](docs/repoqa.md).

### Non-Nix Systems

Use Python 3.11 or 3.12. A local virtual environment is recommended.

With `uv`:

```bash
uv sync --locked --extra dev
```

Then run the CLI from the environment:

```bash
uv run ctxbench --help
```

With standard `venv` and `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Then:

```bash
ctxbench --help
```

Do not install new dependencies or update lockfiles unless the dependency change
is intentional.

## Getting Started

This sequence gives a new user the shape of the workflow without requiring real
provider calls.

### 1. Inspect a Local Dataset

Inspect a dataset package before planning an experiment:

```bash
ctxbench dataset inspect datasets/repoqa
```

For a cached dataset reference, use:

```bash
ctxbench dataset inspect ctxbench/repoqa@2026-05-23
```

If the dataset is remote or archived, materialize it first:

```bash
ctxbench dataset fetch \
  --dataset-url https://example.org/path/to/dataset.tar.gz \
  --sha256 <trusted-sha256> \
  --cache-dir ./.ctxbench/datasets
```

Archive fetches require trusted checksums so the materialized dataset is
reproducible and safe to extract.

### 2. Create or Choose an Experiment Config

An experiment selects the dataset, scope, model factors, strategies, formats,
and evaluation settings.

Minimal local-dataset shape:

```json
{
  "id": "repoqa_inline_local_001",
  "output": "outputs",
  "dataset": {
    "root": "datasets/repoqa"
  },
  "scope": {
    "instances": [],
    "tasks": []
  },
  "factors": {
    "model": [
      {
        "provider": "mock",
        "name": "mock-model"
      }
    ],
    "strategy": ["inline"],
    "format": ["json"]
  },
  "evaluation": {
    "enabled": false,
    "judges": []
  }
}
```

Empty `scope.instances` and `scope.tasks` mean all available instances and
tasks. Use small scopes for exploratory runs.

For a provider-free smoke-check configuration, see
`tests/fixtures/fake_dataset/experiment.json`.

### 3. Plan the Experiment

Planning expands the experiment into immutable trial artifacts:

```bash
ctxbench plan tests/fixtures/fake_dataset/experiment.json \
  --output outputs/getting-started
```

Planning writes:

- `outputs/getting-started/manifest.json`
- `outputs/getting-started/trials.jsonl`

Planning does not call model providers.

### 4. Check Status

Before execution, status can still summarize what artifacts exist:

```bash
ctxbench status outputs/getting-started
```

Breakdowns are available by `model`, `strategy`, `instance`, `task`, or
`judge`:

```bash
ctxbench status outputs/getting-started --by strategy
```

### 5. Execute and Evaluate When Ready

Run these only when the selected experiment is intentionally configured for the
provider cost and observability tradeoffs you want:

```bash
ctxbench execute outputs/getting-started/trials.jsonl
ctxbench eval outputs/getting-started/responses.jsonl
```

Both commands support selectors such as:

```bash
ctxbench execute outputs/getting-started/trials.jsonl --task task_role
ctxbench eval outputs/getting-started/responses.jsonl --model mock-model --status ok
```

Selectors include `--model`, `--provider`, `--instance`, `--task`,
`--strategy`, `--format`, `--repetition`, `--trial`, and `--trial-file`, plus
matching `--not-*` variants.

### 6. Export Results

After evaluation artifacts exist:

```bash
ctxbench export outputs/getting-started/evals.jsonl \
  --to csv \
  --output outputs/getting-started/results.csv
```

`ctxbench export` is artifact-only. It reads existing benchmark artifacts and
does not resolve datasets or call providers.

## Datasets

A dataset package normally contains:

```text
dataset-root/
  ctxbench.dataset.json
  tasks.json
  tasks.instance.json
  context/
    <instanceId>/
      ...
```

The dataset manifest `ctxbench.dataset.json` identifies the package, version,
layout, and provenance. It is distinct from the lifecycle `manifest.json`
written by `ctxbench plan`.

Experiments may reference a dataset by local root:

```json
{
  "dataset": {
    "root": "datasets/repoqa"
  }
}
```

Or by package identity and version when materialized in the cache:

```json
{
  "dataset": {
    "id": "ctxbench/repoqa",
    "version": "2026-05-23"
  }
}
```

For dataset authoring and distribution requirements, see
[`docs/datasets/creating-a-dataset.md`](docs/datasets/creating-a-dataset.md).

## Strategies

CTXBench compares context provisioning strategies through the same experiment
and artifact contract.

| Strategy | Description |
|---|---|
| `inline` | The selected context representation is inserted directly into the model input. |
| `local_function` | CTXBench exposes local Python tools and controls the tool loop. |
| `local_mcp` | CTXBench exposes tools through a local MCP runtime and controls the loop. |
| `remote_mcp` | A remote MCP integration participates in context access; provider-side behavior may be less observable. |

When a strategy cannot expose a metric reliably, CTXBench records the metric as
unavailable/null rather than inventing a value.

## Output Artifacts

Typical experiment outputs:

```text
outputs/<experimentId>/
  manifest.json
  trials.jsonl
  responses.jsonl
  evals.jsonl
  judge_votes.jsonl
  evals-summary.json
  results.csv
  traces/
    executions/
      <trialId>.json
    evals/
      <trialId>.json
```

Canonical lifecycle artifacts are JSON or JSONL. `results.csv` is a derived
export for analysis.

For the detailed artifact contract and migration rules, see
[`docs/architecture/artifact-contracts.md`](docs/architecture/artifact-contracts.md).

## Development

Install development dependencies through either `nix develop`, `uv sync
--locked --extra dev`, or `pip install -e ".[dev]"`.

Run focused tests during development:

```bash
pytest -k plan
pytest -k execute
pytest -k eval
pytest -k export
pytest -k cli
```

Run the full test suite when appropriate:

```bash
pytest -q
```

Report test coverage when needed:

```bash
pytest --cov=ctxbench --cov-report=term-missing
pytest --cov=ctxbench --cov-report=term-missing --cov-report=xml:coverage.xml --cov-report=html:htmlcov
```

RepoQA dataset generation uses a separate locked tool environment:

```bash
cd tools/repoqa
uv sync --locked

cd ../..
tools/repoqa/repoqa_build_dataset --help
```

See [`docs/repoqa.md`](docs/repoqa.md) for RepoQA-specific setup, Nix runtime
notes, and local clone overrides.

## Compatibility Notes

The repository has migrated public terminology to `ctxbench`, `execute`,
`trials.jsonl`, `responses.jsonl`, `trialId`, `taskId`, and `response`.

Legacy names such as `copa`, `query`, `queries.jsonl`, `answers.jsonl`,
`runId`, `questionId`, and `answer` may still appear in historical specs,
generated metadata, or migration notes. New documentation, examples, and public
interfaces should use the current terminology.

## License

CTXBench is licensed under the [MIT License](LICENSE).
