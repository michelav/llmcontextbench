# Workflow artifact contracts

LLMCtxBench supports two workflows: static benchmark execution and adaptive request
execution. Both use the shared durable execution service. A workflow owns its plan and
decision records; generated projections can be rebuilt from canonical records.

## Current versions

| Contract | Current version | Owner |
|---|---:|---|
| Benchmark definition | `schemaVersion: 3`, `kind: "benchmark"` | `plan` |
| Benchmark manifest | `schemaVersion: 3`, `provisioningArtifactVersion: 4`, `executionRecordVersion: 1` | `plan` |
| Adaptive plan | `schemaVersion: 3`, `workflowKind: "adaptive"` | adaptive `plan` |
| Adaptive manifest | `schemaVersion: 2`, `adaptiveArtifactVersion: 2` | adaptive `plan` |
| Adaptive request/decision records | `adaptiveRecordVersion: 2` | adaptive execution |

Older definitions and artifact versions are unsupported. The CLI rejects them; it does
not migrate, upgrade, or partially interpret them. Keep an older checkout to inspect
historical outputs. No conversion tool is provided.

## Authority and projections

| Artifact | Authority | Rebuild behavior |
|---|---|---|
| `manifest.json`, `resolved.json`, `trials.jsonl` | Frozen benchmark plan | Created by benchmark `plan` |
| Benchmark execution records | One record per execution attempt | Durable authority for outcome, usage, and timing |
| `responses.jsonl` | Derived benchmark response view | Rebuilt from all benchmark attempt records |
| `evals.jsonl`, `judge_votes.jsonl` | Evaluation results and individual judge votes | Rebuilt/extended by evaluation phase |
| `adaptive-plan.json`, adaptive manifest | Frozen adaptive plan and policy | Created by adaptive `plan` |
| Adaptive request ledger | Per request decision, attempts, and delivery | Durable authority for adaptive routing and delivery |
| Adaptive execution records | One record per invocation | Durable authority for each attempt |
| Adaptive `responses.jsonl` | Delivered response view, one per served request | Rebuilt from request and execution records |
| Exports, metrics, and summaries | Derived analysis | Rebuilt from canonical artifacts without model calls |

An execution attempt is not the same unit as an adaptive request. Failed and rejected
attempts remain in execution records and contribute to attempt diagnostics and cost.
Request-level outcomes report whether a request was accepted and delivered. Offline
evaluation is separate from online acceptance and does not feed the active controller.

## Identity, provenance, and costs

Repeated task/instance occurrences receive distinct request IDs; each invocation has a
distinct execution ID. Benchmark trials use `trialId`; adaptive requests use `requestId`.
Responses identify the request or trial they represent. Evaluation rows refer to the
delivered response identity.

Every metric value uses one provenance class: `reported`, `measured`, `derived`,
`estimated`, or `unavailable`. An unavailable value is never written as zero unless zero
was observed. Generation, execution-attempt, request, online-assessor, and offline
evaluation costs remain separate.

## Dataset provenance

Dataset declarations remain part of the frozen workflow input. Benchmark manifests and
trial records retain dataset ID, version, origin, resolved revision, content hash, and
materialized path where available. The materialized path is operational metadata and is
not dataset identity. Dataset-specific preparation and evaluation stay in dataset
adapters.

## Historical artifact names

The current reader and writer contract uses `trials.jsonl`, `responses.jsonl`,
`evals.jsonl`, and `judge_votes.jsonl`. It does not alias `queries.jsonl`, `answers.jsonl`,
old run identifiers, legacy study packets, or retired adaptive sidecars. Historical data
remains user-owned and requires the earlier application version for analysis.
