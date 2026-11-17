# Experiments in code

Every lifecycle step is available in Python through `ctxbench.api`. An adaptive experiment can
be read from a definition file or built in code; both give the same stored definition, so the
plan, `resolved.json` and the execution fingerprint are identical for equal experiments. The
full surface is in [Python API](reference/python-api.md).

## Run the example

```console
python examples/adaptive/code_built.py outputs/code-built
```

It prints the planned requests, the execution summary, each request's decision, and where the
metrics were written.

## Walkthrough

`examples/adaptive/code_built.py` loads the dataset, generates a workload, builds the
experiment, plans it and runs it.

**Load the dataset.** `load_dataset` resolves a local dataset (it never downloads) and exposes
what a workload needs: task IDs, instance IDs and the declared request features.

```python
dataset = load_dataset(DATASET_ROOT)
```

**Generate a workload.** `Workload.generate` draws an ordered request list. The draw depends
only on the seed, the segment index and the sorted pool, so equal inputs give equal workloads.
`label_features` copies feature values into each request's labels for later analysis; features
are never visible to the policy.

```python
workload = Workload.generate(dataset, [Segment(4)], seed=17,
                             sampling="with_replacement", label_features=("validation_type",))
```

A segment can filter the pool by declared features, for example
`Segment(10, where={"<feature>": "<value>"})`, or a numeric range
`{"<feature>": {"min": 0, "max": 1000}}`. `Workload.explicit([...])` takes a fixed list of
`WorkloadRequest(task_id, instance_id, request_id=None, labels={})` instead.

**Build the experiment.** Each section accepts a builder or the equivalent mapping from the
[definition file](reference/definition-adaptive.md):

```python
experiment = AdaptiveExperiment(
    id="code-built-adaptive-example",
    dataset={"root": str(DATASET_ROOT)},
    models={"mock": Model("mock", "mock-model")},
    surfaces={"full": {"type": "full_context"}},
    configurations={"inline-json": Configuration("inline", "json", "full")},
    candidates=[Candidate("A", "mock", "inline-json")],
    workload=workload,
    policy=PolicyRef("static", {"candidate": "A"}),
    window=Window(requests=4),
)
```

Builders validate with the same schema as a file, so an invalid value fails with the same field
name. `X.from_definition(mapping)` turns a loaded section back into a builder.

**Plan and run.** `plan` returns a `Run` handle bound to the output directory; `open_run(path)`
returns the same handle for an existing run.

```python
run = plan(experiment, output=output)
outcome = run.execute()
for request in run.requests():
    decision = request["attempts"][0]["decision"]
    print(request["requestId"], request["state"], decision["candidateId"], decision["reason"])
print(run.metrics().summary)
```

`plan` never calls a provider; `Run.execute()` is the only call that runs answer generation and
`Run.evaluate()` the only call that runs judges. API functions do not print; they return result
objects or raise `CtxbenchError` subclasses.

## Scenarios

`Scenario(workload, disturbances=(...))` bundles a workload with `Disturbance` builders;
`scenario.to_sections()` returns the `workload` and `disturbances` sections to pass to
`AdaptiveExperiment`. A scenario is not stored on its own.

## Studies

Matrices of policies, seeds and workloads, pairing of runs and statistics belong in your
scripts. Plan one run per condition, then compare them with `summarize`:

```python
from ctxbench.api import summarize
rows = summarize([run_a.root, run_b.root], signals=["total_tokens", "latency_ms"])
```
