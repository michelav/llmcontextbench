# WP-G acceptance report: workload builder and experiments in code

**Status:** implementation complete; acceptance review pending.

WP-G adds deterministic dataset-backed workload generation, strict request-feature filtering and
label projection, adaptive definition section builders, `load_dataset`, `Scenario`, and a provider-free
code-built example. Both generated and explicit workloads are expanded to the same frozen request
records. Adaptive definition files and code-built `AdaptiveExperiment` objects normalize to the same
resolved definition and plan.

Workload sampling uses SHA-256 based ordering and draw selection keyed by the seed, segment index,
and sorted pool. This keeps generation stable across processes and Python runtimes. Without-replacement
sampling resets for each segment; each segment fails if its filtered pool is smaller than its size.

## Review fixes

- Section builders validate through the same schema fragment **and** per-section normaliser as a
  file (`_normalise_section` in `adaptive/definition.py`, also used by `load_adaptive_experiment`).
  Builders now refuse what a file refuses: a failure-only disturbance with a delay, an inverted
  sequence range, a zero or missing delay, and a window with both `requests` and `all`.
  `Disturbance.delay_ms` and `failure_rate` default to `None` (not declared) instead of `0`.
- `Window(all=True, mode=...)` keeps its mode and round-trips; goal windows are normalised by the
  window rule.
- `AdaptiveExperiment` normalises mapping sections with the same rule at construction, so a
  builder and the equivalent mapping give equal experiments.
- `examples/adaptive/code_built.py` plans into a fresh temporary directory (or a directory given
  as its first argument), so it can be run repeatedly.

## Gate decision

Generated and explicit workloads differ in provenance, and the plan is the fingerprint (WP-P),
so their plans cannot be byte-identical. The gate now requires an identical `requests` array
and a byte-identical plan except `workloadSource`; execution fingerprints differ by design.

## Acceptance checks

| Gate | Test (`tests/test_workload_builder.py` unless noted) |
|---|---|
| Identical request lists across processes | `test_generator_is_deterministic_across_processes` |
| Generated vs explicit expansion: same requests, plan identical except `workloadSource` | `test_generator_and_explicit_expansion_differ_only_in_workload_source` |
| Segments filter by declared features; unknown features and undersized pools fail | `test_generator_filters_declared_features_labels_only_features_and_expands`, `test_generator_rejects_unknown_features_and_insufficient_without_replacement_pool` |
| Feature values only in request labels | `test_feature_values_appear_only_in_request_labels` |
| Builders vs file, every section: byte-identical plan, `resolved.json`, fingerprint | `test_builders_and_file_are_byte_identical_for_every_section` |
| Builder and equivalent mapping give equal experiments | `test_builders_and_equivalent_mappings_give_equal_experiments` |
| `X.from_definition(m).to_definition() == m` | `test_section_builder_round_trips_normalized_mappings` (20 cases, all builders) |
| Builder refuses what a file refuses, naming the same field | `test_builder_refuses_what_a_file_refuses_naming_the_same_field` (17 cases) |
| API round trip on a code-built experiment | `test_api_round_trip_on_code_built_experiment` |
| Code-built example runs as written, repeatedly | `test_code_built_example_runs_repeatedly` |

Validation: `pytest -q tests` — 605 passed. No real-provider execution or evaluation was run.

## Known limitations

- Builder errors name the field but not the mapping key or list index (`models.provider` rather
  than `models.mock.provider`), because a builder does not know where it will be stored.
- `Candidate` accepts model and configuration keys only, not builders as section 9.1 states.
- A candidate stored under a key that differs from its `id` keeps the key silently.
- `Workload.generate` validates against one dataset handle, but `plan` expands against the
  experiment's `dataset`; the two are not checked to be the same.
- Section 9.1 lists `Run.labels` and `open_run(..., plugin_paths=...)`; neither exists yet (not
  part of WP-G). Plug-in paths are passed to `Run.execute`.
