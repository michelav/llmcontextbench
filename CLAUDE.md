# CLAUDE.md

## Project context

This repository supports my PhD research on context provisioning strategies for LLM-based systems.
The goal is to evaluate how strategies affect answer quality, token cost, execution time, tool usage,
observability, and reproducibility.

Core strategies:

- `inline`: context is inserted directly into the prompt.
- `local_function`: local tool/function calling controlled by the benchmark.
- `local_mcp`: local MCP runtime controlled by the benchmark.
- `remote_mcp`: remote MCP server used as a context provider.

CLI command is `llmctxbench` (Python package/import path remains `ctxbench`):
`plan`, `execute`, `eval`, `export`, `metrics`, `status`. Use only these names in code and docs;
do not document obsolete commands unless explicitly writing migration notes.

## Working style

- Propose a short plan for non-trivial changes; proceed directly only when implementation was
  explicitly requested or the change is clearly mechanical.
- Do not explore the whole repository unless explicitly asked.
- No opportunistic refactors; prefer focused changes.
- Do not change public file formats, experiment/dataset schemas, CLI behavior, or output artifact
  names unless explicitly requested.

<!-- SPECKIT START -->
Spec-driven development (`specs/`, worklogs, usage tracking) is not in active use. Do not treat any
`specs/*` entry as an in-progress plan unless the user says so. When it is requested, follow
`docs/development/spec-workflow.md`.
<!-- SPECKIT END -->

## Large benchmark artifacts

Never read full large artifacts into context unless explicitly requested: `responses.jsonl`,
`evals.jsonl`, `judge_votes.jsonl`, trace files under `traces/`, Lattes HTML, full parsed JSON
datasets. Inspect samples with `head`, `jq`, or `rg`, and aggregate with small scripts outside the
conversation (see the `inspect-large-artifacts` skill).

## Validation

- Focused tests: `pytest -k {cli|plan|execute|eval|export}` by area. If unsure, locate tests with
  `rg "def test_" tests`.
- Do not run the full benchmark or call real LLM providers unless explicitly requested.
  Prefer fixtures, mocks, and small local examples.

## Research constraints

Preserve separation between answer-generation model usage, judge model usage, trial traces,
evaluation traces, and aggregate exported results. Never mix execution-phase and evaluation-phase
token usage.

- Cost: distinguish input, output, total, cached (when available), reasoning (when available)
  tokens, and tool-call overhead (when observable).
- Accuracy: distinguish individual judge votes, majority outcome, unanimous outcome, correctness,
  and completeness.
- Docs: keep aligned with the actual CLI, include exact commands, and avoid overstating what the
  benchmark proves.

## Architecture constraints

- Keep strategy logic separate from model-provider adapters; adapters do not own strategy decisions.
- Keep dataset-specific logic isolated from generic execution logic; no Lattes-specific behavior in
  generic ctxbench components.

## Metric provenance

When adding, changing, exporting, or analyzing metrics, classify each value as:

- `reported`: returned by a provider API, SDK, or authoritative runtime;
- `measured`: measured directly by benchmark-controlled instrumentation;
- `derived`: computed deterministically from reported or measured values;
- `estimated`: approximated through heuristics, tokenizers, assumptions, or incomplete information;
- `unavailable`: not available and not responsibly estimated.

Never present estimated values as reported or measured. Never represent unavailable as zero unless
zero is a valid observed value.

## Done criteria

Done means: the behavior is implemented (or the analysis is complete), minimal relevant checks ran
when possible, and the final response states key validation commands and results plus limitations
or unverified assumptions.

## Compacting

Preserve: task goal, accepted plan, files read and changed, design decisions, test results,
remaining problems. Drop: long logs, repeated discussion, obsolete alternatives, JSONL snippets,
traces, dataset content.
