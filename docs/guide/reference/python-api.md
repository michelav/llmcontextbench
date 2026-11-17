# Python API reference

`ctxbench.api` is the only public Python surface; everything else is internal. API functions do
not print or exit: they return result objects or raise `CtxbenchError` subclasses. Walkthrough:
[experiments in code](../experiments-in-code.md).

## Lifecycle

```python
plan(source, *, output=None, cache_dir=None, plugin_paths=(), logger=None, progress=False) -> Run
open_run(path) -> Run
```

`source` is a definition path, a definition mapping, or an `AdaptiveExperiment`. Benchmark
experiments are planned from a path or mapping. `plan` never calls a provider. `open_run` raises
`RunNotFoundError` when the directory has no manifest.

```python
class Run:
    root: Path
    kind: str                       # "benchmark" | "adaptive"
    manifest: Mapping

    def status(self, *, by=None) -> RunStatus
    def execute(self, *, retry_uncertain=False, force=False, selector=None,
                logger=None, progress=False, plugin_paths=()) -> ExecuteOutcome
    def evaluate(self, **options) -> PhaseOutcome
    def export(self, **options) -> PhaseOutcome
    def metrics(self, *, output=None, group_by=None, force=False, selector=None,
                evaluation_status=(), not_evaluation_status=(), logger=None) -> MetricsOutcome
    def metric_tables(self) -> Mapping[str, Sequence[Mapping]]
    def responses(self) -> Iterator[Mapping]
    def requests(self) -> Iterator[Mapping]      # adaptive only
    def attempts(self) -> Iterator[Mapping]      # adaptive only
    def trials(self) -> Iterator[Mapping]        # benchmark only
```

`execute` is the only call that runs answer generation; `evaluate` the only one that runs
judges. Kind-specific readers raise `ExecutionStateError` on the wrong kind. Outcome objects
(`RunStatus`, `ExecuteOutcome`, `MetricsOutcome`, `PhaseOutcome`) carry counts and a one-line
`summary`.

## Adaptive experiments

```python
AdaptiveExperiment(id, dataset, models, surfaces, configurations, candidates, workload, policy,
                   window, seed=0, output="outputs", labels={}, task_params={},
                   execution_options={}, acceptance={}, signals=(), goals=(), disturbances=(),
                   evaluation={}, trace={}, allow_mixed_models=False)
```

Each section takes the mapping of the [definition file](definition-adaptive.md) or a builder:

| Builder | Section |
|---|---|
| `Model(provider, name, model_params={})` | an entry of `models` |
| `Configuration(strategy, representation, surface)` | an entry of `configurations` |
| `Candidate(id, model, configuration, labels={})` | an item of `candidates` (a list of builders or a mapping) |
| `PolicyRef(ref, params={}, sources=())` | `policy` |
| `Window(requests=None, all=False, mode="sliding")` | `window` |
| `Goal(id, signal, statistic, upper=None, lower=None, scope="system", window=None)` | an item of `goals` |
| `Acceptance(minimum_response_length=0)` | `acceptance` |
| `SignalRef(id, assessor, sources=())` | an item of `signals` |
| `Disturbance(name, component, kind, first_sequence, last_sequence=None, seed=0, delay_ms=None, failure_rate=None, candidates=(), version="1")` | an item of `disturbances` |
| `WorkloadRequest(task_id, instance_id, request_id=None, labels={})` | an item of an explicit workload |
| `Scenario(workload, disturbances=())` | `.to_sections()` returns `workload` and `disturbances` |

Every builder has `to_definition()` and `from_definition(mapping)` and validates with the same
schema as a file.

## Datasets and workloads

```python
load_dataset(ref, *, cache_dir=None) -> DatasetHandle   # .task_ids, .instance_ids, .feature_schema
Workload.explicit(requests) -> Workload
Workload.generate(dataset, segments, *, seed, tasks=(), instances=(),
                  sampling="with_replacement", label_features=()) -> Workload
Segment(size, where={})
```

`load_dataset` resolves local datasets only; it never downloads.

## Analysis

```python
summarize(runs, *, signals) -> list[dict]
headroom(run, *, signal, objective="min", by=None)
```

Both read artifacts only. `summarize` returns one row per adaptive run: labels, policy, seed,
`privileged`, `mixedModels`, rate-limit settings per model, workload digest, request counts by
state and failure category, per-signal totals over all attempts and over delivered requests,
and goal violations. `headroom` compares the best static candidate with a per-request oracle over
a benchmark run; the oracle is an upper bound that request-blind policies cannot reach.

## Extension contracts

`Policy`, `Decision(candidate_id, reason, memo=None)` and `CandidateRef(candidate_id, labels)`
are exported for policy authors; see
[adaptive experiments](../adaptive-experiments.md#policies) and the
[policy contract](../../architecture/workflows/adaptive.md#policy-contract). The state a policy
receives is described there as `SystemState`.

## Errors

```text
CtxbenchError
├── DefinitionError        invalid experiment or definition
├── ArtifactError          missing, corrupt or unsupported artifacts; fingerprint mismatch
│   └── RunNotFoundError   no planned run at the path
├── CapabilityError        the dataset or provider cannot support a declared requirement
└── ExecutionStateError    locked run, uncertain attempt without retry_uncertain, wrong run kind
```

Each class also derives from the matching built-in exception (`ValueError`,
`FileNotFoundError`, `RuntimeError`). `PolicyContractError` (a `ValueError`, exported for policy
authors) reports an invalid policy or decision; the API raises it wrapped in `DefinitionError`
at `plan` and in `ExecutionStateError` at `execute`, with the original as `__cause__`.
