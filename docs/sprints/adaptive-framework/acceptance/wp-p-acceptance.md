# WP-P acceptance report: plan as fingerprint

**Status:** implementation complete; acceptance review pending.

Adaptive plans now contain dataset and implementation provenance. The adaptive manifest's
`executionFingerprint` is the SHA-256 hash of `adaptive-plan.json`; `fingerprintInputs` and
`planDigest` are no longer written. `resolved.json` remains available but is not part of the
fingerprint. Execution verifies the plan hash, dataset digest, policy source, assessor source, and
any files listed in an assessor signal's optional `sources` declaration. A changed implementation
does not block execution.

Each completed attempt records its implementation digest in `_adaptiveSignals` and the request
record. Adaptive status reports the number of distinct implementation digests and whether they are
mixed. Attempt metrics include `implementationDigest`; `metrics-manifest.json` lists the observed
digests and `mixedImplementations` flag.

Benchmark fingerprinting, manifests, and artifacts were not changed. Adaptive artifact versions
remain unchanged as specified for this unreleased branch. Earlier adaptive artifacts without plan
provenance are rejected by the existing fresh-plan contract.

## Acceptance checks

Gate tests (no provider calls):

| Gate | Test |
|---|---|
| `executionFingerprint` is the hash of `adaptive-plan.json`; no `fingerprintInputs`/`planDigest`; plan records dataset and implementation provenance | `test_adaptive_workflow.py::test_execution_fingerprint_is_plan_hash_and_plan_records_provenance` |
| Edited plan refused at `execute` | `test_adaptive_workflow.py::test_edited_plan_is_refused_at_execute` |
| Changed dataset refused; removed dataset reported as missing | `test_adaptive_workflow.py::test_changed_dataset_is_refused_at_execute`, `::test_missing_dataset_is_reported_as_missing` |
| Changed policy source refused | `test_adaptive_workflow.py` (existing policy source tests) |
| Changed assessor source, including a file in `sources`, refused | `test_adaptive_quality_signals.py::test_external_assessor_source_changes_are_refused`, `::test_external_assessor_declared_source_changes_are_refused` |
| Changed implementation not refused; later attempts record the new digest; `status` and metrics (`implementationDigest` column, `implementationDigests`, `mixedImplementations`) report mixing | `test_adaptive_workflow.py::test_changed_implementation_is_recorded_not_refused`, `::test_single_implementation_is_not_reported_as_mixed` |
| Attempt replayed on resume keeps the digest it ran with | `test_adaptive_workflow.py::test_replayed_attempt_keeps_the_digest_it_ran_with` |
| Benchmark fingerprint unchanged | `test_benchmark_fingerprint.py` |

Validation: `pytest -q tests` — 556 passed. No real-provider execution or evaluation was run.

## Limitations

- The dataset digest is a file-tree digest only when the dataset has a materialized path. A
  dataset without one falls back to its declared `contentHash`, which is an identifier from the
  dataset source; changes behind it are not detected at `execute`.
- The manifest's `dataset` block (which locates the dataset) is not covered by the fingerprint;
  redirecting it to different content is caught by the plan's dataset digest, not by the hash.
- A fingerprint or source mismatch surfaces as `ExecutionStateError` (unchanged from before
  WP-P), while the error hierarchy in section 9.1 of the design lists fingerprint mismatch under `ArtifactError`.
