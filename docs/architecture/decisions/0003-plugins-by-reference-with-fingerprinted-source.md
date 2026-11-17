# 0003. Plug-ins referenced by name with fingerprinted source

- **Status:** accepted
- **Date:** 2026-11-16

## Context

Studies need their own policies and online assessors. Passing live Python objects into an
experiment would make the experiment unreproducible from its files and let a script sit on the
request path. Changing plug-in code in the middle of a long run would silently change behaviour.

## Decision

Policies and online assessors are referenced in the definition by name and JSON parameters: a
built-in name, or `package.module:ClassName` for an external class, with an optional
`sources` list of extra files. `plan` imports the class, validates parameters and records
`id`, `version` and a source digest over the class's source file and the listed files, for
built-in and external policies alike. `execute` re-resolves every plug-in and refuses to run
when a digest, source list or declared capability differs. `--plugin-path` (API:
`plugin_paths`) adds import directories for one call.

## Consequences

- No live object is part of an experiment; the frozen plan alone describes the run.
- Fixing a plug-in requires a fresh plan.
- The tool owns the loop; scripts supply references, never callables on the request path.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), requirements R15, R16 (section 2.2) and plug-in resolution (section
  6.7).
- [acceptance report: compact plan and policy contract](../../sprints/adaptive-framework/acceptance/wp-b-acceptance.md),
  [acceptance report: online quality signals](../../sprints/adaptive-framework/acceptance/wp-f-acceptance.md).
