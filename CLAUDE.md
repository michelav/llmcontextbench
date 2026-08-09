# CLAUDE.md

## Project context

This repository supports my PhD research on context provisioning strategies for LLM-based systems.

The main goal is to evaluate how different context provisioning strategies affect answer quality, token cost, execution time, tool usage, observability, and reproducibility.

Core strategies:

- `inline`: context is inserted directly into the prompt.
- `local_function`: local tool/function calling controlled by the benchmark.
- `local_mcp`: local MCP runtime controlled by the benchmark.
- `remote_mcp`: remote MCP server used as a context provider.

Core benchmark workflow (CLI command: `llmctxbench`; Python package/import path remains `ctxbench`):

- `llmctxbench plan`
- `llmctxbench execute`
- `llmctxbench eval`
- `llmctxbench export`
- `llmctxbench metrics`
- `llmctxbench status`

The benchmark artifacts can be large. Be careful with token usage and context size.

## Working style

Use an economical context strategy.

Before editing code:

1. Identify the smallest relevant file set.
2. Use `rg`, `find`, `git diff`, `jq`, or small scripts before opening large files.
3. Read only the necessary functions, classes, or file ranges.
4. Propose a short plan for non-trivial changes.
5. Proceed directly only when the user explicitly requested implementation or the change is clearly mechanical.

Do not explore the whole repository unless explicitly asked.
Prefer focused changes over broad refactoring.
Do not perform opportunistic refactors.
Do not change public file formats, experiment schemas, dataset schemas, CLI behavior, or output artifact names unless explicitly requested.

## Lightweight SDD mode

Prefer concise specs and plans unless the change affects architecture, artifacts, metrics,
evaluation, datasets, or provider behavior.

Use workflow levels:

- Level 0: direct edit.
- Level 1: lightweight spec.
- Level 2: lightweight spec + plan with implementation slices.
- Level 3: full SDD, audits, worklog, and usage tracking.

For most implementation work, use compact prompts:

```text
Spec: <path>
Slice: <goal>
Tasks: <ids>
Do: <short list>
Don't: provider calls, full benchmark, opportunistic refactors
Run: focused tests
Report: files, tests, risks
```

## Slice planning

When asked to plan a spec, include an **Implementation Slices** section before generating tasks.

Each slice should include:

- goal;
- likely files;
- focused validation;
- dependencies;
- suggested commit message.

Do not produce a long flat task list without grouping tasks into reviewable slices.

## Process logging

For Level 2 or Level 3 changes, update process logs when useful:

- `worklog.md`: human-readable timeline, decisions, iterations, slices, validation, lessons.
- `usage.jsonl`: structured process metrics.

Do not log every prompt.

Use `token_provenance`:

- `reported`: tool reported usage.
- `estimated`: usage estimated with a documented heuristic.
- `unavailable`: usage not available.

Prefer `unavailable` over false precision.

## Large files and benchmark artifacts

Never read full large artifacts into context unless explicitly requested.

Avoid opening entire files such as:

- `responses.jsonl`
- `evals.jsonl`
- `judge_votes.jsonl`
- large trace files under `traces/`
- large HTML curriculum files
- full parsed JSON dataset files

Instead, inspect samples with commands like:

```bash
head -n 3 responses.jsonl
jq -c 'select(.trialId == "TRIAL_ID")' responses.jsonl
rg '"taskId":"q_sup"' responses.jsonl
python scripts/inspect_trial.py --trial-id TRIAL_ID
```

When analyzing benchmark outputs, prefer small scripts that aggregate data outside the conversation.

## Development rules

Use the smallest verification command that makes sense.

For CLI changes:

```bash
pytest -k cli
```

For planning changes:

```bash
pytest -k plan
```

For trial execution changes:

```bash
pytest -k execute
```

For evaluation changes:

```bash
pytest -k eval
```

For export changes:

```bash
pytest -k export
```

If the exact test target is unknown, locate tests first:

```bash
rg "def test_.*export|def test_.*eval|def test_.*execute|def test_.*query" tests
```

Do not run the full benchmark unless explicitly requested.
Do not call real LLM providers unless explicitly requested.
Prefer fixtures, mocks, and small local examples.

## Research constraints

Preserve separation between:

- answer-generation model usage;
- judge model usage;
- trial traces;
- evaluation traces;
- aggregate exported results.

Do not mix execution-phase token usage with evaluation-phase token usage.

When discussing cost, distinguish:

- input tokens;
- output tokens;
- total tokens;
- cached tokens when available;
- reasoning tokens when available;
- tool-call overhead when observable.

When discussing accuracy, distinguish:

- individual judge votes;
- majority outcome;
- unanimous outcome;
- correctness;
- completeness.

## Architecture constraints

Keep strategy logic separate from model-provider adapters.
Provider adapters should not own benchmark strategy decisions.
Dataset-specific logic should remain isolated from generic benchmark execution logic.
Avoid hardcoding Lattes-specific behavior in generic ctxbench components.

## Documentation rules

When updating documentation:

- keep it aligned with the actual CLI;
- prefer concise reproducibility instructions;
- include exact commands;
- avoid historical implementation details unless needed;
- avoid overstating what the benchmark proves.

Use current command names:

- `llmctxbench plan`
- `llmctxbench execute`
- `llmctxbench eval`
- `llmctxbench export`
- `llmctxbench metrics`
- `llmctxbench status`

Do not document obsolete commands unless explicitly writing migration notes.

## Metric rules

When adding, changing, exporting, or analyzing metrics, preserve metric provenance.

Use the simplest sufficient classification:

- `reported`: returned by a provider API, SDK, or authoritative runtime;
- `measured`: measured directly by benchmark-controlled instrumentation;
- `derived`: computed deterministically from reported or measured values;
- `estimated`: approximated through heuristics, tokenizers, assumptions, or incomplete information;
- `unavailable`: not available and not responsibly estimated.

Estimated metrics must not be presented as reported or measured values. Unavailable metrics
must not be represented as zero unless zero is a valid observed value.

## Done criteria

A task is done only when:

- the requested behavior is implemented or the analysis is complete;
- the relevant minimal tests or checks were run, when possible;
- the final response lists files changed;
- the final response lists commands run and their result;
- limitations or unverified assumptions are stated clearly.

## Compacting instructions

When context grows, compact aggressively.

Preserve:

- current task goal;
- active spec and slice;
- accepted plan;
- files read;
- files changed;
- important design decisions;
- commands run;
- test results;
- remaining problems.

Drop:

- long logs;
- repeated discussion;
- obsolete alternatives;
- full JSONL snippets;
- full traces;
- full dataset content.

<!-- SPECKIT START -->
Spec-driven development (the `specs/` folders, worklogs, and usage tracking described
above) is not currently in active use for day-to-day changes. Spec 004
(`specs/004-dataset-package-capabilities/plan.md`) was the last actively worked plan and
is effectively complete. Do not treat any `specs/*` entry as an in-progress active plan
unless the user explicitly says otherwise for that session.
<!-- SPECKIT END -->
