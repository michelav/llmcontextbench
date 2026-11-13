# Minimal adaptive workflow example

This provider-free definition contains one request and one declared mock candidate using adaptive
plan schema v3. From the repository root, prepare and inspect it with:

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
