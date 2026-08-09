# AGENTS.md

## Repository purpose

This repository is part of a PhD research project on context provisioning for LLM-based systems.

The benchmark compares different ways of giving context to LLMs, including inline context, local function calling, local MCP, and remote MCP.

Primary evaluation dimensions:

- answer quality;
- token cost;
- execution time;
- tool usage;
- traceability;
- judge agreement;
- reproducibility.

## Expected agent behavior

Work like a careful research software engineer.

Default behavior:

- stay scoped;
- minimize context usage;
- inspect before editing;
- prefer small patches;
- verify with targeted tests;
- preserve reproducibility.

Do not make broad architectural changes unless explicitly requested.
Do not silently change experiment semantics.
Do not silently change generated artifact formats.
Do not run expensive experiments unless explicitly requested.

## Lightweight SDD workflow

Use the lightest process that preserves research validity.

- **Level 0 — Direct change**: typo, local fix, small docs update. No spec required.
- **Level 1 — Lightweight spec**: small behavior change with limited impact. Use spec-lite and direct implementation slices.
- **Level 2 — Planned change**: touches CLI, artifacts, tests, docs, or schemas. Use spec-lite, plan, slices, and focused tasks.
- **Level 3 — Full SDD**: architecture, metrics, datasets, evaluation, breaking changes, provider behavior. Use full spec, plan review, tasks, slices, and audit.

Do not use the full Spec Kit flow for every small change.

## Implementation slices

Before generating or implementing tasks for a non-trivial spec, propose implementation slices.

Each slice should include:

- goal;
- files likely affected;
- focused tests/checks;
- dependencies;
- risks;
- suggested commit message.

Implement one slice at a time.
Prefer one commit per green slice, not one commit per task.

## Process logging

For Level 2 or Level 3 specs, maintain lightweight process logs when useful:

- `worklog.md` for human-readable development history;
- `usage.jsonl` for structured process metrics.

Log meaningful steps, not every prompt.

Useful events:

- spec-created;
- plan-reviewed;
- tasks-generated;
- tasks-regrouped;
- slice-implemented;
- diff-reviewed;
- audit-run;
- spec-completed.

When token usage is not available, record `token_provenance: "unavailable"` rather than inventing values.

## Prompt interpretation

For every task, infer and preserve:

- Goal: what behavior or artifact should change.
- Context: which files, commands, examples, or errors are relevant.
- Constraints: what must not change.
- Done when: what verification proves the task is complete.

If the request is ambiguous and implementation could affect experiment validity, ask before editing.
For simple mechanical changes, proceed with the smallest safe change.

## Project workflow

The benchmark workflow is:

```text
experiment config
  -> llmctxbench plan
  -> trials.jsonl + manifest.json
  -> llmctxbench execute
  -> responses.jsonl + execution traces
  -> llmctxbench eval
  -> evals.jsonl + judge_votes.jsonl + eval traces
  -> llmctxbench export
  -> results.csv
  -> llmctxbench metrics
  -> metrics/ (dimension CSVs + summary.json)
```

Use current CLI commands:

```bash
llmctxbench plan
llmctxbench execute
llmctxbench eval
llmctxbench export
llmctxbench metrics
llmctxbench status
```

Do not introduce documentation or scripts using obsolete command names.

## Current and target naming

The implementation may still contain legacy internal names such as `copa`.

The target public architecture uses `ctxbench`, `execute`, `trials.jsonl`, `responses.jsonl`,
`trialId`, `taskId`, and `response`. The installed CLI command is `llmctxbench`; the Python
package/import path and dataset-namespace identifiers (`ctxbench/lattes`, `ctxbench/repoqa`)
remain `ctxbench`.

Treat legacy names as migration details, not permanent public concepts. New specs, docs, examples,
and code should prefer target terminology unless explicitly working on compatibility.

If artifact names or formats change, the specification must define canonical vs. derived
artifacts, migration impact, and schema compatibility.

## File and artifact discipline

Large benchmark artifacts must not be loaded entirely into the conversation.

Avoid reading complete files such as:

- `responses.jsonl`
- `evals.jsonl`
- `judge_votes.jsonl`
- `results.csv` when large
- `traces/**/*.json`
- `raw.html`
- `clean.html`
- large `parsed.json`
- large `blocks.json`

Use targeted inspection:

```bash
head -n 5 responses.jsonl
jq -c 'select(.trialId == "TRIAL_ID")' responses.jsonl
rg '"taskId":"q_sup"' responses.jsonl
rg '"strategy":"inline"' responses.jsonl
```

For repeated analysis, create or use small scripts instead of pasting data into the conversation.

## Coding conventions

Prefer explicit, readable code over clever abstractions.

Keep benchmark concerns separated:

- CLI parsing;
- experiment planning;
- trials execution;
- strategy orchestration;
- model provider adapters;
- MCP runtime;
- evaluation;
- export;
- analysis utilities.

Avoid coupling generic benchmark code to the domain-specific dataset.
Avoid coupling provider-specific behavior to strategy-independent logic.
Use typed data structures where the project already uses them.
Preserve existing naming conventions unless a spec changes them.

## Metric rules

When adding, changing, exporting, or analyzing metrics, preserve metric provenance.

Use the simplest sufficient classification:

- `reported`: returned by a provider API, SDK, or authoritative runtime;
- `measured`: measured directly by benchmark-controlled instrumentation;
- `derived`: computed deterministically from reported or measured values;
- `estimated`: approximated through heuristics, tokenizers, assumptions, or incomplete information;
- `unavailable`: not available and not responsibly estimated.

Estimated metrics must not be presented as reported or measured values. Unavailable metrics
must not be represented as zero unless zero is a valid observed value. Avoid adding extra
confidence scores or complex metric taxonomies unless required by an accepted specification.

## Commands

Use targeted commands first.

Discover tests:

```bash
rg "def test_" tests
```

Run focused tests:

```bash
pytest -k plan
pytest -k execute
pytest -k eval
pytest -k export
pytest -k metrics
pytest -k cli
```

Run formatting or linting only if configured in the repository.

Do not install new dependencies without asking.
Do not change lockfiles unless dependency changes are explicitly requested.

## Safety and cost controls

Never run these commands against real providers unless explicitly requested:

```bash
llmctxbench execute
llmctxbench eval
```

Before running provider-backed commands, state the likely cost or risk.

Prefer dry runs, planning, status checks, fixture-based tests, or mocked providers.

## Pull request / final response expectations

When finished, report:

- summary of what changed;
- files changed;
- commands run;
- test results;
- assumptions;
- remaining risks.

If no tests were run, say so clearly and explain why.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan.
<!-- SPECKIT END -->
