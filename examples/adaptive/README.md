# Adaptive workflow examples

`minimal.json` demonstrates planning from a static definition file. `code_built.py` demonstrates
the same workflow through the Python API, including workload generation from the fake dataset.
Both use the mock provider and make no network calls during planning.

Run the code-built example from the repository root with:

```bash
python examples/adaptive/code_built.py
```

The example uses `load_dataset(...)` to inspect available tasks, instances, and declared request
features. `Workload.generate(...)` samples an ordered workload; planning expands it into explicit
requests and stores the generator specification and pool digest in the adaptive plan.

## Static definition example

This provider-free definition contains one request and one declared mock candidate. From the
repository root, prepare and inspect it with:

```bash
llmctxbench plan examples/adaptive/minimal.json --output /tmp/ctxbench-adaptive
llmctxbench status /tmp/ctxbench-adaptive
```

Execution uses the mock provider and the checked-in fake dataset:

```bash
llmctxbench execute /tmp/ctxbench-adaptive/adaptive-plan.json
llmctxbench status /tmp/ctxbench-adaptive
llmctxbench metrics /tmp/ctxbench-adaptive
```

The frozen request, decision/delivery ledger, durable execution records, and `responses.jsonl`
show how request identity and invocation identity differ. The example declares no online quality SLO
and disables offline evaluation.
