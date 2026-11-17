# Update tasks

Use this when tasks are outdated, too large, wrongly ordered, or missing validation.

```text
Update {{SPEC_DIR}}/tasks.md.

Do not modify spec.md or plan.md unless you find a blocking inconsistency; report it instead.
Do not implement code.
Do not run provider-backed commands.

Read the current:

- spec.md;
- plan.md;
- contracts/, if present;
- research.md, if present;
- quickstart.md, if present.

Regenerate or refine tasks so that each task is small, ordered, and executable.

Break large tasks into smaller tasks.

Ensure tasks include, when relevant:

- fixture-based tests;
- compatibility tests;
- artifact contract tests;
- metric provenance checks;
- documentation update tasks;
- migration note tasks;
- no provider-backed execution;
- no opportunistic refactors.

Keep task IDs sequential.
Report which tasks were added, removed, split, or reordered.
```
