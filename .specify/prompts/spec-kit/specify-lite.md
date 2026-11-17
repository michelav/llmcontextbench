# Specify lite

```text
/speckit.specify

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Create a concise specification for:

{{FEATURE_GOAL}}

Use the current constitution, docs/architecture, AGENTS.md, and CLAUDE.md as constraints.

Include:
- Goal
- Scope
- Out of Scope
- Requirements
- Acceptance Scenarios using Given/When/Then
- Impact
- Compatibility / Migration
- Validation
- Dependencies
- Risks
- Open Questions

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
```
