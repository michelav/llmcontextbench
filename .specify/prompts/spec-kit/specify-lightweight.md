# Create lightweight spec

Use when you want a roadmap-level spec, not an implementation-ready one.

```text
/speckit.specify

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Create a lightweight spec for:

{{FEATURE_GOAL}}

This spec should capture intent, scope, non-goals, dependencies, and acceptance criteria.
Do not over-detail implementation.

Scope:
{{SCOPE}}

Out of scope:
{{OUT_OF_SCOPE}}

Depends on:
{{DEPENDENCIES}}

Use the current constitution and architecture docs as constraints.

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
```
