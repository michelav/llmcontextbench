# Adaptive workflow plan v3

Adaptive plans are peer workflow artifacts. They do not contain `trials.jsonl` and do not expand
requests into benchmark `TrialSpec` records.

## Definition input

`llmctxbench plan` accepts a JSON object with `workflowKind: "adaptive"`, `schemaVersion: 3`,
the fields defined by `ctxbench.adaptive.adaptive_plan_schema()`, and these optional planning
fields:

- `dataset` (required): dataset provenance with required `id` and `version`, plus optional
  `origin`, `resolvedRevision`, `contentHash`, and `materializedPath`.
- `evaluation`: an `enabled` boolean and optional configured `judges`.
- `trace`: trace settings copied into the manifest.

- Request features use the declared feature schema and feature values; fixed RepoQA `sizeBin`
  labels are not part of the adaptive contract.
- `output`: output directory, overridden by `plan --output`.

The plan contains ordered, uniquely identified requests, declared candidates, pre-execution
features, and a workflow-neutral `ExecutionRequest` for each request/candidate pair. Each execution
request has its own `execution_id` and a JSON `payload` with `runtimeRequest` and `resultMetadata`
objects. The payload supplies the runtime and response metadata needed by `execute`. The adaptive
plan API and schema validator are the canonical way to prepare this input.

Planning requires an empty output directory. It writes `adaptive-plan.json` and a manifest with
`workflowKind: "adaptive"`, `schemaVersion: 2`, `adaptiveArtifactVersion: 2`,
`adaptivePlanVersion: 3`, and a digest
of the frozen plan. The definition's execution fingerprint must match every embedded execution
request.

## Execution and status

Use `llmctxbench execute <run>/adaptive-plan.json`. The workflow persists each decision and
delivery in `adaptive-records/`, and each durable invocation attempt in `execution-records/`.
`responses.jsonl` is rebuilt from delivered requests. `status` reads the frozen plan and canonical
records and reports delivered, failed, rejected, started, and pending requests separately.

Adaptive execution rejects `--force` and selectors that would remove requests from the frozen
causal order. To repeat an episode, create a fresh plan and output directory. A durable uncertain
attempt requires the explicit `--retry-uncertain` option.

## Version policy

Earlier adaptive plan and manifest versions are unsupported. They are neither migrated nor
executed by the current workflow. Benchmark plans continue to use the current benchmark provisioning
contract.
