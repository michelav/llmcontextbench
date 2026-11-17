# 0002. One decision and at most one attempt per request

- **Status:** accepted
- **Date:** 2026-11-16

## Context

The earlier adaptive workflow treated the candidate order as both preference and fallback list:
an unmet quality or cost target triggered another candidate until the catalogue was exhausted.
That mixed retry cost into decision quality, gave metric columns two meanings (request versus
attempt), and made goals a hidden control mechanism.

## Decision

Each request gets exactly one policy decision, which always selects a candidate, and the
candidate is executed once. If the attempt fails, or its response is shorter than
`minimumResponseLength`, the request fails. A policy cannot reject a request. There is no
workflow-level retry and no fallback list. Provider-level retries configured through a model's
`rate_limit` parameters happen inside the one attempt and are part of its latency. Goals are
reported by `metrics`, never enforced.

## Consequences

- A failed attempt is an observation; later decisions see it through `failed` and
  `failed.<category>` readings.
- Request and attempt metrics stay distinct but simple; the fallback columns are gone.
- Resume has one decision and one execution to recover per request.
- Retry after failure, load shedding and signal-based acceptance remain deferred until a study
  needs them.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), requirement R8 (section 2.1), delivery and failure (section 6.8),
  divergences from the plan (section 12) and deferred work (section 13).
- [Architecture assessment and plan](../../sprints/adaptive-framework/architecture-assessment-and-plan.md).
- [acceptance report: compact plan and policy contract](../../sprints/adaptive-framework/acceptance/wp-b-acceptance.md).
