# Review tasks

Use this before implementation.

```text
Review {{SPEC_DIR}}/tasks.md.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:

- Are tasks small enough for incremental implementation?
- Are tasks ordered correctly?
- Are dependencies clear?
- Are tasks tied to spec/plan requirements?
- Are tests or fixture validations included where needed?
- Are any tasks too broad?
- Are any tasks mixing unrelated concerns?
- Are any tasks likely to trigger provider-backed execution?
- Are any tasks doing opportunistic refactoring?
- Are any tasks missing exact file paths?

Suggest task splits, removals, or reordering if needed.
```
