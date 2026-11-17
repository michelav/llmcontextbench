# 0001. Request-blind policies

- **Status:** accepted
- **Date:** 2026-11-16

## Context

An adaptive policy chooses a candidate (model plus provisioning configuration) for each request.
If the policy can see the request — task, instance, context size, dataset features, labels — it
can route by request type, and a study measures how well the policy author encoded prior
knowledge of the dataset rather than how a system adapts to what it observes. Request features
also correlate with outcomes, so per-request filtering ("this candidate cannot fit this
context") hides failures the system should have to learn about.

## Decision

A policy receives the candidate catalogue and a read-only system state, and nothing about the
request. The system state holds only windowed readings over observations of earlier requests, the
policy's own memo and a seeded random source. The catalogue is the same for every request; the
tool never filters or ranks candidates by request information. An infeasible choice is executed,
fails, and the failure becomes an observation.

Dataset features are used in exactly two places: building a workload and labelling requests for
analysis.

## Consequences

- A test walks every attribute reachable from the policy inputs and finds no request identifier,
  task, instance, label or task statement.
- Request knowledge can enter only as signal values produced by declared online assessors;
  assessors must be reviewed so they do not copy request features into values.
- Feature-based rules ("route large contexts to B") cannot be built-in or external policies.
  Such comparisons are expressed as separate static runs and analysed with `headroom`.
- Exploration costs real attempts: a blind policy learns about a candidate only by selecting it.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), requirements R3, R4 (section 2.1) and the system state and policy
  contract (sections 6.5, 6.6).
- [Use cases](../../sprints/adaptive-framework/usecases.md).
- [acceptance report: compact plan and policy contract](../../sprints/adaptive-framework/acceptance/wp-b-acceptance.md).
