# Runtime Extraction Baseline

> Transition note: this page describes the existing implementation. The accepted
> [v1 target architecture and contracts](v1-contracts.md) describe the refactor;
> [slice tracking](../../specs/009-llmctxbench-v1/tasks.md) identifies what is implemented.

This note records the first implementation boundary for the staged evolution in
[`../llmcontextbench-evolution-plan.md`](../llmcontextbench-evolution-plan.md).
It covers Phases 0–3: establish the current execution path, introduce
trial-independent contracts, add a benchmark adapter, and migrate `inline` only.
It does not introduce policy selection, runtime telemetry redesign, adaptive
behavior, naming changes, or persisted-artifact changes.

## Implementation status

The inline extraction is implemented. `ctxbench.runtime` and
`ctxbench.core.provisioning` provide the trial-independent contracts;
`TrialRuntimeAdapter` translates benchmark records; and `execute_runspec()`
delegates inline trials through `ProvisioningRuntime`. Tool strategies remain on
their existing path. Provider-free verification passed on 2026-09-18:

```text
67 passed: runtime, AI, provisioning, and import-boundary tests
106 passed: legacy rejection, model schema, provisioning, artifact, lifecycle,
CLI, and metric regression tests
```

## Invariants

- Retain the public concepts `strategy`, `Surface`, `ProvisioningConfiguration`,
  and `representation`.
- Retain deterministic trial identity; `manifest.json`, `trials.jsonl`,
  `responses.jsonl`, trace files, metrics, CLI behavior, and strategy semantics.
- Keep dependencies one-way: `benchmark -> runtime -> ai/core`. Runtime must not
  import benchmark models, artifacts, experiments, commands, or dataset registry.
- Use provider-free tests. `local_function` remains on its current path until
  inline equivalence is demonstrated.

## Current execution path

```text
planning
  -> TrialSpec + manifest.json + trials.jsonl
  -> commands.execute (selection, resume, artifact ownership, shared Engine)
  -> benchmark.executor.execute_runspec
     -> dataset registry resolution; LocalDatasetPackage fallback
     -> inline: adapter.get_context(instanceId, taskId, representation)
     -> request metadata, OpenAI cache-key preparation, AIRequest
     -> Engine.execute
        -> model adapter/rate control -> strategy -> model/tools/MCP -> AIResult
     -> trace/usage retention, metrics summary, timing, TrialResult
  -> trace serialization and responses.jsonl
  -> evaluation, export, metrics, status
```

For `local_function` and `local_mcp`, the executor also resolves dataset tools or
MCP, creates a copied Engine with a tool-runtime factory, and closes it after
execution. `remote_mcp` validates `params["mcp_server"]`. Those paths stay
unchanged in the inline slice.

Context/capability preparation errors currently propagate. Errors from
`Engine.execute()` become an `AIResult.error`; an empty answer becomes the
benchmark error `"Model returned empty answer"`. Preserve this distinction.

## TrialSpec execution inputs

| Classification | Fields | Boundary treatment |
|---|---|---|
| Shared | `taskStatement`, `taskId`, `instanceId`, `provider`, `modelName`, `strategy`, `representation`, `surface`, `surfaceSpec` | Runtime execution inputs and persisted result fields. |
| Shared, split | `dataset` | Benchmark resolves it to a context capability; runtime receives only that capability. Provenance remains in TrialResult. |
| Runtime | `params` | Copy unchanged for provider/model controls, step limits, MCP configuration, and cache settings. |
| Benchmark | `trialId`, `experimentId`, `repeatIndex`, `configurationId`, `modelId`, `taskTags`, `validationType` | Identity, treatment, logging, provider metadata and result annotations. |
| Benchmark | `taskTemplate`, `validationConfig`, `contextBlocks`, `parameters`, `metadata`, `outputRoot`, `trace`, `artifacts`, `id`, `experimentPath`, `evaluationEnabled` | Result/evaluation/artifact lifecycle fields. |

Existing AI request metadata passes through as an opaque dictionary for behavioral
compatibility. Runtime does not use benchmark identity for control flow.

## Minimum contracts

Place shared provisioning types in `ctxbench.core.provisioning` and re-export
them from `ctxbench.benchmark.models`, preserving existing imports and validation.

```python
class ContextSource(Protocol):
    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextContent: ...

@dataclass
class RuntimeRequest:
    task: str
    task_id: str
    instance_id: str
    provider: str
    model_name: str
    configuration: ProvisioningConfiguration
    surface_spec: dict[str, Any]
    params: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    cache_model_name: str | None = None

@dataclass
class ExecutionResult:
    ai_result: AIResult
    started_at: str
    finished_at: str
    duration_ms: int

class ProvisioningRuntime:
    def __init__(self, engine: Engine, context_source: ContextSource): ...
    def execute(self, request: RuntimeRequest) -> ExecutionResult: ...
```

`ExecutionResult` composes the existing lossless `AIResult`, keeping response,
error, usage, trace, raw response, tool calls, and provider metadata intact.
The runtime owns inline context loading, string-or-`json.dumps` conversion,
optional dataset instructions, OpenAI inline cache-key derivation, AIRequest
creation, execution timing, and `Engine.execute()`. It borrows rather than closes
the Engine or context source.

`cache_model_name` preserves the present split model-name behavior: AIRequest
uses `str(trial.params.get("model_name", ""))`; cache key resolution uses
`trial.modelName or trial.params.get("model_name") or ""` after context loads.

## Benchmark adapter

`ctxbench.benchmark.runtime_adapter.TrialRuntimeAdapter` provides:

```python
def to_runtime_request(self, trial: TrialSpec) -> RuntimeRequest: ...
def to_trial_result(self, trial: TrialSpec, execution: ExecutionResult) -> TrialResult: ...
```

It copies request inputs and reconstructs the current TrialResult. It owns empty
answer/status classification, benchmark trace-retention choices, metrics-summary
derivation from retained trace data, the unevaluated evaluation default, and all
trial/artifact fields. It performs no registry resolution, context access,
strategy dispatch, timing, model invocation, or tool handling.

## Future adaptation boundary

This extraction supplies stable execution results; it does not treat metrics as
selection knowledge. Later phases must add this explicit sequence:

```text
ExecutionResult -> RuntimeEvent/RuntimeObservation -> OperationalState
-> EligibilityEvaluator -> ProvisioningPolicy -> ProvisioningDecision
-> next RuntimeRequest
```

Events describe lifecycle facts. Observations attach configuration, measured or
reported latency/tokens, outcome, timestamp, and provenance. Operational state
keeps rolling, configuration-scoped history; policies select only among eligible
configurations. Before implementing this, specify state partitioning (provider,
model, dataset/task class and context size), windows/minimum samples, missing and
stale evidence, cold-start behavior, recovery probing, quality/cost/privacy
constraints, and reproducible records of requested, selected and fallback
configurations. Persisted benchmark metrics cannot automatically become policy
inputs because their availability currently depends partly on trace retention.

## Compatibility risks and acceptance gate

Preserve model-name precedence, JSON context serialization, timing boundaries,
error distinction, trace/usage retention, inline zero-valued tool metrics,
metadata keys, adapter fallback, and shared Engine/rate-control state.

The inline migration is accepted only when provider-free differential tests show
equivalent AIRequest, ModelInput, AIResult-derived TrialResult, serialized
responses and traces for success, empty, error, cache, metadata, context and
retention cases; non-inline regressions remain green; and a direct runtime test
works without constructing or importing benchmark models.
