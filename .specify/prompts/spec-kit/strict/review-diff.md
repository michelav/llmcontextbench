# Review diff against spec

Use this with Claude or Codex after implementation.

```text
Review the current diff against:

- {{SPEC_DIR}}/spec.md;
- {{SPEC_DIR}}/plan.md;
- {{SPEC_DIR}}/tasks.md;
- .specify/memory/constitution.md;
- docs/architecture/.

Do not edit files.
Do not run provider-backed commands.

Focus on:

- compliance with the active spec;
- phase separation;
- artifact contracts;
- metric provenance;
- strategy comparability;
- domain/provider/strategy boundaries;
- migration behavior;
- documentation drift;
- overengineering;
- tests missing or insufficient;
- accidental changes outside the active tasks.

Return:

- summary;
- issues by severity;
- required fixes;
- optional improvements;
- whether the diff is safe to commit.
```
