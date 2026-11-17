# Workflow contract

LLMCtxBench has two peer workflows over shared dataset, runtime, execution, evaluation and
analysis services:

```text
benchmark: definition → plan (frozen trial matrix) → execute (durable attempts) → eval → export / metrics / status
adaptive:  definition → plan (frozen requests, catalogue, policy) → execute (one decision and
           at most one attempt per request) → eval → export / metrics / status
```

- [Benchmark workflow](benchmark.md): every execution is known at plan time.
- [Adaptive workflow](adaptive.md): a request-blind policy chooses a candidate per request at
  run time.

## The `Workflow` protocol

Both workflows implement one protocol (`ctxbench/core/workflow.py`). It has no method bodies and
no shared state; common behaviour lives in services used by composition. There is no
`Study`-like parent type.

```python
class Workflow(Protocol):
    kind: ClassVar[str]                     # "benchmark" | "adaptive"

    def load_definition(self, source, *, logger=None) -> Any
    def plan(self, definition, *, output, cache_dir, plugin_paths=(), logger=None,
             progress=False) -> PlanOutcome
    def status(self, root, *, by=None) -> RunStatus
    def execute(self, root, *, options: ExecuteOptions, logger=None) -> ExecuteOutcome
    def prepare_responses(self, root) -> Mapping[str, Any]
    def responses(self, root) -> Iterator[Mapping]
    def metric_tables(self, root) -> Mapping[str, Sequence[Mapping]]
    def write_metrics(self, roots, *, options: MetricsOptions, logger=None) -> MetricsOutcome
```

| Operation | `BenchmarkWorkflow` (`benchmark/workflow.py`) | `AdaptiveWorkflow` (`adaptive/workflow.py`) |
|---|---|---|
| `load_definition` | benchmark schema v3, resolved definition mapping | adaptive schema v4, `AdaptiveExperiment` |
| `plan` | expand the trial matrix | freeze requests, candidates, policy, signals, goals, disturbances |
| `execute` | run the selected trials | run the decision loop |
| `status` | trial counts | request states |
| `responses` | one per trial | the delivered response per request |
| `metric_tables` | trial rows, aggregates | request, attempt and goal rows |

Result types (`PlanOutcome`, `RunStatus`, `ExecuteOutcome`, `MetricsOutcome`) carry counts and a
one-line `summary`. Workflows never print; the CLI prints the summary.

Kind-specific operations are not in the protocol: `AdaptiveWorkflow` adds `requests(root)` and
`attempts(root)`, `BenchmarkWorkflow` adds `trials(root)`. `ctxbench.api.Run` forwards them and
raises `ExecutionStateError` on the wrong kind.

`ExecuteOptions` carries `retry_uncertain`, `force` and `selector`. A workflow rejects what it
does not support with `ExecutionStateError`; the adaptive workflow rejects `force` and
selectors, because they would break the frozen causal order.

## The registry

`WorkflowRegistry` (`core/workflow.py`) is the only place that reads the workflow kind:

- a definition or manifest with `workflowKind` uses that kind; one without it is a benchmark;
- a definition object is matched against each workflow's `definition_types`;
- a run directory uses its manifest; a directory without a manifest goes to the default
  (benchmark) workflow, which reports the error;
- `metrics` over several inputs uses the default workflow.

`ctxbench/api/workflows.py` builds the registry from both implementations, so `core` never
imports a workflow and `adaptive` never imports `benchmark`. `commands/*.py` and `api/run.py`
contain no comparison on the kind; a test enforces this. A third workflow kind is one new
implementation and one registry entry.

## Shared phases

`eval` and `export` have one implementation each in `ctxbench/phases/`. They receive the
workflow's `prepare_responses` and an `emit` callable, so they import neither a workflow nor the
API. `export`, `metrics` and `status` read existing artifacts only: they do not resolve or fetch
datasets and do not call model providers.

## Shared execution and recovery

Every external invocation has a unique `executionId`. `TrialExecutionService`
(`execution/service.py`) owns session lifecycle, durable attempt records and replay. A saved
terminal attempt is authoritative and is replayed, never re-invoked; a `started` attempt without
a result is uncertain and is retried only with `--retry-uncertain`. `responses.jsonl` is a
projection rebuilt from records without provider calls.

## Phase separation

Answer generation (`execute`), online assessment (adaptive, inside the attempt) and offline
evaluation (`eval`) keep separate usage records and separate metric columns. Offline
evaluation results never reach a policy.

## Dataset commands

`llmctxbench dataset fetch` and `llmctxbench dataset inspect` are supporting commands outside
the workflow lifecycle. Dataset packages provide context, tools, request features and online
assessors through declared capabilities; dataset-specific behaviour stays in its adapter.

See also: [artifact contracts](../contracts/artifacts.md), [adaptive plan](../contracts/adaptive-plan.md),
[manifests](../contracts/manifest.md), [records](../contracts/records.md).

## Version policy

Benchmark definitions use `schemaVersion: 3` and `kind: "benchmark"`; adaptive definitions use
`schemaVersion: 4` and `workflowKind: "adaptive"`. Earlier definitions and artifact versions,
the retired `Study` workflow and RepoQA adaptation campaigns are unsupported; there is no
migration. Keep an earlier checkout to analyse their outputs.
