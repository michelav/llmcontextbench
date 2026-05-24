# CTXBench

CTXBench is a benchmark runner for comparing how LLMs respond to dataset-backed tasks under different execution strategies.

The current codebase is centered on a simple idea:

- keep the task set fixed
- vary how the model accesses the source information
- evaluate the response qualitatively with either deterministic heuristics or a judge model

The repository currently ships a Lattes-based dataset and resource-oriented tool layer.

## What Changed

This version no longer uses the legacy evaluation model based on `exact`, `analytical`, `unanswerable`, numeric scores, or rubric dimensions.

The benchmark now uses:

- dataset instances organized by folder
- task-level `validation.type`
- instance-level `acceptedAnswers`, `contextRefs`, and `themes`
- qualitative evaluation only
- Lattes tools named as `get_<resource>`

## Core Concepts

### Dataset

A dataset is composed of:

- `ctxbench.dataset.json`
- `tasks.json`
- `tasks.instance.json`
- `context/<instanceId>/...`

`ctxbench.dataset.json` identifies the dataset package and its `datasetVersion`.

`tasks.json` defines the stable task catalog.

```json
{
  "datasetId": "example-lattes-v2",
  "tasks": [
    {
      "id": "q_phd_year",
      "statement": "In which year did the researcher obtain their PhD?",
      "tags": ["objective", "factual", "simple"],
      "validation": {
        "type": "heuristic",
        "schema": { "type": "number" }
      },
      "contextBlocks": ["education"]
    },
    {
      "id": "q_research_summary",
      "statement": "Summarize the researcher's main research areas based only on the available context.",
      "tags": ["subjective", "factual", "simple"],
      "validation": {
        "type": "judge"
      },
      "contextBlocks": ["summary", "research"]
    }
  ]
}
```

`tasks.instance.json` binds each task to one instance.

```json
{
  "datasetId": "example-lattes-v2",
  "instances": [
    {
      "instanceId": "5660469902738038",
      "contextBlocks": "context/5660469902738038/blocks.json",
      "tasks": [
        {
          "id": "q_phd_year",
          "acceptedAnswers": [1999]
        },
        {
          "id": "q_research_summary",
          "contextRefs": ["summary", "research"],
          "themes": ["software engineering", "distributed systems"]
        }
      ]
    }
  ]
}
```

Each instance lives in its own directory:

```text
dataset-root/
  ctxbench.dataset.json
  tasks.json
  tasks.instance.json
  context/
    5660469902738038/
      raw.html
      cleaned.html
      parsed.json
      blocks.json
```

Minimal package manifest:

```json
{
  "id": "ctxbench/lattes",
  "datasetVersion": "0.1.0",
  "manifestSchemaVersion": 1
}
```

### Validation Modes

Only two validation modes exist:

- `heuristic`
  Used when the answer can be checked deterministically against `acceptedAnswers`.
- `judge`
  Used when the answer must be evaluated qualitatively against `contextRefs` and `themes`.

Judge outputs are qualitative. They include one rating and one justification for each criterion:

- `groundedness`
- `correctness`
- `completeness`

There is no `score` and no `meanScore`.

### Experiment

An experiment selects:

- which dataset to use
- which instances and tasks to include via `scope`
- which provider/model pairs to run
- which strategies and formats to test
- whether evaluation is enabled

Example:

```json
{
  "id": "lattes_full_001",
  "output": "/abs/path/to/outputs",
  "dataset": "lattes/",
  "scope": {
    "instances": [],
    "tasks": []
  },
  "factors": {
    "model": [
      { "provider": "openai", "name": "gpt-5.4-nano" }
    ],
    "strategy": ["inline", "local_function", "local_mcp", "remote_mcp"],
    "format": ["json", "html"]
  },
  "evaluation": {
    "enabled": true,
    "judge": {
      "provider": "openai",
      "model": "gpt-5.4-mini",
      "temperature": 0
    }
  },
  "execution": {
    "repeats": 1
  }
}
```

`scope.instances` and `scope.tasks` act as filters. Empty lists mean "all available".

## Strategies

CTXBench currently supports four execution strategies.

### `inline`

The model receives the context artifact directly in the prompt.

Typical formats:

- `json` -> `parsed.json`
- `html` -> `raw.html`
- `cleaned_html` -> `cleaned.html`

### `local_function`

The benchmark controls the tool loop and exposes local Python tools directly.

For Lattes, the model interacts with:

- `get_profile`
- `get_expertise`
- `get_education`
- `get_projects`
- `get_supervisions`
- `get_experience`
- `get_academic_activities`
- `get_publications`
- `get_technical_output`
- `get_artistic_output`

### `local_mcp`

The benchmark still controls the loop, but the tools are accessed through a local MCP runtime.

### `remote_mcp`

The model provider controls the remote MCP interaction.

This path is less observable by design. Some metrics may be `null` because the benchmark cannot reliably observe provider-side tool execution.

## Lattes Tool Layer

The Lattes integration is resource-oriented.

The parsed curriculum in `parsed.json` is treated as the source of truth for tool-based execution. The tool surface is fixed and shared across `local_function`, `local_mcp`, and `remote_mcp`:

- `get_profile`
- `get_expertise`
- `get_education`
- `get_projects`
- `get_supervisions`
- `get_experience`
- `get_academic_activities`
- `get_publications`
- `get_technical_output`
- `get_artistic_output`

All tools are read-only. Temporal filters are exposed only where they make sense through `start_year` and `end_year`.

`get_supervisions` returns a grouped structure by supervision level:

- `masters`
- `doctoral`
- `undergraduate`
- `specialization`
- `others`

Each level contains:

- `completed`
- `ongoing`

This keeps the benchmark simpler and makes tool usage easier to compare across strategies.

## CLI

The installed CLI command is `ctxbench`.

### Fetch or Inspect a Dataset

For remote or cached datasets, use the dataset-management commands first:

```bash
ctxbench dataset fetch \
  --dataset-url https://github.com/ctxbench/lattes/releases/download/v0.1.0-dataset/ctxbench-lattes-v0.1.0.tar.gz \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --cache-dir ./.ctxbench/datasets

ctxbench dataset inspect ctxbench/lattes@0.1.0 --cache-dir ./.ctxbench/datasets
```

If your experiment already points to a local dataset root, skip fetch and inspect the root directly:

```bash
ctxbench dataset inspect datasets/lattes
```

### Plan an Experiment

```bash
ctxbench plan datasets/lattes/experiment.json \
  --output outputs/lattes_baseline_001 \
  --cache-dir ./.ctxbench/datasets
```

This writes:

- `manifest.json`
- `trials.jsonl`

### Execute Planned Trials

```bash
ctxbench execute outputs/lattes_baseline_001/trials.jsonl
```

This writes:

- `responses.jsonl`
- `traces/executions/<trialId>.json`

To force re-execution even when response artifacts already exist:

```bash
ctxbench execute outputs/lattes_baseline_001/trials.jsonl --force
```

`Ctrl-C` stops after the current item and leaves a checkpoint behind. Rerunning the same command resumes from the last completed `trialId`.

### Evaluate Responses

```bash
ctxbench eval outputs/lattes_baseline_001/responses.jsonl
```

Optional filters and selectors:

- `--model <id>`
- `--provider <name>`
- `--instance <instanceId>`
- `--task <taskId>`
- `--strategy <name>`
- `--format <name>`
- `--repetition <n>`
- `--trial-id <trialId>`
- `--trial-id-file <path>`
- `--judge <judgeId>`
- `--status <status>`

Batch evaluation uses the same `responses.jsonl` input:

```bash
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --judge juiz-gpt --batch
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --judge juiz-gpt --batch --wait --poll-interval 60
```

This writes:

- `evals.jsonl`
- `judge_votes.jsonl`
- `traces/evals/<trialId>.json`

### Export Analysis-Ready Results

```bash
ctxbench export outputs/lattes_baseline_001/evals.jsonl --to csv --output outputs/lattes_baseline_001/results.csv
```

### Inspect Progress

```bash
ctxbench status outputs/lattes_baseline_001
ctxbench status outputs/lattes_baseline_001 --by judge
```

## Output Artifacts

The benchmark persists:

- `manifest.json`
- `trials.jsonl`
- `responses.jsonl`
- `evals.jsonl`
- `judge_votes.jsonl`
- `results.csv`
- trace artifacts
- checkpoint files for interrupted execution or evaluation

JSONL artifacts are the default canonical source for analysis:

- `trials.jsonl`
- `responses.jsonl`
- `evals.jsonl`

Run responses include a compact `metricsSummary` separate from the raw trace. When a strategy does not expose a metric reliably, the field is stored as `null`.

Evaluation rows persist qualitative details and expose common fields directly (`outcome`, `correctness`, `completeness`, judge metadata, and evaluation token/duration fields) for easier CSV export.

Model factors can include a short `id` for filtering and reporting:

```json
{
  "provider": "openai",
  "id": "gpt-mini",
  "name": "gpt-5.4-mini-2026-03-17"
}
```

Execute and eval commands accept selectors:

```bash
ctxbench execute outputs/lattes_baseline_001/trials.jsonl --model gpt-mini --task q_sup
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --model gpt-mini --instance 5521922960404236
```

`--model` matches either the short `modelId` or the full model name. Selectors are available for provider, model, instance, task, strategy, format, repetition, and trial id. Evaluation also supports status and judge selection via `--judge` / `--not-judge`. Each selector also has a `--not-*` variant.

Evaluation can also use provider batch mode for supported judges. This keeps the input contract unchanged: pass the same `responses.jsonl` input used by synchronous evaluation.

```bash
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --judge juiz-claude --batch
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --judge juiz-gpt --batch --wait --poll-interval 60
ctxbench eval outputs/lattes_baseline_001/responses.jsonl --judge juiz-gemini --batch --batch-id batches/...
```

Batch evaluation currently supports one selected judge per invocation across Anthropic/Claude, OpenAI, and Google/Gemini judges, so use `--judge` when the experiment has more than one judge. The command writes `evaluation.batch.json` beside the experiment artifacts with the provider batch id and request manifest. Without `--wait`, the first command only submits the provider batch; run again with `--batch --wait` or `--batch --batch-id ... --wait` to collect and persist `evals.jsonl`, `evals-summary.json`, and optional CSV artifacts.

## Compatibility / Migration

This migration is intentionally breaking. The public CLI, selectors, artifact names, record fields, and strategy labels use one canonical form each. Legacy public names are documented here for migration only and are not accepted as aliases.

The installed command is `ctxbench`. The Python distribution metadata may still be named `copa` during this migration.

| Deprecated term | Target |
|---|---|
| `copa` | `ctxbench` |
| `query` | `execute` |
| `exec` | prohibited abbreviation; use `execute` |
| `queries.jsonl` | `trials.jsonl` |
| `answers.jsonl` | `responses.jsonl` |
| `runId` | `trialId` |
| `questionId` | `taskId` |
| `answer` | `response` |
| `mcp` | `remote_mcp` when referring to the remote MCP strategy |
| `--question` | `--task` |
| `--repeat` | `--repetition` |
| `--ids` | `--trial-id` |

## Repository Layout

- `src/copa/cli.py`
  CLI entrypoint
- `src/copa/commands/`
  `plan`, `execute`, `eval`, `export`, and `status` commands
- `src/copa/benchmark/`
  experiment schema, runspec generation, execution, evaluation, persistence
- `src/copa/ai/`
  model adapters, strategies, trace collection, runtimes
- `src/copa/dataset/`
  generic dataset loading and validation
- `src/copa/datasets/lattes/`
  section-based Lattes provider, tools, and MCP server
- `examples/datasets/`
  example dataset and experiment fixtures
- `datasets/lattes/`
  main Lattes dataset

## Development

Install the project in editable mode:

```bash
pip install -e .[dev]
```

RepoQA dataset generation uses a separate locked tool environment, not the main ctxbench environment:

```bash
cd tools/repoqa
uv sync --locked

cd ../..
tools/repoqa/repoqa_build_dataset --help
```

See [docs/repoqa.md](docs/repoqa.md) for the small dataset build command and `REPOQA_PYTHON` local clone override.

Run the test suite:

```bash
pytest -q
```

## Current Status

The refactor is aligned around simplicity:

- no compatibility with the legacy dataset/evaluation contract
- no score aggregation
- no rubric dimensions
- no broad domain-specific tool surface
- section-first retrieval for Lattes

If you are extending the benchmark, prefer preserving these constraints instead of reintroducing legacy abstractions.
