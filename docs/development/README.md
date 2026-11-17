# Development

Working on LLMContextBench itself. Using the tool is covered in the [guide](../guide/README.md);
its design in [architecture](../architecture/README.md).

## Setup

`nix develop` (puts `llmctxbench` on `PATH` and points `PYTHONPATH` at `src`), or
`uv sync --locked --extra dev`, or `pip install -e ".[dev]"`. Do not add dependencies or update
lockfiles unless the change is intentional.

## Repository layout

```text
src/ctxbench/      the package (layering: architecture/README.md)
tests/             provider-free tests; fixtures under tests/fixtures/
examples/          provider-free example definitions and the fake dataset (examples/datasets/fake)
datasets/          local dataset material for development and experiments
docs/              guide/, architecture/, development/, sprints/ (rules: docs/README.md)
specs/             spec-kit feature folders
tools/repoqa/      isolated RepoQA dataset-generation environment
```

## Tests

Default tests never call real providers.

```shell
pytest -q
pytest -k "adaptive"
pytest -k "api"
pytest -k "cli"
pytest -k "metrics"
pytest tests/test_import_boundaries.py
pytest tests/test_docs.py
```

`tests/test_docs.py` runs every command in `console` blocks of `README.md` and `docs/guide/` in
a temporary copy of `examples/`, and checks every relative Markdown link under `README.md` and
`docs/`. A command that cannot run provider-free goes in a `shell` block preceded by
`<!-- docs-test: skip (<reason>) -->`. It also checks that the metrics reference names every
column and that `guide/` and `architecture/` do not refer to work packages.

Coverage:

```shell
pytest --cov=ctxbench --cov-report=term-missing
```

## RepoQA tool environment

RepoQA dataset generation has its own locked environment; see
[RepoQA](../guide/datasets/repoqa.md).

```shell
cd tools/repoqa && uv sync --locked && cd ../..
tools/repoqa/repoqa_build_dataset --help
```

## Other documents

- [Validation guide](validation-guide.md): provider-free end-to-end validation of both
  lifecycles.
- [Scenario guide](scenario-guide.md).
- [Spec workflow](spec-workflow.md) and [usage log](usage-log.md).
