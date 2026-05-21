# Worklog: Dataset Package Capabilities and Core/Adapter Boundary

## 2026-05-20

- event: slice-implemented
- slice: S1
- summary: Added v0 dataset payload dataclasses, oracle-unavailable sentinel, adapter error types, and focused payload/error tests.
- token_provenance: unavailable

- event: slice-implemented
- slice: S2
- summary: Added the v0 DatasetPackage protocol surface, generic AdapterRegistry/ResolvedDatasetRef, initial registry tests, and aligned contract validation tests with the new mandatory capabilities.
- token_provenance: unavailable

- event: slice-implemented
- slice: S3b
- summary: Renamed the copied Lattes adapter class, added v0 payload methods to the adapter, tightened LocalDatasetPackage to the v0 method surface, and removed Lattes-specific specialization from the generic dataset provider.
- token_provenance: unavailable

- event: slice-implemented
- slice: S3c
- summary: Added first-party adapter registry wiring for ctxbench/lattes and import-boundary tests for benchmark, dataset, commands, and dataset provider modules.
- token_provenance: unavailable

- event: slice-implemented
- slice: S3d
- summary: Replaced legacy ctxbench.datasets.lattes implementation modules with compatibility re-export stubs and added provider-free tests proving old import paths resolve to moved adapter symbols.
- token_provenance: unavailable

- event: slice-implemented
- slice: S4
- summary: Routed planning through the dataset adapter contract by adding resolve_for_planning, updating runspec generation to use DatasetPackage v0 methods, and resolving registered adapters in plan with a protocol fallback for unregistered local fixtures.
- token_provenance: unavailable

- event: slice-implemented
- slice: S5
- summary: Routed execution through adapter resolution, replaced inline context file access with get_context payloads, enforced tool_provider capabilities for tool-mediated strategies, and updated execution request metadata.
- token_provenance: unavailable

- event: slice-implemented
- slice: S6
- summary: Routed evaluation through adapter resolution and v0 evidence/oracle payloads, kept oracle values out of judge prompts, recorded evidence/oracle trace metadata, and added provider-free evaluation boundary tests.
- token_provenance: unavailable

- event: slice-implemented
- slice: S7
- summary: Added provider-free fake adapter conformance tests, default Lattes registry integration tests, canonical experiment fixture validation, and a clean canonical experiment fixture.
- token_provenance: unavailable

- event: slice-implemented
- slice: S8
- summary: Updated architecture documentation for Adapter Registry v0, adapter boundaries, format vocabulary, artifact-only export/status behavior, and trace metadata contracts; added artifact-only unavailable-dataset fixtures and provider-free export/status validation.
- token_provenance: unavailable

- event: audit-run
- slice: final-audit
- summary: Ran full provider-free validation (`pytest tests/ -x --ignore=tests/fixtures`) with 246 passing tests; import smoke check for executor/evaluation exited 0. Spec Kit prerequisite helper was not used as a gate because the current branch name `feat/dataset-boundaries-capabilities` does not match its numeric feature-branch pattern, but the explicit Spec 004 task list and complete checklist were used.
- token_provenance: unavailable

- event: diff-reviewed
- slice: final-audit
- summary: Confirmed lifecycle phases no longer call `DatasetProvider.from_dataset`; remaining lifecycle fallbacks use `LocalDatasetPackage.from_dataset`, while `DatasetProvider.from_dataset` is retained only through the compatibility subclass. Added a deprecation note to schedule removal after Spec 004 migration safety is no longer needed.
- token_provenance: unavailable

- event: spec-completed
- slice: final-audit
- summary: Follow-ups recorded: no downstream analysis notebook dependency on removed executor trace metadata keys `context_path` or `instance_dir`; `lattes_id` to `instance_id` remains backward-compatible through strategy fallback reads; Spec 006 still owns external Lattes adapter relocation and should remove the deprecated-internal `DatasetProvider` compatibility alias with that relocation.
- token_provenance: unavailable
