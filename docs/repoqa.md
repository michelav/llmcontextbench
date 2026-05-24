# RepoQA Tool Environment

CTXBench keeps RepoQA in an isolated tool environment under `tools/repoqa/`.
This avoids adding RepoQA's research dependencies to the main ctxbench runtime while keeping dataset generation reproducible.

## Setup

Create the locked tool environment:

```bash
cd tools/repoqa
uv sync --locked
```

The lockfile pins RepoQA to `evalplus/repoqa` commit `ae876deb1365dbf5a15b0533723c8ed123eee586`.

## Build A Small Dataset

From the repository root:

```bash
tools/repoqa/repoqa_build_dataset \
  --output datasets/repoqa-experimental \
  --version 2026-05-23.1 \
  --language python \
  --max-base-instances 2 \
  --context-tokens 1024 \
  --input ../repoqa/repoqa-2024-06-23.json.gz \
  --force
```

The wrapper uses `tools/repoqa/.venv/bin/python` by default, verifies the required RepoQA imports, then forwards all arguments to `tools/repoqa/build_repoqa_dataset.py`.
On Nix systems, RepoQA commands should go through `tools/repoqa/repoqa_python`, which adds discovered runtime library paths for binary wheels such as NumPy before invoking Python.

## Score Exported Outputs

Exported RepoQA model outputs can be scored with the shared Python wrapper:

```bash
tools/repoqa/repoqa_python -m repoqa.compute_score \
  --model_output_path outputs/repoqa_inline_local_001/repoqa_outputs/gpt-mini_inline_code_context.jsonl \
  --dataset_path datasets/repoqa-minimal/raw/*
```

Calling `tools/repoqa/.venv/bin/python` directly can fail on Nix because PyPI binary wheels may not be able to find runtime libraries such as `libstdc++.so.6` and `libz.so.1`. Use `tools/repoqa/repoqa_python` for RepoQA modules unless you are already inside an environment that provides those libraries.

## Local RepoQA Clone Override

For RepoQA development, point the wrapper at another Python environment:

```bash
REPOQA_PYTHON="$HOME/repos/doutorado/repoqa/.venv/bin/python" \
tools/repoqa/repoqa_build_dataset \
  --output datasets/repoqa-experimental \
  --version 2026-05-23.1 \
  --language python \
  --max-base-instances 2 \
  --context-tokens 1024 \
  --input ../repoqa/repoqa-2024-06-23.json.gz \
  --force
```

Provider-backed ctxbench execution and evaluation remain separate. Do not use this tool environment to run `ctxbench execute` or `ctxbench eval` against real providers.
