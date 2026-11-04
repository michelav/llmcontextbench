# AGENTS.md

## Repository purpose

This repository is part of a PhD research project on context provisioning for LLM-based systems.
The benchmark compares inline context, local function calling, local MCP, and remote MCP across
answer quality, token cost, execution time, tool usage, traceability, judge agreement, and
reproducibility.

## Expected agent behavior

Work like a careful research software engineer: stay scoped, minimize context usage, inspect before
editing, prefer small patches, verify with targeted tests, and preserve reproducibility.

- Do not make broad architectural changes unless explicitly requested.
- Do not silently change experiment semantics or generated artifact formats.
- If ambiguity could affect experiment validity, clarify before editing; otherwise make the
  smallest safe change.

Spec-driven development (`specs/`, worklogs, usage tracking) is not in active use. Do not treat any
`specs/*` entry as an in-progress plan unless the user says so. When it is requested, follow
`docs/development/spec-workflow.md`.

## Workflow and naming

The workflow is `plan -> execute -> eval -> export -> metrics`; `status` reports progress. Use the
installed `llmctxbench` command; the Python package/import path and dataset-namespace identifiers
(`ctxbench/lattes`, `ctxbench/repoqa`) remain `ctxbench`. Do not introduce obsolete command names in
docs or scripts.

Target public terms: `execute`, `trials.jsonl`, `responses.jsonl`, `trialId`, `taskId`, `response`.
Legacy internal names such as `copa` are migration details; new code and docs use target terms
unless working on compatibility. If artifact names or formats change, the spec must define
canonical vs. derived artifacts, migration impact, and schema compatibility.

## Large artifacts

Do not load large benchmark artifacts (JSONL outputs, traces, raw/clean HTML, parsed or blocks JSON)
in full. Inspect targeted records or summaries; for repeated analysis, use a small script.

## Coding conventions

Prefer explicit, readable code over clever abstractions. Keep CLI, planning, execution, strategy,
provider, MCP, evaluation, export, and analysis concerns separated; keep dataset- and
provider-specific behavior out of generic logic. Follow existing typing and naming conventions.

## Metric rules

Preserve metric provenance: `reported` (provider/runtime), `measured` (benchmark instrumentation),
`derived` (deterministic computation), `estimated` (heuristics or assumptions), or `unavailable`.
Never present estimates as reported/measured, or unavailable values as zero unless zero was
observed.

## Commands, safety, and cost

- Run targeted checks (`pytest -k {cli|plan|execute|eval|export}`); run formatting or linting only
  if configured.
- Do not install dependencies or change lockfiles unless requested.
- Never run `llmctxbench execute` or `llmctxbench eval` against real providers unless explicitly
  requested; state likely cost or risk first. Prefer dry runs, status checks, fixtures, or mocks.

## Final response

Briefly report the change, affected files, and relevant checks. Mention assumptions or risks only
when material; if checks were not run, say so.
