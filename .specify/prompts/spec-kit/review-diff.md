# Review diff

```text
Review the current diff against:

- {{SPEC_DIR}}/spec.md
- {{SPEC_DIR}}/plan.md
- {{SPEC_DIR}}/tasks.md
- .specify/memory/constitution.md
- docs/architecture/

Do not edit files.
Do not run provider-backed commands.

Focus on:
- active spec compliance;
- implementation slice scope;
- phase separation;
- artifact contracts;
- metric provenance;
- domain/provider/strategy boundaries;
- migration behavior;
- documentation drift;
- overengineering;
- missing tests;
- accidental changes outside active slice.

Return:
- summary;
- issues by severity;
- required fixes;
- optional improvements;
- whether the diff is safe to commit.
```
