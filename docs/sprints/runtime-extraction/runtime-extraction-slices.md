# Runtime Extraction Implementation Slices

> Current architecture and workflow contracts are documented in [workflow-contracts](../../architecture/workflows/workflow-contract.md).

Use this sequence with the baseline in
[`runtime-extraction.md`](runtime-extraction.md) and the long-term roadmap in
[`../llmcontextbench-evolution-plan.md`](../evolution-plan/llmcontextbench-evolution-plan.md).
Implement one green slice per commit. Do not begin the next slice until the
preceding acceptance gate passes.

| Slice | Goal | Likely files | Focused checks | Risk | Suggested commit |
|---|---|---|---|---|---|
| 1 | Establish provider-free inline compatibility fixtures and capture baseline behavior. | `tests/test_ai.py`, new focused runtime tests, architecture note | Request, prompt, result, serialized response/trace comparisons; deterministic clock fixtures. | A weak oracle misses metadata, timing, cache or retention drift. | `test: characterize inline execution compatibility` |
| 2 | Add benchmark-independent provisioning and runtime contracts plus deterministic translation. | `src/ctxbench/core/provisioning.py`, `src/ctxbench/runtime/models.py`, `src/ctxbench/benchmark/runtime_adapter.py`, `benchmark/models.py`, import-boundary tests | Existing configuration imports/validation; adapter mappings; runtime imports free of benchmark. | Moving `ProvisioningConfiguration` breaks subclass identity or public imports. | `refactor: introduce trial-independent runtime contracts` |
| 3 | Implement `ProvisioningRuntime` and route `inline` through it. Keep all tool strategies on the existing executor path. | `src/ctxbench/runtime/runtime.py`, `src/ctxbench/benchmark/executor.py`, tests | Legacy-versus-runtime inline equivalence; context exceptions; cache key; shared Engine behavior. | Timing and model-name/cache precedence drift. | `refactor: execute inline through provisioning runtime` |
| 4 | Prove benchmark independence and lifecycle compatibility; record evidence. | Runtime tests, artifact/CLI/lifecycle/metrics tests, architecture note and worklog | Direct runtime execution with an in-memory context source; planning/execute artifact contracts; resume/export/metrics/status regressions. | Indirect benchmark import or artifact-output change. | `test: prove inline runtime and artifact equivalence` |

Slices 1–4 are complete for `inline`. The verification evidence appears in
`runtime-extraction.md`; do not start the `local_function` extraction until this
baseline remains green on the current branch.

## Required test matrix

- Text, JSON-object and Unicode context; unsupported representation and context
  source failures.
- Success, empty/whitespace response, Engine error, missing usage, raw response,
  provider metadata and cache/reasoning token fields.
- Every trace-retention flag, with tracing enabled and disabled, including trace
  file serialization.
- Default and explicit OpenAI cache keys, including distinct `modelName` and
  `params["model_name"]` values, using mocks only.
- Registry materialization fallback and reuse of a caller-supplied Engine/rate
  control state.
- Existing `local_function`, `local_mcp` and `remote_mcp` behavior remains
  unchanged and is not routed through the new runtime yet.

## Completion evidence

Record the exact provider-free commands and pass counts in the worklog. The
pre-extraction baseline was:

```bash
pytest -q tests/test_ai.py tests/test_provisioning_configurations.py tests/test_import_boundaries.py
```

Result: `64 passed`.

Then run focused runtime/adapter tests followed by relevant artifact, CLI,
lifecycle and metrics tests. Do not run `llmctxbench execute` or
`llmctxbench eval` against providers for this refactor.

## Deferred sequence

After Slice 4 passes: extract `local_function`, prove equivalence, then address
the remaining strategies. Only after strategy parity should the project specify
runtime events, observations, configuration-scoped operational state,
eligibility, fixed policy and deterministic rule policy. Adaptive selection must
be a separate specification with an artifact/reproducibility design; it is not a
follow-on implementation detail of inline extraction.
