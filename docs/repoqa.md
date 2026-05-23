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
scripts/repoqa_build_dataset \
  --output datasets/repoqa-experimental \
  --version 2026-05-23.1 \
  --language python \
  --max-base-instances 2 \
  --context-tokens 1024 \
  --input ../repoqa/repoqa-2024-06-23.json.gz \
  --force
```

The wrapper uses `tools/repoqa/.venv/bin/python` by default, verifies the required RepoQA imports, then forwards all arguments to `scripts/build_repoqa_dataset.py`.
On Nix systems, the wrapper also adds a discovered GCC runtime library path so binary wheels such as NumPy can load `libstdc++.so.6`.

## Local RepoQA Clone Override

For RepoQA development, point the wrapper at another Python environment:

```bash
REPOQA_PYTHON="$HOME/repos/doutorado/repoqa/.venv/bin/python" \
scripts/repoqa_build_dataset \
  --output datasets/repoqa-experimental \
  --version 2026-05-23.1 \
  --language python \
  --max-base-instances 2 \
  --context-tokens 1024 \
  --input ../repoqa/repoqa-2024-06-23.json.gz \
  --force
```

Provider-backed ctxbench execution and evaluation remain separate. Do not use this tool environment to run `ctxbench execute` or `ctxbench eval` against real providers.
