# Create command model and phase renaming spec

Use this with `/speckit.specify`.

```text
/speckit.specify

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.

SPECIFY_FEATURE_DIRECTORY=specs/001-command-model-and-phase-renaming

Create a specification named "command-model-and-phase-renaming".

The goal is to migrate the benchmark public command model and lifecycle terminology to the target architecture.

Target command model:

- `ctxbench plan`
- `ctxbench execute`
- `ctxbench eval`
- `ctxbench export`
- `ctxbench status`

Target terminology:

- query -> execute/execution
- queries -> trials
- answer -> response
- runId -> trialId
- questionId -> taskId
- mcp -> remote_mcp when referring to the remote strategy

The spec must define compatibility expectations for legacy names such as `copa`, `query`,
`queries.jsonl`, `answers.jsonl`, `runId`, `questionId`, and `answer`.

Writers should prefer target names. Readers may support legacy names during migration.

The spec must not change dataset semantics or add a new domain. It only addresses command
names, phase names, public terminology, compatibility aliases, tests, documentation, and
migration behavior.

No provider-backed command may be executed.
```
