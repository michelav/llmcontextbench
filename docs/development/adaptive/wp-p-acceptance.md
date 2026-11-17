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

The implementation covers the WP-P gates for plan hashing, manifest field removal, dataset and
plug-in source verification, changed-implementation continuation, per-attempt provenance, mixed
implementation reporting, and replay provenance. Benchmark fingerprint code paths are unchanged.

Focused validation after the implementation:

- `pytest -q tests/test_adaptive_quality_signals.py::test_quality_signal_is_persisted_and_available_to_policy_and_metrics` — passed.
- No real-provider execution or evaluation was run.
