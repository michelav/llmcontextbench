# Implement task slice

Use this with Codex.

```text
Implement only these tasks from {{SPEC_DIR}}/tasks.md:

{{TASK_IDS}}

Do not implement any other tasks.
Do not create or switch branches.
Do not run provider-backed commands.
Do not perform opportunistic refactors.
Do not change artifact contracts beyond what the active spec allows.

Before editing:

- inspect the relevant files;
- summarize the intended changes;
- identify the focused tests to run.

After editing:

- run only focused tests relevant to these tasks;
- report files changed;
- report commands run and results;
- report remaining risks;
- leave unchecked tasks untouched.
```
