# Command model spec

```text
/speckit.specify

SPECIFY_FEATURE_DIRECTORY=specs/001-command-model-and-phase-renaming

Create a spec for migrating the public CLI and phase terminology to the target LLMContextBench architecture.

Use docs/architecture as the source of target vocabulary.

Scope:
- copa -> ctxbench
- query -> execute
- queries -> trials
- answers -> responses
- runId -> trialId
- questionId -> taskId
- mcp -> remote_mcp when referring to the remote strategy
- compatibility aliases during migration

Out of scope:
- dataset redesign
- new domains
- provider behavior changes

Do not create or switch branches.
Do not implement code.
Do not run provider-backed commands.
```
