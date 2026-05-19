# Specification Quality Checklist: Lattes Dataset Extraction

**Purpose**: Validate roadmap-level specification completeness and quality before proceeding to planning or follow-on specs
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Roadmap-Level Discipline

- [x] Spec defines intent, scope, dependencies, and non-goals without prescribing implementation
- [x] Decisions intentionally deferred to planning or follow-on specs are listed explicitly
- [x] Dependencies on previous specs are named (Spec 001, Spec 002, Spec 003, Spec 004, Spec 005)
- [x] Future specs enabled by this one are named
- [x] Affected concepts, artifacts, and docs are enumerated

## Migration Discipline

- [x] What moves to `ctxbench/lattes`, what remains in `ctxbench-cli`, and what is deleted is specified
- [x] An inventory step is required before any move
- [x] Direct references from `ctxbench-cli` to Lattes are required to be removed, not relocated
- [x] Compatibility expectations are explicit (compatible vs incompatible configurations)
- [x] Breakage is required to be documented when unavoidable
- [x] Migration steps must be reproducible and have defined acceptance evidence
- [x] Provider-free verification is required (Constitution Principle X)

## Artifact-Role Mapping (per Spec 005)

- [x] Lattes raw HTML mapped to *source*
- [x] Lattes cleaned/minified HTML mapped to *context* (markup representation)
- [x] Lattes parsed JSON mapped to **both** *normalized/derived* and *context* (structured-object representation), without payload duplication
- [x] Lattes blocks JSON mapped to *evidence*
- [x] Assets with no analogue routed to *metadata* and forbidden from being mistaken for *context* or *evidence*
- [x] No new artifact roles introduced beyond Spec 005's five
- [x] Representation names required to be domain-neutral (no Lattes terminology)

## Terminology Mapping (per Spec 001)

- [x] Questions renamed to tasks (`taskId`)
- [x] Question-instance mappings renamed to task-instance mappings
- [x] Conversion rule for legacy `questionId` is required (preserve/transform/regenerate) and must be deterministic
- [x] Legacy terminology (`questionId`, `runId`, `answer`, `query`, `queries.jsonl`, `answers.jsonl`, `copa`) is forbidden in the migrated Lattes package

## Boundary Conformance (per Spec 003 / Spec 004)

- [x] `ctxbench-cli` must contain zero Lattes-specific data/code/identifiers after migration
- [x] `ctxbench-cli` must not import from `ctxbench/lattes` directly
- [x] Lattes readers and tools are exposed through the dataset package contract
- [x] Lattes evidence is exposed through the evidence-artifact provider
- [x] Contract gaps uncovered by Lattes must be escalated to the owning spec, not patched in `ctxbench-cli`

## Reproducibility (per Spec 003 / Constitution Principle VIII)

- [x] Dataset identity and dataset version are required to be declared by `ctxbench/lattes`
- [x] Every run records both `ctxbench-cli` version and `ctxbench/lattes` version
- [x] A version handshake is performed at run-start
- [x] Version-handshake failure stops the run with a deterministic, identifiable error (no silent fallback)

## Scope Discipline

- [x] No software-repository domain or second domain introduced (deferred)
- [x] No new generic strategies introduced
- [x] No provider behavior changes
- [x] No plugin framework
- [x] No artifact-contract redefinition (governed by Spec 002)
- [x] No role-model redefinition (governed by Spec 005)
- [x] No CLI/terminology redefinition (governed by Spec 001)
- [x] No provider-backed execution for validation

## Notes

- All items pass. Spec is lightweight by design: it is the first conformance migration of the contracts established by Specs 002–005, not a redesign.
- Scope is explicitly fenced by FR-038 through FR-043 to prevent the spec from drifting into a second-domain implementation, new strategy work, provider changes, a plugin framework, or redefinition of any upstream contract.
- This spec is the **first conformance target** for Spec 003 — genuine contract gaps revealed by Lattes are required by FR-027 to be resolved by amending Spec 003, not by accommodating Lattes-specific behavior inside `ctxbench-cli`.
- Constitution principles respected: Principle VII (Boundary Isolation — FR-029, FR-030), Principle VIII (Reproducibility and Traceability — FR-028, FR-033, FR-034), Principle X (Provider-Free Validation — FR-037), Principle XII (Simplicity — no new roles, no new strategies, no plugin framework).
