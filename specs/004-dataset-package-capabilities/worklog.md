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
