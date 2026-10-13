# Reusable RepoQA baselines and adaptation studies

Definitions live in `examples/studies/`; generated JSON Schemas live in
`schemas/studies/`. The experiment owns dataset, model, configurations, operation
surfaces and evaluation. `baseline.json` adds a language-stratified target split,
integer workload seeds, repetitions and context budget. `study.json` references a
frozen baseline and supplies policies, held-out seeds, repetitions, scenarios and
comparison pairs. Paths are relative to the declaring definition.

Prepare a baseline, inspect `prepared.json`, then execute its calibration episodes:

```bash
llmctxbench study baseline prepare --definition examples/studies/baseline.repoqa-five.json --output baselines/repoqa-five
llmctxbench study baseline execute --prepared baselines/repoqa-five/prepared.json
llmctxbench eval baselines/repoqa-five/episodes/EPISODE_ID/responses.jsonl
llmctxbench study baseline freeze --prepared baselines/repoqa-five/prepared.json
```

The generated matrix is configuration × seed × repeat. Each episode executes its
whole calibration workload once. Freeze requires terminal execution records and,
when enabled, evaluation records for every request. Failed responses remain in
observations; a successful response requires an evaluated result, while a failed
response may have a skipped evaluation. The immutable `frozen.json` contains raw
artifact hashes, per-request observations and all-sample estimates. Latency means
use successful requests; failure counts, usage coverage and known token totals are
separate. Evaluation usage is never counted as execution usage.

Prepare and run a held-out study:

```bash
llmctxbench study prepare --definition examples/studies/study.latency.json --output studies/latency
llmctxbench study status studies/latency
llmctxbench study episode --prepared studies/latency/prepared.json --policy adaptive --scenario stationary --seed 201 --repeat 1
llmctxbench study analyze studies/latency
```

`study prepare` verifies the baseline digest and every frozen raw artifact. It
persists exact held-out workloads, estimates, definitions, resolved defaults and
the policy × scenario × seed × repeat matrix. The same frozen baseline can initialize
separate latency, budget and reliability studies. Identical seeds and repeats receive
identical workloads and disturbance schedules across arms; each arm has its own
controller state. Study and baseline episode directories contain standard
`manifest.json`, `trials.jsonl`, `responses.jsonl` and traces so the regular
`llmctxbench eval`, `export` and `metrics` commands can operate on each constituent
execution. The study commands do not evaluate automatically.

Router defaults are a five-request switch cooldown, 10% material improvement,
five-observation rolling updates and probes every ten requests, rotating among
eligible alternatives. Candidate declaration order breaks ties. Study values for
budgets, latency limits, delays, quality floors and reliability thresholds are
explicit scientific choices; the example numbers are illustrative and require
pilot justification before held-out collection. A budget is per episode. Forecasts
are estimates and can overshoot; unknown usage stops further budget-dependent
requests. The ledger records known consumption, uncertainty and overshoot. The
optional quality floor uses calibration pass rates only. Reliability monitors the
chosen execution failure classes over its declared window; wrong answers remain
offline evaluation outcomes. It changes future routing only, with no same-request
fallback. Operation errors can coexist with a successful final answer and do not
imply transport failure.

Request delays apply to the chosen configuration inside measured execution time,
including inline. Tool-call delays require local MCP and apply once per call.
Analysis reports planned and completed coverage, unserved requests, failures,
latency, deadline misses, token and evaluation coverage, probes, paired target
cluster comparisons and derived latency timelines. Targets and frozen baselines are
shared across arms and seeds, so they are not independent replications. Incomplete
matrices remain visible in the report.

Episode requests are sealed before execution. Resume replays completed packets and
refuses an uncertain provider attempt unless `--retry-uncertain` is explicit.
Such a retry may duplicate a charged call, so its prior consumption remains unknown.
A budget policy stops further service after that uncertainty. Prepared/frozen
artifacts bind experiment, dataset and measurement source fingerprints; changing
those inputs requires a fresh compatible baseline. Historical adaptation commands
and runs remain readable under their legacy protocol. The older
`repoqa-lean-surface-plan.md` restriction excluding local functions from adaptation
is superseded for this V3 study protocol. Corrected MCP error flags require fresh
measurements; old traces are not rewritten.

No command in this guide should be run against a paid provider without a separately
approved collection budget. `prepare`, `freeze`, `status` and `analyze` are provider
free. The sample definitions do not establish a token, latency or reliability
benefit; compare individual policies with fixed configurations before considering
combined policies.
