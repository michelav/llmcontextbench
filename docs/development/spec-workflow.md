# Lightweight SDD Workflow

This repository uses a lightweight, slice-first specification workflow.

## Workflow levels

Use the lightest process that preserves research validity.

| Level | Use for | Process |
|---|---|---|
| Level 0 — Direct change | typo, local fix, small docs edit | edit → focused check → commit |
| Level 1 — Lightweight spec | small behavior change with limited impact | spec-lite → implementation slice → focused check |
| Level 2 — Planned change | CLI, artifacts, tests, docs, schemas | spec-lite → plan with slices → tasks by slice → implement slices |
| Level 3 — Full SDD | architecture, metrics, datasets, evaluation, breaking changes, provider behavior | full spec → plan review → tasks by slice → audits |

Do not use full Spec Kit flow for every small change.

## Recommended flow for Level 2/3

1. Create a concise spec.
2. Review the spec for scope and acceptance criteria.
3. Create a plan with implementation slices.
4. Review slices before generating tasks.
5. Generate tasks grouped by slice.
6. Implement one slice at a time.
7. Run focused provider-free checks.
8. Commit after each green slice.
9. Update `worklog.md` for major steps.
10. Update `usage.jsonl` when usage data is available or explicitly unavailable.

## Spec style

Prefer direct specs:

- Goal
- Scope
- Out of Scope
- Requirements
- Acceptance Scenarios in Given/When/Then
- Impact
- Compatibility / Migration
- Validation
- Dependencies
- Risks
- Open Questions

Use Given/When/Then only for observable acceptance scenarios, not for the whole spec.

## Implementation slices

Each slice should include:

- goal;
- likely files;
- validation;
- dependencies;
- suggested commit message.

A good slice ends in a green checkpoint and is easy to review.

## Process logging

For Level 2/3 changes, create or update:

- `worklog.md`: human-readable development history.
- `usage.jsonl`: structured metrics, one JSON object per important event.

Do not log every prompt. Log meaningful steps:

- spec-created;
- plan-created;
- plan-reviewed;
- tasks-generated;
- tasks-regrouped;
- slice-implemented;
- diff-reviewed;
- audit-run;
- spec-completed.

Token usage may be unavailable. Do not invent token counts. Record `token_provenance` as
`reported`, `estimated` (documented heuristic), or `unavailable`; prefer `unavailable` over false precision.

## Compact slice prompt

```text
Spec: <path>
Slice: <goal>
Tasks: <ids>
Do: <short list>
Don't: provider calls, full benchmark, opportunistic refactors
Run: focused tests
Report: files, tests, risks
```

## Converting existing specs to lite format

Existing specs may be converted to the lite format when they are too verbose for their risk level.

Recommended flow:

1. Use `docs/prompts/spec-kit/review-spec-for-lite.md`.
2. If conversion is safe, use `docs/prompts/spec-kit/convert-spec-to-lite.md`.
3. Review the diff with `docs/prompts/spec-kit/compare-lite-spec.md`.
4. Update `plan.md` or `tasks.md` only if the conversion changed scope, requirements, or acceptance criteria.

Do not convert a spec if doing so would hide a public contract, migration decision, metric rule, artifact change, or research constraint.
