# LLMContextBench Redesign Spec Roadmap

## Status legend

- `draft`: lightweight spec exists
- `planning-ready`: ready for `/speckit.plan`
- `planned`: plan reviewed
- `tasked`: tasks reviewed
- `in implementation`: implementation started
- `done`: merged

## Specs

| Spec | Goal | Depends on | Enables | Status | Branch | Notes |
|---|---|---|---|---|---|---|
| `001-command-model-and-phase-renaming` | Rename CLI, commands, and phase terminology. | Architecture docs | `002` | draft | TBD | Keep compatibility explicit. |
| `002-artifact-contracts-and-migration` | Define canonical/derived artifacts and migration. | `001` | `003`, `004` | draft | TBD | Include metric provenance. |
| `003-domain-architecture-boundaries` | Make LLMContextBench core domain-neutral. | `001`, `002` | `004`, `005`, `006` | draft | TBD | Avoid plugin framework until needed. |
| `004-dataset-artifact-model` | Define domain-neutral artifact roles and representations. | `002`, `003` | `005`, `006` | draft | TBD | Separate context from evidence. |
| `005-lattes-dataset-migration` | Migrate Lattes to the artifact model. | `004` | `006` | draft | TBD | Preserve behavior. |
| `006-software-repository-domain` | Add software repository domain. | `003`, `004`, `005` | Future experiments | deferred | TBD | Do not detail too early. |

## Current focus

```text
{{CURRENT_SPEC}}
```

## Decisions

- Writers prefer target artifact names.
- Readers may support legacy artifact names during migration.
- Domain-specific concepts must not leak into benchmark core.
- Artifacts should be modeled by semantic role and representation.
- Metric provenance uses: reported, measured, derived, estimated, unavailable.

## Open questions

- {{OPEN_QUESTION_1}}
- {{OPEN_QUESTION_2}}
- {{OPEN_QUESTION_3}}
