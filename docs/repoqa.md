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

## Long64 dataset version

`datasets/repoqa-2026-10-13-long64/` is the immutable `ctxbench/repoqa` version
`2026-10-13-long64.1`. It selects five new needles per language from two large
repositories: `karate` and `mssql-jdbc` (Java), `locust` and
`pytorch_geometric` (Python), `cargo` and `LibAFL` (Rust), and `date-fns` and
`langchainjs` (TypeScript). The manifest records the exact repository, needle
index, source archive hash, generator hash, RepoQA revision, and tokenizer
revision. `instances.index.json` records requested and actual native token counts.

Regenerate into a **new, empty** directory with the same command, changing only
`--output` for verification:

```bash
HF_HUB_OFFLINE=1 tools/repoqa/repoqa_build_dataset \
  --input datasets/repoqa/raw/repoqa-2026-05-23.json.gz \
  --output datasets/repoqa-2026-10-13-long64 \
  --version 2026-10-13-long64.1 --selection-profile long64 --compress-raw \
  --context-tokens 2048 --context-tokens 4096 --context-tokens 8192 \
  --context-tokens 16384 --context-tokens 32768 --context-tokens 65536
```

The generator rejects 64k contexts below 95% of 65,536 native tokens. The
existing `datasets/repoqa/` version and its results stay intact. Targets differ
between versions, so compare distributions rather than target-paired outcomes.

`experiment.repoqa-long64.json` and
`examples/studies/baseline.repoqa-long64.json` define the five-configuration
long64 baseline. The SEAMS v2 definitions (`study.seams-cascade.json`, which
selects all five configurations, and `study.seams-degradation.json` and `study.seams-inline-degradation.json`, which
select inline and lean local MCP) use the v2 frozen baseline. The v1
definitions `study.long64-{budget,latency,reliability}.json` use the v1 baseline
and select the inline and local-MCP configurations.

Observed lean-surface behaviour: in v1 held-out runs, every lean MCP failure was a
`max_steps=8` step-limit error on two targets (`rs_004`, `py_005`), at every context
size, while lean used about half the tokens of the default surface. Calibration did
not include those targets. The cascade policy exploits this with a bounded fallback
to the default surface. See `docs/studies.md` for preparation, evaluation, freezing,
degradation, and held-out execution commands. The four-size profile groups
2k/4k as small and 8k/16k as large. The six-size profile groups 2k/4k as
small, 8k/16k as medium, and 32k/64k as large. These groups determine
calibration estimates; nominal size and target identity do not enter router
features. Example context limits are study inputs to review against the chosen
model before paid execution.
