# Reusable baselines and adaptation studies

Status: implemented and fixture-validated. Level 3. Revised 2026-10-13 for simplicity.

## Objective

Support a reusable five-configuration RepoQA baseline and separate token-budget,
latency and reliability studies. Replace the fixed two-candidate protocol with
small validated definitions. Preserve existing runs and standard benchmark artifacts.

Categories: CLI, planning, schemas, operation surfaces, adaptive execution, recovery,
accounting, analysis and documentation. Implementation is complete with provider-free fixtures. Paid runs still require
separate authorization and an explicit budget.

## Simplicity review

The earlier draft exposed implementation and provenance details as user choices and
introduced lifecycle layers before they were necessary. This revision supersedes it.

| Earlier proposal | Simpler decision |
|---|---|
| Workload IDs plus numeric seeds | Plain integer seeds; no aliases |
| Named episode groups with repeated workloads/configurations | One baseline matrix: configurations × seeds × repeats |
| Baseline collection plus independently managed calibration snapshots | One frozen baseline containing measurements and derived estimates |
| Study repeats experiment, population, features and context limits | Inherit them from its baseline |
| Mandatory IDs, kind and user-supplied digests | File/output paths identify definitions; preparation generates identities and hashes |
| Generic grouping, feature and ordering configuration | One documented RepoQA protocol in V1 |
| Configurable estimator/algorithm versions on every policy | Versions recorded by implementation in frozen artifacts |
| Separate baseline evaluation declaration | Reuse experiment evaluation |
| Historical reuse modes, parent collections and collection merging | Reuse one compatible frozen baseline; otherwise collect a new one |
| Generic analysis configuration | Fixed documented analysis; explicitly select comparison pairs |
| Monetary/shared budgets, unknown-usage estimation modes | Per-episode token budget; stop budget-dependent execution on unknown usage |
| User-configurable constraint priority engine | Individual typed policies first; combined policy deferred |

Keep scientific controls needed by actual studies: seeds, repeats, split size,
configuration selection, policy parameters, token budget, deadline, disturbance
scope/range, and comparison pairs. Do not hide scientific behavior: record all
resolved defaults and implementation versions in generated plans.

## Two authored definitions

Keep the existing experiment schema for dataset, model, parameters, configurations,
surfaces, evaluation and tracing. Add `baseline.json` and `study.json`, with typed
validation, unknown-field rejection and generated JSON Schema. The examples below show executable syntax. Numeric values are illustrative.

### Baseline definition

```json
{
  "schemaVersion": 1,
  "experiment": "./experiment.repoqa-baseline.json",
  "split": { "seed": 42, "calibrationTargetsPerLanguage": 1 },
  "seeds": [101, 102, 103],
  "repeats": 2,
  "contextLimit": 32768,
  "outputReservation": 4096
}
```

Configurations come from the experiment's existing `factors.configuration`; do not
list them again. Use five distinct configurations: inline full, local MCP default,
local function default, local MCP lean and local function lean. Retain existing
strategy names and use distinct configuration IDs. One answering model per baseline.

The split is generated once at preparation. RepoQA uses target-level grouping,
stratified by language; all context variants stay together. Save exact calibration
and held-out membership in the generated baseline plan. No target count is hard-coded
in the engine. V1 retains the current supported variant sizes and balanced workload
ordering; unsupported populations fail clearly. The adapter owns field mappings.

All baseline episodes are stationary and use one fixed configuration. Membership is
exactly configuration × seed × repeat, expanded during preparation. The example with
five configurations yields 30 episodes. Every episode executes its complete ordered
calibration workload once. Seeds change order; repeats rerun that same order. Generated
episode IDs identify execution records; the user does not author IDs or group labels.
Candidate execution order is counterbalanced deterministically and persisted.

Missing and failed executions remain visible in the manifest. A completed episode
with failed requests is still evidence; an interrupted episode is not silently
excluded. Freeze requires all planned requests to have terminal records and configured
evaluation to be complete. Missing token usage is retained with coverage indicators.

New baseline/study definitions own repetitions. Require the referenced experiment's
`execution.repeats` to be 1 to avoid two repetition multipliers. Legacy commands
retain their existing behavior. Context/output settings must agree with model params.

### Study definition

```json
{
  "schemaVersion": 1,
  "baseline": "../baselines/repoqa-five/frozen.json",
  "seeds": [201, 202, 203],
  "repeats": 1,
  "policies": {
    "inline": { "type": "fixed", "configuration": "inline-code-full" },
    "frozen": { "type": "router", "adaptive": false },
    "adaptive": { "type": "router", "adaptive": true }
  },
  "latencyLimitMs": 6000,
  "scenarios": {
    "stationary": [],
    "inline-delay": [
      {
        "configuration": "inline-code-full",
        "scope": "request",
        "delayMs": 5000,
        "firstRequest": 21,
        "lastRequest": 44
      }
    ]
  },
  "comparisons": [["adaptive", "frozen"], ["adaptive", "inline"]]
}
```

The baseline supplies the experiment, candidate catalog, context budget, held-out
membership, feature mapping and baseline estimates. An optional `configurations`
list restricts that catalog; omission uses all candidates. This is selection, not
redefinition. Fixed-policy configurations must belong to the selected catalog.

Policy/scenario names are useful keys because commands and comparisons reference
those objects. Seeds need no names. All example configuration IDs must exist in the
referenced experiment; no special inline ID is required by the new engine.

Optional study controls are `tokenBudget` (per episode), `latencyLimitMs`, and
`minimumCalibrationPassRate`. Each policy type declares which controls it requires;
reject irrelevant or contradictory fields. No monetary budgets in V1. Without a
quality floor, report quality but do not silently exclude configurations by quality.

Policies are a closed set: fixed, router (frozen/adaptive), budget, and reliability.
Expose parameters only where they alter the research question: probe interval,
cooldown, update window, improvement threshold, and for reliability, failure classes,
minimum observations and failure-rate threshold. Parameter units/ranges/defaults
must be specified before that policy's implementation. Generated plans record the
resolved settings and policy version. No generic algorithm registry or expressions.

Study episodes are policy × scenario × seed × repeat over the inherited held-out
population. Comparisons use identical workloads, scenarios and independent policy
states. Request ranges are one-based, inclusive and validated against workload length.
Stationary scenarios have empty disturbance lists. V1 delay scope is `request` or
`tool-call`; tool-call scope requires a compatible tool runtime. No arbitrary fault
language. Fault injection for policy tests stays in fixtures initially.

Delay values and deadlines must be decided using calibration/pilot evidence before
held-out evaluation. V1 uses explicit numbers, not reference expressions or an
automatic delay sweep/selection engine. This deliberately defers the previous draft's
new disturbance-calibration CLI; legacy calibration remains available under its old
protocol. Record how values were chosen in the study's protocol notes. All arms receive
identical schedules, applied only when the targeted candidate executes.

## Frozen artifacts, reuse and reproducibility

A baseline has a prepared plan, raw execution/evaluation records, and one
`frozen.json` manifest containing references, hashes, coverage, and derived estimates.
There is no separately authored or managed calibration snapshot. Study preparation
copies/resolves the required estimates and binds the exact frozen baseline digest
in its own immutable `prepared.json`. Scientific changes require a new study output.

Freeze uses all calibration observations for summaries; estimator treatment of failed
or missing values is explicit. Preserve raw observations and distinguish success-only
latency estimates from failure rates and partial resource totals. Changing the legacy
last-five initialization is a new protocol version, not a semantics-preserving refactor.
Rolling updates may still use the policy's declared observation window.

Paths are resolved relative to the declaring file. Users supply paths; the program
computes hashes, versions, IDs and counts. Hashes are still verified at execution:
removing them from authored JSON does not remove integrity checks.

Reuse only compatible measurements: dataset/task/model/params, configurations,
operation/schema/prompt implementations, output/step/retry limits, measurement
boundaries and evaluator semantics must match. Record source revision, measurement
code identity, runtime/cache conditions, sessions and timestamps automatically.
Policy/analysis-only changes need not invalidate measurements; identifying that
boundary requires conservative tests. Unknown relevant incompatibilities fail reuse.
Full execution resume retains strict fingerprints. Environment drift remains a
limitation even with matching code; no stale-baseline bypass in V1.

No collection merging, observation cherry-picking, multiple split pooling, or legacy
baseline importer in V1. A new population/split/configuration campaign needs a new
baseline. Several studies may share one frozen baseline and held-out membership;
report that dependence. Reusing inspected held-out results for development does not
provide fresh confirmatory evidence merely by changing seeds. Plain small integer
seeds are recommended for new definitions; historical numeric seeds remain unchanged.

## Operations, policies and accounting

### Confirmed MCP error-flag defect

Read-only investigation of `runs/repoqa-adaptive-001` found 22 error-only tool
payloads recorded with `isError: false`: three calibration `read_file` calls and
19 episode calls (seven `read_file`, twelve `get_symbol`). Fixture reproduction
confirmed direct service results have `is_error=True`, while the same operation
through `MCPRuntime` returns identical content with `is_error=False`.

RepoQA's registered MCP handlers return only `.content`, discarding the correctly
set service flag. Fix that boundary before new baseline collection. Preserve the
error flag in the MCP response and retain useful normalized content; do not add
payload-key heuristics to the generic runtime. Check the equivalent content-only
Lattes wrappers with a reproducer; their behavior has not yet been verified.

Existing direct-service error and MCP-success tests pass but do not cover error
propagation through the protocol. Add runtime and fixture-strategy regression tests
covering errors, successful results, trace flags and subsequent model inputs.
These are operation-error reporting defects, not demonstrated transport failures.
An individual tool error does not imply the whole request ultimately fails.
Keep old traces unchanged and document the limitation in historical comparisons;
do not reuse them as corrected reliability evidence or bypass source fingerprints.

### Lean operations and policy behavior

Implement the existing lean surface contracts from
`docs/development/repoqa-lean-surface-plan.md`: path lists; flat deduplicated symbols
with stable IDs, names, kinds and available documentation; complete code/content
retrieval. Preserve visibility, filtering, deterministic order, explicit errors and
default operations. This design supersedes that document's restriction excluding
local functions from the adaptive candidate set, not its operation contracts.

Verify equal model-visible schemas, operation content and limits across local MCP
and local functions. Smaller payloads do not prove fewer total generation tokens or
preserved quality. Keep dataset and scorer unchanged.

Generalize selection/probing to N candidates with deterministic tie-breaking and
rotation among alternatives. Do not assume a required inline -> MCP -> local function
progression. Include relevant fixed arms and the cheapest calibration-qualified
fixed configuration when assessing budget adaptation; a dominant fixed strategy is
an acceptable finding.

Budget policy uses observed consumption plus estimated remaining work, accounting
for every known model call, failed attempt and probe exactly once. Preserve partial
and unknown usage. Stop budget-dependent execution when consumption is unknown or
no option is feasible; record unserved requests and overshoot. No hard-cap guarantee.
Execution and evaluation usage remain separate with existing provenance categories.

Request-scoped delays run inside the controller's measured outer execution boundary.
Record requested and actual delay separately from overall latency. Per-tool delay
and per-request delay are distinct treatments. Use fake clocks in tests.

Diagnose saved failures before implementing reliability adaptation. Classify transport,
operation, model-tool-use, step-limit, provider and unknown failures from evidence.
Wrong answers remain quality outcomes. Reliability changes future selections; same-
request fallback is deferred because it requires multiple-attempt identity/recovery.
Never use held-out scoring or ground truth as online controller observations.

Combined budget/latency/reliability policy remains a later research milestone after
individual studies show useful trade-offs; do not build a configurable priority engine
now. Repeated splits, split-manifest imports, historical initialization, monetary
budgets, generic features, custom estimators and collection extension are deferred.

## CLI and repository boundaries

Implemented commands:

```text
llmctxbench study baseline prepare --definition baseline.json --output PATH
llmctxbench study baseline execute --prepared PATH [--resume]
llmctxbench study baseline freeze --prepared PATH
llmctxbench study prepare --definition study.json --output PATH
llmctxbench study episode --prepared PATH --policy ID --scenario ID --seed N --repeat N
llmctxbench study status PATH
llmctxbench study analyze PATH
```

No separate study calibrate/freeze steps: explicit scientific settings freeze during
prepare. Baseline execute selects only planned work. Keep evaluation explicit through
existing `llmctxbench eval`; it may incur provider costs depending on evaluator.
Standard export/metrics consume constituent execution directories. Preparation,
baseline freeze, status and analysis never invoke providers. No automatic paid chains.

Use a small `studies/` package for typed definitions, preparation and baseline reuse.
Keep execution/recovery in `adaptive/`, RepoQA operations/features in its adapter,
and providers unchanged. Do not preallocate modules for hypothetical capabilities.
Preserve existing `llmctxbench adaptation repoqa` and its script wrapper for the old
protocol. Do not rewrite `runs/repoqa-adaptive-001` or existing experiment files.

Retain trial/response/evaluation/judge-vote formats. Version new study manifests and
sidecars where optional objectives, failure evidence and budget state require new
contracts. Durable packets remain authoritative for recovery; summaries/plots are
derived. Preserve strict uncertain-attempt handling and deterministic replay.

## Analysis and acceptance

Use the existing RepoQA target-within-language bootstrap and paired comparisons,
with a documented default resampling seed/count recorded in results. Keep variants
and repeated executions clustered at the target level; episode seeds are not new
independent targets. Generalize arms and phase ranges from the prepared plan. No
new generic analysis DSL. Report planned coverage, failures/unserved requests,
quality, latency/deadlines, tokens/coverage, probes/switches, and budget consumption.

Acceptance: one fixture baseline initializes separate budget and latency studies;
plain integer seeds produce persisted deterministic workloads; five configurations
work through both local strategies; overlap/incompatible reuse is rejected; failed
observations retained; delay timing and budget replay correct; no old artifact changes.
Implementation was verified with provider-free tests. Paid provider collection remains a separate research step.

Before live collection finalize model, population, repeat counts, quality tolerance,
budgets, deadlines and reliability thresholds. Schema field validation and policy defaults are implemented in V3 artifacts.
