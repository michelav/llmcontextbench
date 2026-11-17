# WP-F acceptance report: online quality signals

**Status:** review fixes applied; awaiting approval.

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
- Full provider-free suite before the review fixes: `540 passed` (`pytest -q`).
- No real provider execution or evaluation was run.

## Review fixes

- **Gate change accepted.** Goal evaluation over quality signals moves from the WP-F gate to WP-H,
  which owns goals.
- **Only successful attempts are assessed.** A failed attempt's quality is unavailable, not `0`,
  and its cost record is a known zero (`derived`) marked `skipped: "attempt_not_successful"`.
  Before, the fake and RepoQA assessors scored failed attempts `0`, which mixed failures with poor
  answers in quality readings.
- **Generation duration without assessment.** Request and attempt metric rows gain
  `generationDurationMs` and its provenance, taken from the runtime-measured `timing.durationMs`.
  Attempt `durationMs` stays attempt wall time and is documented as including assessment.
- **Isolation from offline evaluation is now tested properly.** A quality-driven policy runs with
  and without `evals.jsonl` and `judge_votes.jsonl` rows that would change its choices if they
  were read; decisions, readings and quality values are identical.
- **`rate` on declared signals is checked at `plan`.** A declared signal's `valueScale` gives it a
  unit: binary scales are `bool`. `validate_reading_request` applies this at `plan` and in
  `state.window()`, so `rate` on a non-binary quality signal is refused before the run.
- **RepoQA online and offline scoring share one rule.** `score_repoqa_response` and
  `DEFAULT_THRESHOLD` in `adapters/repoqa/evaluation.py` serve both the offline evaluator and the
  online assessor. Limitation: an experiment-specific offline threshold (`validationConfig`) is
  not applied online; that needs per-signal parameters in the definition.
- **Not fixed (needs a schema decision):** external assessors spread over several files have only
  the class file in the fingerprint; signal declarations have no `sources` field.

Checks:

- `pytest -q tests/test_adaptive_quality_signals.py` — 15 passed.
- `pytest -q` — 548 passed.
- No real provider execution or evaluation was run.
