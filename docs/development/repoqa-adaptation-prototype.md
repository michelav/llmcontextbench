# RepoQA Adaptive Provisioning Prototype

## Purpose and requested change

Deliver a small, reproducible single-domain prototype by the October 23, 2026
SEAMS deadline. The prototype will compare fixed and feedback-updating choices
between the existing inline-code and local-MCP RepoQA configurations under
stationary and controlled local-tool-latency conditions.

This is a research-only adaptation runner around the existing benchmark
execution path. It does not add a public CLI command, change the canonical
artifact schemas, introduce a new provisioning strategy, perform mid-request
fallback, or use learned policies. The existing inline runtime extraction at
`fdee3e0` remains the starting point; this work does not expand that extraction
to other strategies.

## Change categories

- Dataset provider and surface resolution: add RepoQA operation-surface support
  and enforce its allow-list.
- Local MCP and experiment execution: add a controlled delay hook used only by
  the RepoQA research runner.
- Trial execution and experiment workflow: choose one planned configuration
  per request between requests, then use the existing executor and evaluator.
- Metrics and documentation: record decisions in a sidecar and describe the
  experiment without changing response, evaluation, export, or metrics schemas.

## Current baseline and experiment population

The checked-in `datasets/repoqa` data contains 80 context instances: 20 target
groups across Java, Python, Rust, and TypeScript, each with 2k, 4k, 8k, and 16k
context-size variants. It currently has one task template (`Search Needle
Function`). The target group, rather than an individual size variant or repeat,
is the independent sampling unit for split and uncertainty analysis. Results
must be described as a study of this RepoQA retrieval task, not as evidence for
all RepoQA tasks or code question answering.

The two actions are fixed concrete configurations:

| ID | Strategy | Representation | Surface |
|---|---|---|---|
| `inline-code-full` | `inline` | `code` | full context |
| `local-mcp-repoqa-ops` | `local_mcp` | `json` | `list_files`, `list_symbols`, `get_symbol`, `read_file` |

Both use the same answering provider/model, prompt/task statement, dataset
snapshot, retry settings, and request order. The local-MCP surface exposes all
four existing RepoQA operations and no others.

## Proposed design

### Dataset surface and operation enforcement

Implement `RepoQADatasetAdapter.resolve_surface()` to accept full-context
surfaces and operation surfaces containing only the four supported RepoQA
operation names. Reject unknown or empty operation lists during planning.
Update `tool_provider()` and `mcp_server()` to accept the resolved
`allowed_operations` list. Filter tool discovery to that list and reject
disallowed calls at dispatch time, including direct calls to the in-process
service. Register only allowed tools in FastMCP. This prevents a model from
invoking a tool omitted from the treatment surface.

Update the adapter metadata that currently describes RepoQA as inline-only and
does not mention deterministic scoring. Keep the scorer and its threshold
unchanged; it remains outside the adaptation loop.

### Between-request runner and policies

Add a small `ctxbench.adaptive` package for decision records, policy state, and
selection rules, plus a RepoQA experiment entry point under `tools/repoqa/`.
The entry point consumes a normal planned trial catalog containing both
candidate configurations. It pairs candidates by task, instance, model, and
repeat, presents only permitted request features to the policy, selects one
candidate `TrialSpec`, and invokes `execute_runspec()` once. It reuses the
existing result serializer and deterministic RepoQA evaluation. A policy never
receives task statements, task tags, target identities, oracle data, evaluation
results, or phase labels.

Implement four arms:

- `always-inline`: always select the inline candidate.
- `always-local-mcp`: always select the local-MCP candidate.
- `frozen-router`: use calibration estimates and the routing rule below, but
  never update those estimates from runtime observations.
- `adaptive-router`: use the same initial estimates and rule, then update its
  estimates after each completed request.

The fixed arms do not probe. Frozen and adaptive routers force the inactive
eligible configuration on requests 10, 20, 30, 40, 50, and 60 of each episode.
Probe executions count in resource use and quality metrics. They use the same
schedule for both router arms. Frozen-router probe observations are logged but
do not update its estimates; adaptive-router probe observations do.

The controller receives measured `contextBytes`, mapped to `small` for the 2k
and 4k variants and `large` for the 8k and 16k variants. It also receives the
configured latency objective and the configuration-scoped estimates. It does
not receive the context-size suffix or target identifier as independent
features. Preflight context-window eligibility uses the selected model's
tokenizer when available; otherwise use a conservative deterministic estimate
and record its provenance as `estimated`. The answering model and its context
window must be locked before calibration.

For each configuration and size bin, estimate end-to-end latency and total
tokens from calibration. Maintain a trailing arithmetic mean over the last five
valid observations; require at least three observations before using an
runtime-updated bin estimate. Initialize each arm from the separate
calibration data. Missing token usage remains unavailable and is never treated
as zero.

Selection is deterministic:

1. Exclude configurations that cannot execute or fit the model context window.
2. If at least one eligible configuration is predicted to meet the latency
   objective, choose the one with the lowest estimated total tokens.
3. Otherwise choose the eligible configuration with the lowest estimated
   latency and record that it is predicted to miss the objective.
4. Retain an eligible incumbent during cooldown. A normal selection at index
   k blocks discretionary switches at k+1 through k+5; k+6 permits switching.
   Initial selection starts cooldown. After cooldown, meeting the objective
   takes precedence when the incumbent misses it, regardless of token cost.
   Otherwise require at least 10% improvement in the active criterion.
   Ineligibility overrides cooldown. Exact initial ties prefer `inline-code-full`.
   Known estimates rank before unavailable ones. When all latencies are missing,
   retain an eligible incumbent or initially choose inline and record attainment
   as unknown. Zero-valued ties do not justify a switch.
5. If no configuration is eligible, record an explicit `unserved` decision.
   Do not fabricate a response row or silently drop the request from the
   denominator.

Measure request wall time in the runner around the complete `execute_runspec()`
call, including context/tool setup and cleanup. Preserve the existing
`TrialResult.timing` meaning. Store this outer measurement separately as
`endToEndDurationMs` with provenance `measured`.

Add an optional internal local-MCP runtime decorator hook to
`execute_runspec()`. The default is `None` and preserves current execution. The
research runner supplies a RepoQA-only decorator that delays each local MCP
tool call by the phase's configured duration. The decorator must preserve the
underlying tool result and measure the actual delay in the outer end-to-end
time. It must not alter inline behavior, model parameters, or dataset contents.

### Decision and run artifacts

Keep all canonical benchmark artifacts unchanged. Each policy/seed output
directory contains the usual `manifest.json`, selected `trials.jsonl`,
`responses.jsonl`, `evals.jsonl`, and any standard export/metrics outputs, plus:

- `decisions.jsonl`: one versioned record for every scheduled request,
  including fixed arms, probes, failures, and unserved requests.
- `adaptive-run.json`: run-level policy, scenario, seed, data/model provenance,
  configuration catalog, latency objective, injection schedule, cache policy,
  and code revision.

Each decision record includes `schemaVersion`, request/trial identity when an
execution was selected, sequence index, policy/version, permitted features,
eligible candidates, estimates and provenance, selected configuration or
`null`, reason, probe/cooldown state, observed status, outer measured duration,
reported/estimated token values, and any error. Evaluation outcomes are not
written to the decision stream until the episode is complete; the controller
must not read them.

Write a selected trial row only when a configuration is executed. The manifest
contains both configuration definitions. Each response retains the existing
`configurationId` and treatment fields for the configuration actually run.
Policy and seed identity live in the output directory and run/decision sidecars,
not in `TrialResult` or the canonical schema. A scheduled request with an
execution error remains represented by its normal error response; a request
with no eligible action is represented as unserved in `decisions.jsonl` and
counts as a failure in all-request quality denominators.

Use separate output roots for calibration and for every
scenario/policy/seed. Isolate prompt-cache keys by policy and seed when the
provider supports it; otherwise counterbalance policy execution order and
record cache-related usage so warm-cache effects cannot systematically favor
one arm.

### Experimental protocol

Use a deterministic, language-stratified split. With split seed `20260929`,
select one target group from each language for calibration and keep the other
16 target groups held out. Keep all four size variants of a target in the same
split. Record the selected group IDs and the dataset content hash in
`adaptive-run.json` before any model execution.

Calibration uses four target groups × four context sizes × two configurations ×
two repeats: 64 executions. Use calibration only to initialize performance
estimates, set the latency objective, and choose the local-MCP delay. Freeze
these values before the held-out study. Set the experimental latency objective
to the pooled normal-condition p90 end-to-end latency across the two
configurations unless an application SLO is supplied before calibration. This
is an experiment threshold, not a production guarantee. Test per-tool delays of
100, 250, 500, and 1,000 ms; select the smallest delay that increases local-MCP
p95 latency by at least 25% and causes measurable objective violations in
calibration. Record and freeze it. If no tested delay meets that criterion,
report the stationary/context-size study and do not claim a latency-degradation
adaptation result.

Each held-out episode uses all 16 targets × four context sizes, giving 64
requests. Run two scenarios:

- **Stationary:** normal local-MCP latency for all 64 requests.
- **Degradation and recovery:** normal latency for requests 1–20, injected
  delay for requests 21–44, and normal latency for requests 45–64.

Within every phase, balance the four context sizes as evenly as possible and
shuffle the request order using the episode seed. Use three episode seeds; each
seed's workload and disturbance schedule is identical across all four systems.
The full evaluation is 64 requests × two scenarios × three seeds × four
systems (1,536 request executions). Repeated seeds quantify execution/order
variability; they do not increase the count of independent targets.

Use the selected single provider/model for every arm. Record the resolved model
ID and provider parameters, prompt/configuration IDs, retries, cache settings,
and price source if currency cost is reported. After calibration, estimate
main-run token/API cost and obtain explicit authorization before provider-backed
evaluation. Do not run judge models; RepoQA's existing deterministic scorer is
the only quality evaluator.

The primary contrast is adaptive versus frozen router on deadline-miss rate in
the degradation/recovery scenario. Secondary outcomes are total tokens per
request, RepoQA pass rate over all scheduled requests, end-to-end p50/p95,
switch/probe counts, decision overhead, and requests to react to degradation
and recovery. Report per-target paired differences and 95% bootstrap intervals
resampling held-out target groups within language, keeping all variants,
policies, scenarios, and seeds for a sampled target together. Treat quality as
an observed outcome, not a runtime guarantee; do not claim a quality
non-inferiority result without a predeclared margin and adequate evidence.

## Invariants and compatibility

- Runtime selection never sees evaluator/oracle data, RepoQA target labels, or
  scenario phase information.
- Each request has at most one selected configuration and one execution; there
  is no retry across configurations or mid-request fallback.
- Only the declared operation surface is discoverable and callable.
- Existing public strategy names, provisioning artifact version 2, trial IDs,
  `trials.jsonl`, `responses.jsonl`, `evals.jsonl`, judge artifacts, exports,
  and metrics semantics remain unchanged.
- Provider-reported, benchmark-measured, derived, estimated, and unavailable
  metrics remain distinct. Evaluation usage remains separate from execution
  usage.
- Calibration and evaluation data are disjoint by target group. The evaluator
  is run only after all request decisions in an episode have been made.
- All output is reproducible from the code revision, pinned dataset hash,
  model/prompt settings, split and episode seeds, and recorded policy/scenario
  configuration.

## Implementation slices

### Slice 1 — RepoQA surfaces and feasibility (September 29–October 1)

**Goal:** Enable and enforce the two RepoQA configurations without changing
scoring or strategy semantics.

**Likely files:** `src/ctxbench/adapters/repoqa/package.py`,
`src/ctxbench/adapters/repoqa/tools.py`,
`src/ctxbench/adapters/repoqa/mcp_server.py`, and focused RepoQA tests.

**Checks:** Test valid/invalid surface resolution; assert only allowed tools
appear in both the tool provider and MCP listing; verify direct calls to an
undeclared tool fail; verify all four declared tools work against fixtures;
verify the provider never reads `oracle.json` or native task/hidden prompt data.
Run the existing RepoQA tool, surface, planning, and artifact tests.

**Dependency:** None. **Risk:** FastMCP integration may differ from the direct
service behavior; test discovery and invocation through both paths.

**Suggested commit:** `feat: support RepoQA operation surfaces`

### Slice 2 — Policy contracts and deterministic tests (October 2)

**Goal:** Implement sidecar models, calibration initialization, frozen and
adaptive estimates, eligibility, selection, cooldown, and probes without model
calls.

**Likely files:** New `src/ctxbench/adaptive/` policy/controller modules and
`tests/test_adaptive_policy.py`.

**Checks:** Table-driven tests for each selection branch; one test per missing,
stale, ineligible, or tied estimate case; prove the frozen state never updates;
prove the adaptive state updates only from runtime observations; prove probes
and cooldowns behave identically in both routers.

**Dependency:** Slice 1's concrete configuration names and capabilities.
**Risk:** Sparse observations or missing token values must not be silently
converted to zero or create nondeterministic choices.

**Suggested commit:** `feat: add deterministic provisioning policies`

### Slice 3 — Episode runner and artifact integration (October 3–4)

**Goal:** Pair candidate `TrialSpec`s, choose one per request, execute through
`execute_runspec()`, and persist standard artifacts plus the two sidecars.

**Likely files:** New adaptive runner module, `tools/repoqa/` experiment entry
point, a narrow `execute_runspec()` local-MCP decorator hook, and runner tests.

**Checks:** Mock-engine tests for one response per selected request, explicit
error/unserved accounting, stable trial treatment metadata, versioned decision
records, and isolated sidecar paths; validate generated policy directories
with the standard artifact validator; verify evaluation can score the saved
responses without exposing results to the controller.

**Dependency:** Slice 2. **Risk:** Dynamic selection must still produce
manifest/trial/response rows accepted by existing validators and CLI lifecycle
commands.

**Suggested commit:** `feat: add adaptive RepoQA episode runner`

### Slice 4 — Calibration, freeze, and held-out evaluation (October 5–11)

**Goal:** Run the 64-execution calibration, freeze policy/SLO/injection
settings, then run the paired 1,536-execution held-out study after explicit
cost authorization.

**Likely files:** Experiment configs and the runner's output artifacts; no
canonical schema changes.

**Checks:** Verify data split/hash, paired request schedules, cache isolation or
counterbalancing, complete decision/response reconciliation, and absence of
evaluator inputs in policy state before starting the full study.

**Dependency:** Slices 1–3 and a successful pilot. **Risk:** If the pilot shows
no operating trade-off, stop and report context-fit or controlled-delay
resilience only; do not tune on held-out results.

**Suggested commit:** `experiment: run RepoQA adaptation episodes`

### Slice 5 — Analysis and submission package (October 12–22)

**Goal:** Recompute deterministic RepoQA scores, analyze paired outcomes,
document limitations, and prepare reproducible paper artifacts.

**Likely files:** `docs/repoqa.md`, a concise experiment protocol/results note
under `docs/`, and analysis scripts or notebooks only if needed to reproduce
reported tables/plots.

**Checks:** Re-run evaluation/export/metrics from saved responses; confirm
analysis joins decisions to actual configurations and uses all scheduled
requests in denominators; report uncertainty and negative results; rehearse
artifact reproduction from the pinned revision.

**Dependency:** Slice 4. **Risk:** The 20-target/one-task-template dataset
limits generalization; state this in the claims.

**Suggested commit:** `docs: report RepoQA adaptation prototype`

## Acceptance criteria

- RepoQA planning accepts the supported operation surface and rejects unknown
  operations. At runtime, tools not declared by the selected surface are both
  absent from tool discovery and rejected if called directly.
- The policy runner produces four comparable arms on identical paired
  workloads, with the adaptive and frozen routers differing only in whether
  runtime observations update their estimates.
- Every scheduled request has a decision record; every executed request has a
  standard response row or explicit error; unserved requests are recorded and
  counted as failures in the all-request analysis.
- The controller cannot access evaluator/oracle outputs or hidden phase labels.
- Standard artifact validation, RepoQA evaluation, export, and metrics work
  with policy-specific output directories and unchanged canonical schemas.
- The report includes execution and decision overhead, metric provenance,
  paired uncertainty, dataset/model/code provenance, failures, and conditions
  where adaptation does not help.

## Risks and explicit limits

- A local injected delay is a controlled MCP-tool latency experiment, not a
  claim about remote MCP network failures.
- The single task template and 20 target groups constrain external validity.
- Model/provider latency, prompt caching, and output variability can overwhelm
  a small pilot; record cache behavior and use a single locked model.
- A calibration-derived latency threshold is an experimental objective, not a
  user-facing service-level guarantee.
- Main model calls can be costly, especially for local MCP's multiple model
  steps. Pilot-derived cost estimates and explicit authorization are required
  before the full run.

## Tracking and validation

This document is the implementation plan and source of defaults for the
prototype. Record meaningful milestones in `docs/development/worklog.md` if
implementation spans multiple slices. No tests or provider-backed experiments
were run while preparing this plan.

## Frozen slice 2 contracts (policy version 2)

Workload preparation maps nominal 2k/4k variants to small and 8k/16k to large;
policies receive only explicit bins and measured context bytes, never identifiers
or suffixes. No implicit byte threshold exists. Callers supply precomputed input
token requirements, output reservation, context limit and tokenizer-derived or
explicitly estimated context-fit provenance; actual prompt budgeting is slice 3.

Every episode starts with independent state copied from calibration. No time-based
expiry applies: estimates stay usable within the episode (the stale-state rule).
Runtime means use the last five successful observations per configuration/bin.
Latency and tokens independently require three available samples; otherwise use
calibration, then unavailable. Calibration uses the same mean estimator without
that runtime minimum. Means are derived unless any input is estimated; sources
and sample counts remain visible. Failures are logged but excluded from means.

A scheduled probe executes the eligible alternative to the normal routing choice.
The normal choice alone commits incumbent/cooldown state. With no alternative,
there is no actual probe. Fixed arms never substitute an ineligible configuration.

Sidecar schemaVersion 1 uses explicit camelCase serialization. Decision envelopes
contain requestId, trialId, policy, policyVersion, decision (sequenceIndex,
features, eligibleCandidates, candidates, estimates, selectedConfiguration,
normalConfiguration, reason, probe, cooldownActive, objectiveAttainment),
status, endToEndDurationMs, tokens, error. Run envelopes contain policy/version,
scenario, seed, dataset/model provenance, configurationCatalog,
latencyObjectiveMs, injectionSchedule, cachePolicy and codeRevision.
Identity, execution outcome and scenario metadata remain outside policy inputs.
No sidecar writer or runner is included in slices 1–2. Canonical artifacts need no
migration; ad hoc consumers must adopt explicit bins and policy-owned observe().

### Slices 1–2 completion

Completed on 2026-10-02: operation-surface enforcement coverage, explicit policy
features and eligibility, versioned sidecar types, policy-owned observations,
per-metric rolling estimates, and deterministic routing/probes. The specified
seven-file acceptance set passed all 127 tests. See `worklog.md` for validation
commands and compatibility notes. Runner integration and provider experiments
remain unimplemented; this completion covers the model-free slices only.

## Resumable workflow implementation

The accepted A–E continuation replaces the earlier fresh-run-only implementation
scope. The research runner, controlled disturbances, frozen calibration and saved
episode analysis are implemented; paid calibration and the held-out study remain
separate authorized experiments. See [the executable protocol](repoqa-resumable-workflow.md)
and [slice tracking](../../specs/006-repoqa-adaptive-resume/worklog.md). Policy version 2,
decision/run schema 1 and canonical schemas remain unchanged. Recovery is between
requests, with replay and explicit uncertain-call retries.
