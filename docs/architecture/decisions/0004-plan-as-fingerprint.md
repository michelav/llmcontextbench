# 0004. The adaptive plan is the fingerprint

- **Status:** accepted
- **Date:** 2026-11-17

## Context

Adaptive runs first computed the execution fingerprint from a separate set of inputs (frozen
artifacts, implementation digest, dataset, plug-ins) stored in the manifest. That duplicated
what the plan already held, so a code-built and a file-defined experiment could not be compared
through one hash, and an implementation fix blocked resuming a long run.

## Decision

The frozen plan records everything the run depends on besides its own content: plug-in source
digests and a `provenance` block with the dataset digest and the implementation digest with
dependency versions. `executionFingerprint` is the SHA-256 of `adaptive-plan.json`; the
manifest has no `fingerprintInputs`. `execute` checks the plan hash, the dataset digest and
plug-in sources. The implementation digest is recorded per attempt and not enforced; `status`
and `metrics` report runs whose attempts span several implementations.

Benchmark manifests and their fingerprint check are unchanged.

## Consequences

- Equal experiments give byte-identical plans and equal fingerprints, however they were written.
- A code fix does not block resuming; the mix is visible in the attempt rows and the metrics
  manifest.
- A changed built-in policy module is still refused, because policy source digests are part of
  the plan.

## Sources

- [Design](../../sprints/adaptive-framework/design.md), manifest and fingerprint (section 8.3) and resume (section 7.5).
- [acceptance report: plan as fingerprint](../../sprints/adaptive-framework/acceptance/wp-p-acceptance.md).
