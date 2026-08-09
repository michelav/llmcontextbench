# CLI Architecture

## Purpose

The CLI exposes both dataset-management commands and lifecycle commands.

```text
llmctxbench dataset fetch
llmctxbench dataset inspect
llmctxbench plan
llmctxbench execute
llmctxbench eval
llmctxbench export
llmctxbench metrics
llmctxbench status
```

The CLI should remain thin: parse arguments, resolve selectors, and delegate to command handlers.

## CLI component structure

```mermaid
flowchart TB
    CLI["llmctxbench CLI<br/>argument parsing"]
    Selectors["Selector parser"]
    DatasetFetch["dataset fetch command"]
    DatasetInspect["dataset inspect command"]
    Plan["plan command"]
    Execute["execute command"]
    Eval["eval command"]
    Export["export command"]
    Metrics["metrics command"]
    Status["status command"]
    Core["Benchmark core"]
    Store["Artifact store / cache"]

    CLI --> Selectors
    CLI --> DatasetFetch
    CLI --> DatasetInspect
    CLI --> Plan
    CLI --> Execute
    CLI --> Eval
    CLI --> Export
    CLI --> Metrics
    CLI --> Status

    DatasetFetch --> Store
    DatasetInspect --> Store
    Plan --> Core
    Execute --> Core
    Eval --> Core
    Export --> Store
    Metrics --> Store
    Status --> Store
    Core --> Store
```

## Command groups

### Dataset-management commands

| Command | Responsibility |
|---|---|
| `llmctxbench dataset fetch` | Materialize a dataset into the local cache. |
| `llmctxbench dataset inspect` | Validate and report capability/provenance for a local or cached dataset reference. |

### Lifecycle commands

| Command | Responsibility |
|---|---|
| `llmctxbench plan` | Expand experiment into trials. |
| `llmctxbench execute` | Execute trials and collect responses. |
| `llmctxbench eval` | Evaluate responses. |
| `llmctxbench export` | Build analysis-ready files. |
| `llmctxbench metrics` | Compute canonical effectiveness/efficiency/robustness/evaluation-reliability/observability metrics from existing run artifacts. |
| `llmctxbench status` | Report progress from existing artifacts. |

Lifecycle commands do not fetch remote datasets implicitly.

## Common selectors

Recommended selectors:

```text
--model
--provider
--instance
--task
--strategy
--format
--repetition
--trial
--trial-file
--status
--judge
```

## Nested subparser pattern

The parser shape is:

```text
llmctxbench
  dataset
    fetch
    inspect
  plan
  execute
  eval
  export
  metrics
  status
```

`llmctxbench dataset` requires a subcommand.

## Historical migration reference

The table below is a migration reference only. Public CLI commands and selectors use the target
forms only and do not expose aliases. For the authoritative artifact reference, see
`docs/architecture/artifact-contracts.md`.

| Current | Target |
|---|---|
| `copa` | `ctxbench` |
| `query` | `execute` |
| `exec` | prohibited abbreviation; use `execute` |
| `queries.jsonl` | `trials.jsonl` |
| `answers.jsonl` | `responses.jsonl` |
| `--question` | `--task` |
| `--repeat` | `--repetition` |
| `--ids` | `--trial` |
