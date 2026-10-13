# RepoQA Tool Environment

LLMContextBench keeps RepoQA in an isolated tool environment under `tools/repoqa/`.
This avoids adding RepoQA's research dependencies to the main LLMContextBench runtime while keeping dataset generation reproducible.

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

Provider-backed ctxbench execution and evaluation remain separate. Do not use this tool environment to run `llmctxbench execute` or `llmctxbench eval` against real providers.

## Exporting native RepoQA model outputs

Run `tools/repoqa/export_repoqa_outputs.py` in the benchmark Python environment. It
requires the provisioning manifest and validates canonical responses before export.
Use `--configuration ID`, `--strategy NAME`, or `--representation NAME` to filter;
`--split` writes separate files per model and persisted configuration ID. Native
output rows retain `configurationId`, `strategy`, and `representation` in `ctxbench`
metadata. Historical outputs require the previous benchmark version.

### Historical MCP operation errors

Older RepoQA MCP handlers discarded service error flags. In
`runs/repoqa-adaptive-001`, 22 error-only tool payloads were recorded with
`isError: false` (three calibration calls and 19 episode calls). These are
operation errors, not evidence of transport failure or necessarily failed final
answers. Historical artifacts remain unchanged; collect fresh compatible baselines
for corrected reliability measurements. Current handlers preserve the flag and
normalized content, allowing the model to recover on subsequent steps. Lattes
currently raises missing-data exceptions in its service rather than returning
flagged service results; that distinct behavior is unchanged.

### Opt-in lean operations

`experiment.repoqa-five.json` compares inline full context, local MCP default/lean,
and local function default/lean. The `repoqa-lean` surface declares
`list_files_lean`, `list_symbols_lean`, `get_symbol_lean`, and `read_file_lean`.
These return path strings, flat deduplicated symbol records with documentation,
complete code, and file content respectively. Defaults still expose the original
four operations. Lean transport schemas and normalized results are equivalent.
Smaller serialized payloads are measured bytes, not demonstrated token savings.
