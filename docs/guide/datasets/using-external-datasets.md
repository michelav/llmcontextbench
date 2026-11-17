# Using External Datasets

## Purpose

This guide documents the supported workflow for working with datasets that live outside the
LLMContextBench repository.

Two command families matter:

- dataset-management commands: `llmctxbench dataset fetch`, `llmctxbench dataset inspect`
- lifecycle commands: `llmctxbench plan`, `llmctxbench execute`, `llmctxbench eval`, `llmctxbench export`, `llmctxbench metrics`, `llmctxbench status`

Lifecycle commands are local-only. They do not fetch, clone, or download datasets.

## Remote dataset workflow

Use this path when the experiment references a dataset by `id` and `version`.

```bash
llmctxbench dataset fetch \
  --descriptor-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.dataset.json \
  --cache-dir ./.ctxbench/datasets

llmctxbench dataset inspect ctxbench/lattes@0.1.0 --cache-dir ./.ctxbench/datasets

llmctxbench plan tests/fixtures/lattes_provider_free/experiment.json \
  --output outputs/lattes_example \
  --cache-dir ./.ctxbench/datasets
llmctxbench execute outputs/lattes_example/trials.jsonl
llmctxbench eval outputs/lattes_example/responses.jsonl
llmctxbench export outputs/lattes_example/evals.jsonl --to csv --output outputs/lattes_example/results.csv
llmctxbench status outputs/lattes_example
```

Expected artifact progression:

- `llmctxbench dataset fetch`: materializes the dataset into the local cache
- `llmctxbench dataset inspect`: reports capability and provenance metadata
- `llmctxbench plan`: writes `manifest.json` and `trials.jsonl`
- `llmctxbench execute`: writes `responses.jsonl` and execution traces
- `llmctxbench eval`: writes `evals.jsonl`, `judge_votes.jsonl`, `evals-summary.json`, and eval traces
- `llmctxbench export`: writes `results.csv`

## Local-path shortcut

Use this path when the experiment points directly to a dataset root.

```json
{
  "dataset": {
    "root": "datasets/local-dataset"
  }
}
```

For local paths, skip `llmctxbench dataset fetch` and go straight to inspection or planning:

```bash
llmctxbench dataset inspect datasets/local-dataset
llmctxbench plan experiment.json --output outputs/local_example
```

## Verified archive acquisition

### Canonical descriptor-based fetch

Preferred remote source:

```bash
llmctxbench dataset fetch \
  --descriptor-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.dataset.json
```

Offline descriptor source:

```bash
llmctxbench dataset fetch \
  --descriptor-file ./downloads/ctxbench-lattes-v0.1.0.dataset.json
```

### Direct archive URL with `--sha256`

```bash
llmctxbench dataset fetch \
  --dataset-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.tar.gz \
  --id ctxbench/lattes \
  --version 0.1.0 \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

### Direct archive URL with `--sha256-url`

```bash
llmctxbench dataset fetch \
  --dataset-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.tar.gz \
  --id ctxbench/lattes \
  --version 0.1.0 \
  --sha256-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.sha256
```

### Local archive with `--sha256-file`

```bash
llmctxbench dataset fetch \
  --dataset-file ./downloads/ctxbench-lattes-v0.1.0.tar.gz \
  --id ctxbench/lattes \
  --version 0.1.0 \
  --sha256-file ./downloads/ctxbench-lattes-v0.1.0.sha256
```

### Local unpacked directory

```bash
llmctxbench dataset fetch --dataset-dir ./datasets/lattes
```

Rules:

- `--descriptor-url` and `--descriptor-file` are the canonical self-describing acquisition sources
- `--dataset-url` requires either `--sha256` or `--sha256-url`
- `--dataset-file` requires either `--sha256` or `--sha256-file`
- `--dataset-url` and `--dataset-file` also require `--id` and `--version`
- `--dataset-dir` does not require checksum material
- checksum verification happens before extraction
- missing checksum input fails fast
- invalid checksum fails before extraction or materialization

Archive extraction is safety-checked. The fetch command rejects:

- path traversal entries
- absolute paths
- unsafe symlinks
- unsafe hardlinks
- device nodes
- FIFOs
- other special files

After extraction, LLMContextBench requires exactly one dataset manifest. It accepts either:

- a single top-level directory containing the dataset package
- files directly at the archive root

It fails if there is no manifest, or more than one manifest.

## Conflict and ambiguity handling

### Missing dataset

If `llmctxbench plan` cannot resolve `dataset.id@version` locally, it fails and tells you to run:

```bash
llmctxbench dataset fetch --descriptor-url <url>
```

### Cache reuse and replacement

If the requested dataset identity, version, and content identity are already cached, `llmctxbench dataset fetch`
prints the existing materialized path and exits without downloading, extracting, or overwriting.

If the same dataset identity and version are cached with conflicting content:

- fetch fails by default
- `--force` allows replacement only after checksum verification, safe extraction, and manifest validation succeed

The materialized path is semantic:

```text
<cache-dir>/<dataset-id>/<datasetVersion>/
```

### Ambiguous dataset

If the local cache contains multiple materializations for the same `datasetId` and requested
version but with conflicting provenance, planning and inspection fail with an ambiguity error.

Resolution options:

1. Remove the conflicting cache entry outside the benchmark workflow.
2. Re-fetch the intended dataset from the authoritative origin.
3. Switch the experiment to a local `root` reference if you are intentionally using a one-off local copy.

### Identity/version mismatch

If optional identity or dataset-version validation overrides are provided and the fetched or
unpacked dataset manifest does not match them, the fetch operation fails and nothing is materialized into the cache.

## No implicit network rule

The lifecycle commands below do not acquire datasets:

- `llmctxbench plan`
- `llmctxbench execute`
- `llmctxbench eval`
- `llmctxbench export`
- `llmctxbench metrics`
- `llmctxbench status`

Consequences:

- `plan` fails if a referenced `dataset.id@version` is not already materialized locally
- `execute` and `eval` fail if required local dataset artifacts are missing
- `export` and `status` work from existing artifacts and preserved provenance only

## Provenance in artifacts

Dataset provenance is preserved across canonical artifacts as a nested `dataset` object with:

- `id`
- `version` (the dataset version selected at planning time)
- `origin`
- `resolvedRevision`
- `contentHash`
- `materializedPath`

## Cache root selection

Dataset commands share the same cache-root selection rules:

- `--cache-dir <path>` overrides everything else
- `CTXBENCH_DATASET_CACHE` applies when `--cache-dir` is omitted
- otherwise LLMContextBench uses the default dataset cache location

Use the same cache root for `llmctxbench dataset fetch`, `llmctxbench dataset inspect`, and `llmctxbench plan`
when you are not using the default location.

Flat export adds:

- `dataset_id`
- `dataset_version`
