# CTXBench Architecture

This document is the entry point for the CTXBench architecture documentation. It's loosely organized into [C4 Model](https://c4model.com/) style but with a few other structures added when necessary.

CTXBench is a Python-based command-line benchmark framework for evaluating context provisioning strategies in LLM-based systems. It is a research tool: the architecture prioritizes simplicity, reproducibility, explicit artifacts, and comparability between strategies.

## Architectural scope

CTXBench supports experiments where a stable set of dataset instances and tasks is executed across different models, context formats, and context provisioning strategies.

The canonical workflow is:

```text
experiment.json
   ↓
ctxbench plan
   ↓
trials.jsonl + manifest.json
   ↓
ctxbench execute
   ↓
responses.jsonl + traces/executions/
   ↓
ctxbench eval
   ↓
evals.jsonl + judge_votes.jsonl + evals-summary.json + traces/evals/
   ↓
ctxbench export
   ↓
results.csv
```

## Technology baseline

The current implementation is a Python project. The current package metadata still uses the legacy name `copa`, but the public CLI and artifact contract use `ctxbench`. The internal package path remains `src/copa/` in the current repository layout.

| Concern | Decision |
|---|---|
| Language | Python |
| Runtime | Python 3.11–3.12 |
| CLI style | Python command-line application |
| Packaging | `pyproject.toml` / setuptools, compatible with uv and Nix workflows |
| Main data formats | JSONL, JSON, CSV |
| LLM integrations | OpenAI, Google Gemini, Anthropic |
| MCP integration | FastMCP/local MCP runtime and remote MCP-compatible servers |
| Analysis tools | notebooks, pandas, DuckDB, spreadsheets |

## Architectural principles

### Simplicity first

The core concepts should remain small and stable:

```text
dataset → instance → task → trial → response → evaluation → result
```

New architectural elements should be added only when they clarify reproducibility, extensibility, or comparison.

### Domain neutrality

The framework should not assume that every dataset is a Lattes curriculum, a document, or a Q/A benchmark.

Framework-level terms should be generic:

```text
instance
task
trial
response
evaluation
trace
```

Dataset-specific adapters may use domain-specific terms internally.

### Explicit artifacts

Each phase writes inspectable artifacts. These artifacts make the experiment auditable and reproducible.

### Strategy comparability

The same experiment contract should support multiple context provisioning strategies:

```text
inline
local_function
local_mcp
remote_mcp
```

### Observability by design

CTXBench should record responses, metrics, traces, evaluation outcomes, and judge votes. For provider-managed or remote flows, missing observability should be recorded as an architectural property of the strategy.

## Main design decisions

| Decision | Rationale |
|---|---|
| Use `CTXBench` as public name | More general than the legacy `COPA` name and aligned with context provisioning. |
| Use `execute` instead of `query` or `run` | `query` is too narrow; `run` conflicts with run/runId wording. |
| Use `trial` instead of `run` | A trial is one planned experimental execution. |
| Use `response` instead of `answer` | Not every task is Q/A. |
| Keep `instance` | It is domain-neutral and works for curricula, documents, traces, repositories, tickets, images, etc. |
| Use `remote_mcp` instead of `mcp` | `mcp` alone is ambiguous because local MCP also exists. |
| Use C4 deployment for runtime topology | Runtime placement, local files, providers, and remote MCP boundaries are deployment concerns. |
| Use C4 dynamic diagrams for strategy flows | Tool loops and MCP interactions are runtime behaviors, not static component structure. |

## Documentation structure

This documentation follows the C4 organization where it helps, without forcing unnecessary fragmentation.

| File | Purpose |
|---|---|
| `artifact-contracts.md` | Authoritative artifact set, classification, provenance taxonomy, and no-alias policy. |
| `vocabulary.md` | Canonical terminology and naming rules. |
| `workflow.md` | User workflow, phases, commands, artifacts, and strategy overview. |
| `cli-architecture.md` | CLI architecture, command contract, selectors, and migration notes. |
| `system-context.md` | C4 Level 1: system context. |
| `container.md` | C4 Level 2: containers/modules. |
| `component.md` | C4 Level 3: internal components. |
| `deployment.md` | C4 supplementary: physical/runtime deployment, including local and remote MCP. |
| `dynamic.md` | C4 supplementary: runtime interaction flows for each strategy. |

## C4 usage in this project

CTXBench is not a commercial distributed platform, so the C4 model should be used pragmatically.

Recommended use:

```text
System Context: who uses CTXBench and which external systems it touches.
Container: major executable/logical parts of the framework.
Component: internal modules that implement planning, execution, evaluation, export.
Deployment: where the Python runner, local files, providers, and MCP servers run.
Dynamic: how strategy-specific execution flows happen at runtime.
```

The deployment and dynamic diagrams are especially important for MCP because MCP is both:

```text
- a strategy being compared; and
- a runtime integration mechanism with client/server boundaries.
```

## Repository layout

### Framework repository

```text
ctxbench-cli/
├── README.md
├── pyproject.toml
├── src/
│   └── copa/
│       ├── cli.py
│       ├── commands/
│       ├── benchmark/
│       ├── dataset/
│       ├── strategies/
│       ├── models/
│       ├── mcp/
│       └── tracing/
├── tests/
├── docs/
└── examples/
```

### Dataset repository

```text
lattes/
├── README.md
├── dataset-card.md
├── DATASET-TERMS.md
├── NOTICE.md
├── CITATION.cff
├── dataset/
│   ├── tasks.json
│   └── tasks.instance.json
├── experiments/
│   └── lattes_baseline_001.json
├── scripts/
├── tools/
├── datasets/
├── outputs/
├── analysis/
│   └── notebooks/
├── downloads/
└── dist/
```

### Experiment output layout

```text
outputs/<experimentId>/
├── manifest.json
├── trials.jsonl
├── responses.jsonl
├── evals.jsonl
├── judge_votes.jsonl
├── evals-summary.json
├── results.csv
└── traces/
    ├── executions/
    │   └── <trialId>.json
    └── evals/
        └── <trialId>.json
```

## Historical migration reference

The table below is a migration reference only. The public CLI, selectors, artifact names, record fields, and strategy labels use the target forms only. Legacy names are not accepted as aliases.
For the authoritative artifact contract, see `docs/architecture/artifact-contracts.md`.

| Current | Target |
|---|---|
| `copa` | `ctxbench` |
| `query` | `execute` |
| `exec` | prohibited abbreviation; use `execute` |
| `queries.jsonl` | `trials.jsonl` |
| `answers.jsonl` | `responses.jsonl` |
| `runId` | `trialId` |
| `questionId` | `taskId` |
| `answer` | `response` |
| `mcp` | `remote_mcp` |
| `traces/queries/` | `traces/executions/` |
