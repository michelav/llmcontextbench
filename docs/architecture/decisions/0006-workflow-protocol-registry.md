# 0006. One `Workflow` protocol behind a registry

- **Status:** accepted
- **Date:** 2026-11-16

## Context

Benchmark and adaptive workflows shared services but no contract. Every command branched on the
workflow kind by hand, and a programmatic API would have had to repeat those branches.

## Decision

Both workflows implement one `Workflow` protocol (`core/workflow.py`): load definition, plan,
status, execute, prepare responses, responses, metric tables, write metrics. The protocol has no
method bodies and no shared state; common behaviour stays in services used by composition, and
no `Study`-like parent type is introduced. `WorkflowRegistry` is the only place that reads the
workflow kind. Commands and `ctxbench.api` dispatch through it and contain no kind comparison.
Kind-specific operations (`requests`, `attempts`, `trials`) are outside the protocol.

## Consequences

- A third workflow kind is one implementation and one registry entry.
- A test enforces that no kind comparison exists outside the registry.
- "Trial" and "request" remain different units; the protocol does not unify them.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), requirement R24 (section 2.2) and the workflow interface (section 5.4).
- [Architecture assessment and plan](../../sprints/adaptive-framework/architecture-assessment-and-plan.md).
