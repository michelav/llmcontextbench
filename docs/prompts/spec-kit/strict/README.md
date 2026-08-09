# LLMContextBench Prompt Templates

Reusable prompt templates for running a specification-driven workflow with Spec Kit, Claude, and Codex.

These templates are meant to be copied into the chat and filled with concrete values. They are not Spec Kit internal templates. Keep them separate from `.specify/templates/`.

## Recommended location in the repository

```text
docs/
  prompts/
    spec-kit/
      README.md
      common-constraints.md
      create-lightweight-spec.md
      promote-spec-to-planning-ready.md
      set-active-feature.md
      plan-specific-spec.md
      generate-tasks.md
      update-spec.md
      update-plan.md
      update-tasks.md
      review-spec-readiness.md
      review-plan.md
      review-tasks.md
      implement-task-slice.md
      review-diff.md
      update-roadmap.md
      create-placeholder-spec.md
      simplify-spec.md
      review-roadmap.md
      create-command-model-spec.md
      create-artifact-contracts-spec.md
      create-domain-boundaries-spec.md
      create-dataset-artifact-model-spec.md
      create-lattes-migration-spec.md
      spec-roadmap-template.md
```

## Common placeholders

| Placeholder | Meaning |
|---|---|
| `{{SPEC_DIR}}` | Feature directory, e.g. `specs/001-command-model-and-phase-renaming` |
| `{{SPEC_NAME}}` | Human-readable feature name |
| `{{FEATURE_GOAL}}` | Short description of the intended change |
| `{{TASK_IDS}}` | Task IDs to implement, e.g. `T001-T003` |
| `{{DEPENDENCIES}}` | Specs or docs this work depends on |
| `{{ENABLED_SPECS}}` | Specs enabled by this work |
| `{{DECISION}}` | Design/research decision to incorporate |
| `{{DISCOVERY}}` | Implementation discovery or constraint to incorporate |
| `{{BRANCH_NAME}}` | Current development branch, if relevant |
| `{{ROADMAP_ITEMS}}` | Ordered list of specs in the roadmap |
| `{{TARGET_FILE}}` | File to simplify or review |
| `{{ROADMAP_FILE}}` | Roadmap file to review |
| `{{CURRENT_SPEC}}` | Current roadmap focus |
| `{{OPEN_QUESTION_1}}` | Open question to track |

## Recommended flow

1. Create a roadmap for related specs.
2. Create lightweight specs for upcoming architectural changes.
3. Promote only the next implementable spec to planning-ready.
4. Run `/speckit.plan` only for that spec.
5. Review the plan.
6. Run `/speckit.tasks`.
7. Review tasks.
8. Implement a small slice of tasks with Codex.
9. Review the diff against the active spec, plan, tasks, constitution, and architecture docs.
10. Update spec/plan/tasks only when intent, technical design, or task sequencing changes.

## Rule of thumb

- Intent, scope, public contracts changed? Update `spec.md`.
- Technical approach, files, migration strategy changed? Update `plan.md`.
- Task order, granularity, or execution changed? Update `tasks.md`.

## Agent usage

- Prefer Claude for specification, planning, architecture, and semantic review.
- Prefer Codex for focused implementation, mechanical refactors, tests, and small patches.
- Use planning mode for changes that affect CLI, artifacts, metrics, datasets, architecture, evaluation, or compatibility.
