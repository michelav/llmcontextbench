# Workflows

LLMCtxBench has two peer workflows over shared dataset, runtime, execution, evaluation, and
analysis services. Dataset acquisition and inspection are supporting commands.

## Benchmark

The benchmark plan freezes model/configuration assignments before execution:

```text
versioned definition → plan → manifest + resolved inputs + trials.jsonl
                   → execute → durable execution attempts → responses.jsonl projection
                   → eval → evals.jsonl + judge_votes.jsonl
                   → export / metrics / status
```

Every planned trial has a stable `trialId`. Each execution invocation is stored as a durable
attempt. `responses.jsonl` is rebuilt from those attempt records; it is not the recovery authority.

## Adaptive

The adaptive plan freezes requests, declared candidate invocations, feature schema, estimator,
and policy. For each request occurrence the MAPE-K controller monitors available runtime and
acceptance signals, analyzes SLO status, selects the next eligible candidate, executes through
the shared service, and updates Knowledge from calibration priors and strictly earlier request
observations.

```text
adaptive definition → plan → adaptive-plan.json + manifest
                    → execute → request decisions/delivery ledger + durable attempts
                    → responses.jsonl projection of delivered requests
                    → request/attempt analysis
```

Repeated task/instance occurrences have distinct `requestId` values, and every invocation has a
unique `executionId`. Failed and rejected attempts remain inspectable and count toward attempt
costs. Request outcomes report admission, acceptance, and delivery. Offline evaluation stays
separate from online controller observations.

## Dataset commands

Remote datasets are fetched explicitly with `llmctxbench dataset fetch`; local roots can be
inspected or planned directly. Dataset packages provide context, tools, features, and evaluators
through their declared capabilities. Dataset-specific behavior stays in its adapter.

## Artifact-only analysis

`export`, `metrics`, and `status` read existing artifacts without resolving or fetching datasets.
They rebuild derived projections from canonical records and do not call model providers.
See [artifact contracts](../contracts/artifacts.md) for authority, versions, provenance, and historical
artifact policy.

## Version policy

Benchmark definitions use `schemaVersion: 3` and `kind: "benchmark"`. Adaptive definitions and
plans use `schemaVersion: 3` and `workflowKind: "adaptive"`. Old Study and RepoQA adaptation
protocols, adaptive v1 definitions, and previous artifact versions are unsupported. Keep an earlier
checkout to analyze their outputs; the current CLI does not migrate them.
