# Workflow architecture and contracts

LLMCtxBench has two peer workflows over shared dataset, runtime, execution, evaluation,
and analysis services:

```text
benchmark: definition → frozen trials → durable attempts → evaluation → analysis
adaptive:  definition → MAPE-K requests → durable attempts and decisions → delivery → analysis
```

Benchmark planning freezes candidate assignments before execution. Adaptive planning
declares eligible candidates and policy; at runtime the controller observes available
signals, analyzes acceptance/SLO status, plans the next eligible candidate, executes it,
and updates Knowledge from calibration priors and strictly earlier observations.
Adaptive execution uses `ExecutionRequest` and does not construct benchmark `TrialSpec`
records as its execution API.

## Shared execution and recovery

Each external invocation has a unique `executionId`. The shared execution service owns
session lifecycle, retries, recovery, timing, and durable attempt records. Benchmark
trials and adaptive requests adapt their workflow contracts to that service. A saved
attempt is authoritative; response collections are projections rebuilt without provider
calls. Resume preserves completed attempts and reports uncertain interrupted attempts
according to the explicit retry policy.

## Workflow authority

- Benchmark manifests and trial plans freeze static assignment. Execution records hold
  every attempt; `responses.jsonl` is a derived view.
- Adaptive request records hold every decision and delivered/failed disposition.
  Execution records retain every attempt; adaptive `responses.jsonl` contains only the
  response delivered for each served request.
- Evaluation records remain separate from execution and controller observations.
  Offline evaluation does not become online Knowledge for the active episode.

See [artifact contracts](../contracts/artifacts.md), [adaptive plan contract](../contracts/adaptive-plan-v3.md),
and the [architecture assessment and removal plan](../../sprints/adaptive-framework/architecture-assessment-and-plan.md).

## Support policy

Current benchmark definitions use `schemaVersion: 3` and `kind: "benchmark"`. Adaptive
plans use `schemaVersion: 3` and `workflowKind: "adaptive"`. Historical `Study`, RepoQA
adaptation campaigns, adaptive v1 definitions, legacy CLI commands, and prior artifact
versions are retired. They are not compatibility inputs; retain an earlier checkout to
analyze their outputs. No generic `Study` abstraction replaces those protocols.
