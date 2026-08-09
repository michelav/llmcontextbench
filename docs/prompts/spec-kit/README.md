# LLMContextBench Prompt Templates — Light Version

Short prompt templates for day-to-day use with Spec Kit, Claude, and Codex.

These prompts intentionally avoid repeating the full constitution or architecture. They assume the agent can read the versioned project guidance:

- `.specify/memory/constitution.md`
- `docs/architecture/`
- `AGENTS.md`
- `CLAUDE.md`
- `.agents/skills/`
- `.specify/templates/`

Use these prompts as starting points and write the human intent yourself.

## Files

| File | Use when |
|---|---|
| `specify.md` | Create a normal spec from a human goal |
| `specify-lightweight.md` | Create an early roadmap-level spec |
| `specify-placeholder.md` | Register future work that is not ready |
| `promote-spec.md` | Turn a lightweight spec into planning-ready spec |
| `set-active-feature.md` | Point `.specify/feature.json` to the active spec |
| `plan.md` | Generate/update plan for one spec |
| `tasks.md` | Generate/update tasks for one spec |
| `implement.md` | Implement a small task slice with Codex |
| `review-spec.md` | Review spec before planning |
| `review-plan.md` | Review plan before task generation |
| `review-tasks.md` | Review tasks before implementation |
| `review-diff.md` | Review current diff against spec/plan/tasks |
| `update-spec.md` | Update spec after a decision |
| `update-plan.md` | Update plan after a technical discovery |
| `update-tasks.md` | Update tasks after plan/task changes |
| `simplify.md` | Ask the agent to simplify a design/spec/plan |
| `roadmap.md` | Create/update the spec roadmap |
| `command-model-spec.md` | Shortcut prompt for the command-model spec |
| `artifact-contracts-spec.md` | Shortcut prompt for artifact contracts |
| `domain-boundaries-spec.md` | Shortcut prompt for domain boundaries |
| `dataset-artifact-model-spec.md` | Shortcut prompt for dataset artifact model |
| `lattes-migration-spec.md` | Shortcut prompt for Lattes migration |

## Common placeholders

| Placeholder | Meaning |
|---|---|
| `{{SPEC_DIR}}` | Spec directory, e.g. `specs/001-command-model-and-phase-renaming` |
| `{{FEATURE_GOAL}}` | Human description of the intended change |
| `{{SCOPE}}` | What is included |
| `{{OUT_OF_SCOPE}}` | What is excluded |
| `{{DEPENDENCIES}}` | Specs/docs this depends on |
| `{{TASK_IDS}}` | Task IDs to implement, e.g. `T001-T003` |
| `{{DECISION}}` | Decision to incorporate into the spec |
| `{{DISCOVERY}}` | Technical discovery to incorporate into the plan |

## Recommended flow

1. Write the goal in your own words.
2. Use `specify.md` or `specify-lightweight.md`.
3. Review the generated spec.
4. Use `plan.md` only for the spec you are about to implement.
5. Use `tasks.md`.
6. Implement a small task slice using `implement.md`.
7. Review with `review-diff.md`.

## Rule of thumb

- Changed intent, scope, semantics, or public contract? Update `spec.md`.
- Changed implementation approach, files, tests, or migration strategy? Update `plan.md`.
- Changed order, granularity, or execution of work? Update `tasks.md`.
