# 0005. Two entry paths, one canonical definition form

- **Status:** accepted
- **Date:** 2026-11-17

## Context

Researchers write experiments both as definition files and in Python. A separate set of
API-only classes would drift from the file format, and results would depend on how an
experiment was written.

## Decision

An adaptive experiment is either read from a definition file or built in code with the section
builders (`Model`, `Configuration`, `Candidate`, `PolicyRef`, `Window`, `Goal`,
`Acceptance`, `SignalRef`, `Disturbance`, and the `Scenario` helper). Both are first-class
and converge on one stored form: `AdaptiveExperiment` normalises every section to the canonical
mapping of the v4 schema. A builder validates by passing its mapping through the same schema
fragment and normaliser as a file, so a value invalid in a file is invalid in a builder, with an
error naming the same field. The plan, `resolved.json` and the fingerprint are computed from the
stored form only.

## Consequences

- `plan(code-built)` and `plan(path)` produce byte-identical artifacts for equal experiments.
- New sections need one schema fragment and one normaliser; the builder follows.
- Builders are input types, not a second representation; reading a section returns the mapping.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), requirement R13 (section 2.2) and the public API (section 9.1, "Two
  entry paths, one stored form").
- [acceptance report: workload builder and experiments in code](../../sprints/adaptive-framework/acceptance/wp-g-acceptance.md).
