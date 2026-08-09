# LLMContextBench Redesign Spec Roadmap

## Purpose

This roadmap tracks the sequence of specs needed to migrate LLMContextBench toward the target architecture while preserving research validity, reproducibility, artifact contracts, metric provenance, and migration safety.

## Status legend

- `draft`: lightweight spec exists or is being drafted
- `planning-ready`: spec is ready for `/speckit.plan`
- `planned`: plan exists and has been reviewed
- `tasked`: tasks exist and have been reviewed
- `in implementation`: implementation has started
- `done`: implemented, tested, reviewed, and merged

## Specs

| Spec | Goal | Depends on | Enables | Status | Branch | Notes |
|---|---|---|---|---|---|---|
| `001-command-model-and-phase-renaming` | Rename CLI, commands, and phase terminology to target architecture. | Architecture docs | `002` | draft | TBD | Keep compatibility explicit. |
| `002-artifact-contracts-and-migration` | Define canonical/derived artifacts and migration from legacy names. | `001` | `003`, `004` | draft | TBD | Include metric provenance. |
| `003-domain-architecture-boundaries` | Make LLMContextBench core domain-neutral. | `001`, `002` | `004`, `005`, `006` | draft | TBD | Avoid speculative plugin framework. |
| `004-dataset-artifact-model` | Define domain-neutral artifact roles and representations. | `002`, `003` | `005`, `006` | draft | TBD | Separate context from evidence. |
| `005-lattes-dataset-migration` | Migrate Lattes to the domain-neutral artifact model. | `004` | `006` | draft | TBD | Preserve current behavior. |
| `006-software-repository-domain` | Add the software repository domain. | `003`, `004`, `005` | Future experiments | deferred | TBD | Do not detail too early. |

## Current focus

```text
{{CURRENT_SPEC}}
```

## Current decisions

- Writers should prefer target artifact names.
- Readers may support legacy artifact names during migration.
- Domain-specific concepts must not leak into generic benchmark core.
- Artifact roles should be semantic: source, context, evidence, normalized/derived, metadata.
- Metric provenance should use the simplest sufficient model: reported, measured, derived, estimated, unavailable.

## Open questions

- {{OPEN_QUESTION_1}}
- {{OPEN_QUESTION_2}}
- {{OPEN_QUESTION_3}}
