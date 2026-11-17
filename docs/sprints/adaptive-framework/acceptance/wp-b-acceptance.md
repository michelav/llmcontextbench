# WP-B acceptance: compact adaptive plan and policy contract

**Status:** implemented; awaiting review before WP-C.

## Delivered

- Moved shared definition resolution, fingerprints, provenance, surfaces, and task rendering into
  `core/` and `dataset/`; kept benchmark re-exports and added the adaptive-to-benchmark import
  boundary test.
- Added the explicit-workload adaptive definition v4 model, plan v4, manifest/artifact v3, request
  records v3, computed fingerprints, named policy loading, and source-change refusal.
- Replaced candidate fallback with one persisted decision and at most one execution attempt per
  request. Resume reuses the stored decision. The policy receives only the fixed candidate
  catalogue and causal observations.
- Added built-in static, seeded random, and round-robin policies; `verify_replay`; and the adaptive
  CLI/API paths, including planning from an `AdaptiveExperiment` object.
- Rejected old adaptive plan versions with fresh-plan guidance. Benchmark artifact schemas and
  CLI behavior remain unchanged.

## Acceptance checks

- Definition file, mapping, and `AdaptiveExperiment` planning produce identical frozen plans.
- The fake dataset and mock provider plan and execute through both API and CLI.
- Policy blindness, invalid decisions, deterministic built-ins, one-attempt failure, persisted
  decision resume, replay, and external policy fingerprint refusal are covered.
- Focused checks: `30 passed` across API, adaptive workflow/contracts, and import boundaries.
- Full provider-free suite: `450 passed` (`pytest -q`).
- `git diff --check` is clean. No real provider execution or evaluation was run.

## Review fixes

- An `AdaptiveExperiment` built in a script plans like a file; its fields are validated through
  the v4 schema and written to `resolved.json`.
- The plan records extra policy sources relative to the policy module and no absolute paths, so
  a run and its plug-in directory can move.
- Planning refuses a candidate whose strategy the dataset cannot serve (`CapabilityError`).
- Definition problems found while planning raise `DefinitionError`.
- `status --by task|instance|candidate` prints the grouped table again.
- Lifecycle sessions record their own start time, provider invocations and replayed executions.
- A multi-request interrupt-and-resume test compares the resumed records with an uninterrupted run.

## Known scope boundary

Signals/state statistics, goals, workload generation, disturbances, and online quality assessors
remain in their assigned later work packages. WP-B accepts explicit workload requests only.
