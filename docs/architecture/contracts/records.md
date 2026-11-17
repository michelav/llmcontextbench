# Records

Durable records are the authority for what happened in a run. Projections (`responses.jsonl`,
metric tables, exports) are rebuilt from them without provider calls.

## Execution records (both workflows)

Path: `execution-records/<key>/attempt-NNNNNN.json`, where `<key>` is the first 24 hex digits of
the SHA-256 of the `executionId`. Writer: `ctxbench/execution/service.py::TrialExecutionService`.

One file per attempt. It is written with `state: "started"` before the invocation and rewritten
with the terminal state and `result` after it.

| Key | Content |
|---|---|
| `executionRecordVersion` | `1` |
| `executionId` | Benchmark: the trial's execution ID. Adaptive: the `requestId`. |
| `workflowId`, `correlationId`, `trialId`, `experimentId`, `taskId`, `instanceId`, `candidateId` | Identity copied from the execution request. Adaptive attempts have `correlationId = requestId` and `trialId = null`. |
| `attemptId`, `attemptIndex` | `<key[:16]>-<index:06d>` and the 1-based index. |
| `executionFingerprint` | The run's fingerprint. |
| `state` | `started`, `succeeded` or `failed`. |
| `startedAt`, `finishedAt` | UTC timestamps. |
| `result` | The serialised invocation result (response, usage, `metricsSummary`, timing, trace reference). Present once the attempt is terminal. |

A `started` attempt without a result is uncertain: the invocation may have reached the provider.
`execute` refuses to continue past it unless `--retry-uncertain` is given. A terminal attempt is
replayed from its record on resume; it is never invoked again.

### Adaptive attempt payload (`result._adaptiveSignals`)

Computed inside the invocation wrapper, so it is stored atomically with the attempt result:

| Key | Content |
|---|---|
| `signals` | Map of signal ID to `{"value", "provenance", "unit"}`: the built-in signals and any `quality.<id>` signals. An unavailable value is `null` with provenance `unavailable`, never `0`. |
| `knownSubtotals` | Known partial totals of signals whose value is unavailable (for example `total_tokens`). Not signal values. |
| `failureCategory` | `null` on success; otherwise one of `context_overflow`, `rate_limited`, `provider_error`, `tool_error`, `step_limit`, `empty_response`, `capability_unavailable`, `unknown`. |
| `accepted` | Success and at least `minimumResponseLength` characters of response. |
| `disturbances` | `[{"name", "version", "appliedDelayMs", "injectedFailures"}]`, one per disturbance whose component the attempt instantiated. |
| `assessorCost` | One entry per declared assessor: `signalId`, `assessorId`, `assessorVersion`, `durationMs`, `durationProvenance`, `totalTokens`, `tokenProvenance`, optional `errorType`; for an attempt that did not succeed, a known zero cost with `skipped: "attempt_not_successful"`. |
| `implementationDigest` | Digest of the implementation that executed the attempt. |

`failed.<category>` values are not stored; they are computed from `failureCategory` when a
policy or goal reads them.

## Adaptive request records

Path: `adaptive-records/<requestId>.json`. Writer: `ctxbench/adaptive/workflow.py`.
One record per request, `schemaVersion: 3`.

```json
{
  "schemaVersion": 3,
  "requestId": "r-0007", "sequenceIndex": 7,
  "executionFingerprint": "<sha256>",
  "taskId": "…", "instanceId": "…", "labels": {},
  "state": "delivered", "terminalReason": "delivered",
  "requestDurationMs": 1234, "requestDurationProvenance": "measured", "interrupted": false,
  "attempts": [{
    "ordinal": 1,
    "decision": {
      "decisionId": "r-0007:d1", "decisionIndex": 7,
      "policy": {"id": "window_threshold", "version": "1"},
      "candidateId": "B", "reason": "…", "memo": null,
      "readings": [{"signal": "total_tokens", "statistic": "sum", "scope": "system",
                    "window": {"requests": 10, "mode": "sliding"}, "capacity": null,
                    "value": 10432, "provenance": "derived",
                    "sampleCount": 10, "missingCount": 0, "knownSubtotal": null}],
      "createdAt": "<utc>"
    },
    "executionId": "r-0007",
    "execution": {"attemptId": "…", "status": "success", "resumed": false},
    "observation": {"status": "success", "signals": {}, "knownSubtotals": {},
                    "failureCategory": null, "accepted": true},
    "disturbances": [],
    "assessorCost": [],
    "implementationDigest": "<sha256>"
  }],
  "delivery": {"candidateId": "B", "executionId": "r-0007", "attemptId": "…"}
}
```

| Field | Rule |
|---|---|
| `state` | `started` (record created; the decision may or may not be persisted), `delivered` or `failed`. |
| `terminalReason` | `delivered`, `attempt_failed` or `response_too_short`; `null` while `started`. |
| `requestDurationMs` | `measured` with a monotonic clock from before the decision to the terminal state. `interrupted: true` when the request spanned a resume. |
| `attempts` | Exactly one element once the request is terminal: one decision, at most one attempt. |
| `decision` | Persisted before the execution starts. `readings` is the audit of every `state.window()` call the policy made. `memo` is passed back to the policy at the next decision. |
| `observation` | Copied from the execution record's `_adaptiveSignals`. |
| `delivery` | The delivered attempt, or `null` when the request failed. |

The record holds no state snapshot and no goal status. The observation log is rebuilt from the
records on resume, and goals are computed by `metrics`.

## Adaptive lifecycle

`adaptive-lifecycle.json` (`schemaVersion: 1`) lists execution sessions:
`{"startedAt", "finishedAt", "providerInvocations", "replayedExecutions"}`.

## Responses projection

`responses.jsonl` is a projection. Benchmark: one row per trial, rebuilt from the execution
records. Adaptive (`ctxbench/adaptive/projections.py`): exactly one row per delivered request,
in sequence order, with `workflowKind: "adaptive"`, `responseSchemaVersion: 3`,
`responseId = requestId`, `requestId`, `sequenceIndex`, `executionId`, `attemptId`, and the
attempt result without `_adaptiveSignals`. Failed requests have no row.

Evaluation (`evals.jsonl`, `judge_votes.jsonl`) refers to response identities and keeps judge
usage separate from generation usage.
