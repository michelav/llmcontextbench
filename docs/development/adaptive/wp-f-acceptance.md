# WP-F acceptance report: online quality signals

**Status:** implementation complete; awaiting review.

WP-F resolves quality signal declarations against either a dataset capability and its
`online_assessor` implementation or an external `module:Class` assessor. External source digests
and the assessor capability contract are frozen in `adaptive-plan.json` and included in the
execution fingerprint. Execution refuses changed sources or capability metadata before it starts
the request loop.

Assessors receive `AssessmentInput` with request/task/instance/candidate identity and response
text. The policy still sees only the candidate catalogue and the prefix observation state. Invalid
observations and assessor exceptions become unavailable quality readings; assessor wall time is
measured even on failure. Quality values, assessor cost, and errors are stored with the durable
execution result, then copied into the request ledger. Resume therefore reuses the saved result and
does not assess a request twice.

Assessor token usage and duration have separate request/attempt metric columns. Missing cost stays
unavailable; known token subtotals are retained separately. A run is marked `privileged` when an
enabled assessor uses reference data, and the flag appears in both metric CSV rows and the metrics
manifest. The RepoQA reference scorer now implements its already-declared assessor capability.
Offline evaluation artifacts are not read by the adaptive decision path.

Goal calculation remains WP-H work. WP-F verifies that quality values can be read by
`state.window(...)` and drive `window_threshold`; WP-H will cover goals over those readings.

## Acceptance checks

- Provider-free fake assessor drives a policy choice from a prior quality observation.
- Assessor failure persists an unavailable value with measured duration and causes
  `when_unavailable` selection on the next request.
- Interruption after durable execution resumes without a second assessor invocation.
- External assessor source changes are refused at execute; dataset assessors resolve through the
  dataset capability contract.
- Reference-data assessors mark the run and metrics privileged.
- Assessor costs remain separate from generation and evaluation usage; offline evaluation rows do
  not affect decisions.
- Adaptive plan, artifact, and request record versions remain unchanged. Signal fields use the
  existing declared-signal structure; assessor cost and privileged metric columns are additive.

Validation:

- Focused quality, adaptive, dataset-package, and RepoQA checks passed.
- Full provider-free suite: `540 passed` (`pytest -q`).
- No real provider execution or evaluation was run.
