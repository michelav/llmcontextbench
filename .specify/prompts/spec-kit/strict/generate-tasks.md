# Generate tasks

Use this with `/speckit.tasks`.

```text
/speckit.tasks

Generate tasks only for this specification:

{{SPEC_DIR}}

Use this feature directory:

SPECIFY_FEATURE_DIRECTORY={{SPEC_DIR}}

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

Read:

- spec.md;
- plan.md;
- research.md, if present;
- data-model.md, if present;
- contracts/, if present;
- quickstart.md, if present.

Generate tasks.md with small, ordered, executable tasks.

Tasks must:

- preserve research semantics;
- avoid provider-backed execution;
- include focused tests or fixture-based validation when relevant;
- avoid broad opportunistic refactors;
- separate setup, foundational tasks, user-story tasks, and polish tasks;
- identify tasks that can run in parallel;
- include exact file paths where possible;
- keep domain abstractions minimal and justified;
- include documentation and migration tasks when public behavior changes.

Do not implement the tasks.
```
