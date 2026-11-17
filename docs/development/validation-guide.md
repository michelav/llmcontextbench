# Provider-free workflow validation

The checked-in minimal examples use the mock provider and fake dataset. Run commands from the
repository root; they make no external model or MCP calls.

## Benchmark

```bash
llmctxbench plan examples/benchmark/static-minimal.json --output /tmp/ctxbench-benchmark
llmctxbench status /tmp/ctxbench-benchmark
llmctxbench execute /tmp/ctxbench-benchmark/trials.jsonl
llmctxbench status /tmp/ctxbench-benchmark
llmctxbench metrics /tmp/ctxbench-benchmark
```

The benchmark plan should contain `trials.jsonl` and a version-4 provisioning manifest. Execution
attempts are canonical under `execution-records/`; `responses.jsonl` is rebuilt from their results.

## Adaptive

```bash
llmctxbench plan examples/adaptive/minimal.json --output /tmp/ctxbench-adaptive
llmctxbench status /tmp/ctxbench-adaptive
llmctxbench execute /tmp/ctxbench-adaptive/adaptive-plan.json
llmctxbench status /tmp/ctxbench-adaptive
llmctxbench metrics /tmp/ctxbench-adaptive
```

The adaptive plan contains the ordered requests, the candidate catalogue and the policy. One
decision, the observation and the delivery per request are canonical in `adaptive-records/`,
durable attempts are under `execution-records/`, and `responses.jsonl` contains delivered
requests. Request and attempt metrics retain failed work. `examples/adaptive/window-threshold.json`
exercises a generated workload, two candidates, a goal and a disturbance the same way.

## Contract and test checks

Tests use markers to separate the fast default unit/contract layer from the workflow
integration layer. The small provider-free end-to-end cases cover both workflows.

Run the fast layer and then the integration layer with:

```bash
pytest -q -m "not workflow"
pytest -q -m workflow
pytest -q -m e2e
```
The complete suite is also provider-free by default; do not run benchmark execution against real
provider definitions unless that spend is intended.

Only version-3 benchmark definitions, version-4 benchmark artifacts, version-4 adaptive
definitions and adaptive plan version 4 are supported. Old study/RepoQA adaptation protocols and historical artifact readers have been
removed; retain an older checkout if those artifacts still need analysis.
