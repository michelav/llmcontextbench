# WP0 decision record: benchmark and adaptive workflows

Status: decisions frozen for WP1–WP6 implementation, subject to review at the WP0 gate.  
Date: 2026-11-11

This record resolves the contract questions for the staged re-architecture described in
[`architecture-assessment-and-plan.md`](architecture-assessment-and-plan.md). It constrains new
behavior; it does not certify current adaptive v1 behavior as correct.

## Workflow and identity

- Benchmark and adaptive are peer workflows over shared dataset, runtime, execution, evaluation,
  artifact, and analysis services. Benchmark planning freezes configuration assignment in
  `trials.jsonl`. Adaptive planning validates a candidate catalog and ordered workload, while
  candidate selection happens at runtime.
- A benchmark `trialId` identifies one planned benchmark result. An adaptive `requestId` identifies
  one occurrence in the ordered workload. Repeated task/instance pairs are allowed when their
  request IDs differ; task and instance IDs are correlation data, not invocation identity.
- Each invocation has a unique, stable `executionId`. Retries belong to that execution and have
  attempt sequence numbers. An adaptive request may therefore have multiple execution IDs, one per
  selected candidate attempt. Adaptive execution does not construct `TrialSpec` as its execution
  API.
- Each adaptive attempt has its own persisted decision, with a stable decision ID and the relevant
  request sequence and attempt ordinal. A decision is recorded before invoking the execution
  service. Acceptance is analyzed after the attempt; fallback/escalation requires another decision.

## Canonical records and projections

- The durable execution record keyed by `executionId` is the authority for invocation attempts,
  runtime outcomes, retries, execution metrics, and trace references. Attempts are children of an
  execution, not trial records.
- The adaptive request ledger is the authority for request order, per-attempt decisions, delivery,
  and request-level outcome. It references execution IDs; it does not duplicate execution attempt
  payloads.
- `trials.jsonl` remains the frozen benchmark plan. `responses.jsonl` is a projection with exactly
  one benchmark result per trial, or exactly one delivered adaptive response per served request.
  Failed/unserved adaptive requests have no delivered response row and remain visible in the request
  ledger. Intermediate adaptive attempts never become response rows.
- Evaluations remain separate from generated responses and retain individual judge votes. Their
  input identity is the benchmark `trialId` or adaptive delivered-response/request identity. The
  controller may consume a separately declared, disjoint calibration evaluation, but not offline
  evaluation of its active episode.
- Request, execution-attempt, generation, online-assessor, quota-wait, and offline-evaluation costs
  remain separately attributable. Response and evaluation projections are deterministic and can be
  rebuilt from their canonical inputs; projection rebuilding is batched or incremental rather than
  performed as a full rewrite after every attempt.
- New adaptive definitions and adaptive artifacts use an explicitly versioned contract. The target
  workflow requires a fresh plan. Existing adaptive v1 plans are not silently migrated or executed
  by the target workflow. Existing benchmark artifacts keep their current schema unless a separately
  versioned migration is approved. The legacy non-durable benchmark execute path is not expanded;
  migration or retirement is gated on preserving supported benchmark behavior.

## Recovery, retries, and ordering

- Persist the adaptive decision before starting execution. On resume, replay persisted decisions
  and completed outcomes; never recompute an already persisted decision from later history.
- A durable `started` attempt with an uncertain provider outcome is not silently rerouted or
  repeated. Resume reports the uncertainty and requires the explicit retry policy. Retrying creates
  a new attempt under the same execution ID and records the choice.
- `force` starts a clean output generation or is rejected for adaptive execution. It must not mix
  old records into new controller history, quota accounting, or projections.
- Controller history is strictly prefix-causal. Decision `n` can use declared frozen Knowledge,
  observations from requests `< n`, and earlier completed attempts of request `n`; no later request
  can influence it. Execution is serial in the first implementation. Concurrency requires a separate
  ordering and admission design.
- Canonical records use one shared atomic persistence mechanism with lock scope covering the
  relevant run writer. The study-specific `adaptive/recovery.py` helper is not the generic workflow
  store. Separate record types remain separate authorities, not duplicate stores.

## MAPE-K, acceptance, and quality

- Monitor collects runtime outcomes and declared online signals. Analyze determines whether the
  response is accepted and whether declared service objectives are met. Plan selects the next
  eligible candidate and performs admission. Execute invokes the shared execution service.
- The existing minimum-response-length behavior is a response-acceptance sensor. It can reject an
  empty/short response and trigger another decision, but it does not measure semantic correctness
  and cannot satisfy an accuracy SLO.
- A quality SLO is valid only when the adaptive definition names an online semantic assessor and
  its required dataset capability is available. An unavailable quality signal remains unavailable;
  it is neither zero nor a satisfied SLO.
- Every sensor declares its class (response acceptance, semantic proxy, judge, or oracle),
  provenance, and runtime/token cost. Results and claims identify that class. Oracle and judge
  signals are not described as deployment-realistic proxy quality.
- Admission/quota is a Plan responsibility. Admission outcome and quota wait are recorded
  separately from provider execution duration. No policy can select outside the predeclared,
  validated candidate catalog.

## Dataset features, calibration, and estimation

- Extend the existing `DatasetCapabilityReport`; do not add a parallel capability registry.
  Capabilities describe feature availability, response-acceptance sensors, semantic assessors, and
  calibration/evaluation support, including provenance and cost where relevant.
- Reuse and extend the existing adaptive `Candidate`, `RequestFeatures`, `Observation`, `Decision`,
  `PolicyState`, provenance, and sidecar contracts. Avoid duplicate models with the same semantics.
- Feature partitions are declared by a versioned feature schema. They can include dataset-provided
  categorical features or a declared numeric partition; they are not fixed to `sizeBin`. Feature
  identity, missing-value behavior, and partition boundaries are frozen into the plan/definition.
  Identity, outcomes, and post-execution fields are not request features.
- Calibration is a named, versioned Knowledge input with source run identity, dataset and candidate
  compatibility, feature schema, estimator version, and evaluation provenance. Calibration
  requests are disjoint from the active workload. A disjoint calibration run may be evaluated and
  those evaluation results may seed Knowledge; evaluation from the active episode may not.
- Define a versioned estimator interface over observations and an explicit finite rolling window.
  The initial implementation uses the most recent five valid observations per candidate/partition,
  with a minimum of three runtime observations before replacing a calibration estimate. Fewer than
  three samples retain an available calibration estimate; without one, the estimate is unavailable.
  Provenance is propagated through estimates. Window and warm-up rules are policy metadata, not
  implicit implementation constants.

## Shared service and import boundaries

- `ExecutionRequest` and `ExecutionOutcome` are workflow-neutral. The request contains the unique
  `executionId`, workflow/run correlation, request or trial correlation, task/instance, selected
  candidate/provisioning configuration, and execution options. It does not require `TrialSpec`.
- The shared execution service owns attempt persistence, retry/recovery mechanics, runtime
  invocation, and outcome references. Benchmark adapts `TrialSpec` to this contract; adaptive builds
  it from its request and selected candidate. Neither workflow calls the other's orchestration.
- Shared services and neutral contracts do not import benchmark or adaptive workflow modules.
  Benchmark may depend on shared services and its own domain models. Adaptive may depend on shared
  services, adaptive models, and dataset protocols, but not `commands.*`, benchmark workflow
  execution modules, or `TrialSpec` as its invocation API. CLI commands dispatch into workflows.
- A run-scoped execution session owns reusable runtime/Engine/MCP resources and is reused across
  serial invocations in that run. Session creation and warm-up are recorded separately from
  per-invocation duration, so MCP startup is not charged to every adaptive attempt. Per-invocation
  duration starts at service invocation and includes runtime work and declared online sensor work;
  quota wait and offline evaluation are separate.
- Runtime disturbances are named, seeded, component-scoped inputs in the definition and execution
  fingerprint. A disturbance must identify the component it affects and be applied consistently to
  every candidate that uses that component. Injected delay appears in measured wall-clock duration,
  with the declared injection separately recorded; injected failures are distinguishable from
  provider/runtime failures. The duplicated delay wrappers are replaced by one shared interceptor.

## Baselines and acceptance coverage

The static benchmark baseline is the provider-free fake-dataset planning workflow and the
artifact-contract fixture workflow. These preserve static trial expansion, dataset/task identity,
response/evaluation identity, judge-vote retention, and separation of execution from evaluation.
Adaptive behavior baselines cover response acceptance and fallback delivery, candidate exhaustion,
attempt usage accounting, and uncertain-attempt recovery. Known v1 defects are explicitly excluded:
started-request resume must not erase/redecide history, and future request records must not enter a
decision's history or quota accounting.

WP1 must move the fallback tests off `commands.execute._execute_durable` onto the shared execution
service seam as soon as that seam exists. This test migration is intentionally coupled to the WP1
service contract, rather than introducing a temporary execution abstraction in WP0.

Provider-free verification commands for the WP0 gate:

```text
pytest -q tests/test_fake_dataset_workflow.py tests/test_artifact_contracts.py
pytest -q tests/test_adaptive_v1_fallback.py tests/test_execution_records.py tests/test_adaptive_token_accounting.py tests/test_adaptive_calibration.py
```

No real-provider execution is part of these baselines.
