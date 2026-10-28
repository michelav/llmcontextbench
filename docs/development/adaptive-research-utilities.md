# Adaptive research utilities

`ctxbench.adaptive.research` provides provider-free preparation and analysis helpers:

- `seeded_workload` samples unique task/instance requests with a fixed integer seed and can
  exclude declared `sourceGroup` lineage groups. Callers must supply lineage keys; unknown lineage
  is not inferred.
- `resample_knowledge` bootstraps numeric observations by candidate and feature group. Every
  requested group must have observations, and every output metric is marked `estimated`.
- `knowledge_diff` reports changed estimate fields without editing either snapshot.
- `materialize_derivation` copies a complete dataset directory to a new destination and writes
  `derivation.json` with its source, selected requests, and derived provenance. It does not filter
  domain-specific files; adapters interpret the selected request list.
- `paired_differences` computes right-minus-left values for complete request pairs and reports
  scheduled pair count and coverage. Incomplete pairs remain visible in the denominator.

These helpers do not call providers, mutate calibration snapshots, or modify the source dataset.
They intentionally leave dataset-specific filtering and lineage discovery to the adapter.
