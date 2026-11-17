# Review of the benchmark and adaptive workflow architecture plan

Reviewed document: [`architecture-assessment-and-plan.md`](architecture-assessment-and-plan.md)
Review date: 2026-11-11
Basis: reading `src/ctxbench/adaptive/v1.py`, `src/ctxbench/commands/execute.py`, the dataset
package protocol and capability report, `src/ctxbench/adaptive/types.py`, plus targeted searches
for callers. No tests were run, and the `studies/` runners were not read in depth.

## Verdict

The direction is right, but the plan is **not ready for implementation**. Several decisions are
still open, and WP1 and WP4 would end up making them by accident. Some "current state" claims do
not match the code. WP0, which is the plan's own gate, is not done: no baseline fixtures exist, and
the decisions listed under [Design gaps](#design-gaps) are missing.

## What holds up

- Treating benchmark and adaptive as peer workflows over shared services is better than
  "Level 1 / Level 2".
- The controller never builds provider or MCP clients, and routes come only from a declared
  candidate catalog.
- Unavailable quality is never zero or a satisfied SLO. Online signals are kept apart from offline
  evaluation, and assessor cost counts toward execution cost.
- The decision is persisted before execution, and resume replays records instead of re-deciding.
- The work packages are incremental and gated, and removal only happens once stated conditions are
  met.

## Where the "current state" section is wrong

1. **The adaptive ledger does not feed eval, export or metrics.** Only `status` reads
   `requests.jsonl` or `adaptive-records/`. Eval, export and metrics run on `responses.jsonl`, which
   in an adaptive run holds every candidate attempt, including cascade fallbacks that were never
   delivered. There is no request-level analysis at all, so this is missing work, not just a risk.
2. **Several "new" contracts already exist.** `adaptive/types.py` defines `Candidate`,
   `RequestFeatures`, `Observation`, `Decision`, `Provenance` and `PolicyState`.
   `adaptive/sidecars.py` has `DecisionRecord`. `dataset/capabilities.py` has
   `DatasetCapabilityReport` with mandatory and optional capabilities. The plan proposes types with
   the same names and does not say whether to reuse, extend or replace them.
3. **An online quality sensor already exists.** The `minimum_response_length` sensor
   (`src/ctxbench/adaptive/v1.py:527-546`) already has acceptance and fallback behaviour and records
   its own cost. It should become the first `OnlineQualityAssessor`; the plan treats this as
   greenfield.
4. **There are two execute paths.** The legacy non-v4 path
   (`src/ctxbench/commands/execute.py:117-197`) has no durable records, and the plan does not
   mention it. WP1 has to decide whether to keep or retire it.
5. **The argument order is reversed.** The plan's protocol has
   `request_features(task_id, instance_id)`, but the code uses `(instance_id, task_id)`
   (`src/ctxbench/dataset/package.py:80`).

## Design gaps

Ordered from most to least important.

### A. Cascade and fallback cannot be represented

Today a cascade makes several attempts per request, applies an acceptance rule, and updates
Knowledge between attempts. The cascade order also overrides `choose_candidate` inside the loop
(`v1.py:460-465`, `v1.py:487-488`), so policy logic is split between the controller and the loop.
The plan's `Decision` has one selected candidate, and its state diagram goes decision → one attempt
→ feedback.

**Needed:** either one decision per attempt (escalation) or a decision that carries an ordered plan,
with acceptance placed in Analyze.

### B. Injected disturbances are missing entirely

Phases inject `toolDelayMs`, `toolFailureRate` and `failureSeed` through
`local_mcp_runtime_decorator`, and this is what makes adaptation observable at all. Open points:

- The disturbance only reaches `local_mcp`. `inline` and `local_function` are untouched, so part of
  any measured "adaptation" comes from which strategy gets disturbed. This is a research-validity
  problem.
- It is unclear whether the injected delay counts as measured latency, and what provenance it gets.
- It is unclear whether the disturbance belongs in the definition, the execution fingerprint, or
  `ExecutionContext`.
- There are two implementations: `calibration.DelayedRuntime` and `v1.DelayedToolRuntime`.

### C. Admission control is not placed

`TokenQuota` sleeps in real time over rolling timestamp windows, inside Execute rather than the
controller, so replay is not deterministic.

**Needed:** put admission in Plan (wait, admit or reject) and report quota wait time as its own
metric.

### D. Attempt identity blocks realistic workloads

Request × candidate is expanded into `TrialSpec`s up front, and attempts are tied to the trial.
That is why a workload cannot repeat a task/instance pair (`v1.py:93`), which contradicts the plan's
own "repeat settings". `execute_trial(trial)` inherits the same limit. This changes the
`execution-records` layout, so it must be decided before WP1. Also, the glossary defines a Trial as
benchmark-only, yet adaptive uses trials too.

### E. Calibration is an unnamed contract between the two workflows

`knowledge.json` is built from a benchmark run's artifacts (`v1.py:131-202`).

- It needs to be a named, versioned contract.
- `_load_calibration` *rejects* calibration runs that have evaluation enabled (`v1.py:135`). The
  plan's rule "offline evaluation must not feed Knowledge" mixes up two cases:
  - evaluating the same episode's responses is leakage and should be forbidden;
  - evaluating a separate, disjoint calibration run is a legitimate quality prior, and quality SLOs
    essentially need it to choose a route before executing.

### F. An oracle used in the loop is an idealised sensor

Using RepoQA's oracle or the Lattes judge as an online assessor relies on ground truth that a real
deployment would not have. `QualityObservation` should record the sensor class (oracle, judge or
proxy), and claims should be scoped to match. Otherwise the results overstate what could be
deployed.

### G. Knowledge is tied to one dataset feature

Knowledge is partitioned by a hard-coded `sizeBin ∈ {small, medium, large}` (`v1.py:96-98`,
`v1.py:177-179`), which contradicts the dataset-agnostic goal. The definition needs a declared
partition key or feature schema. The update rule is a cumulative running mean that never forgets
older data; with phased disturbances, that is a research choice and should be explicit and
versioned as part of the policy.

### H. Which packages may import which is undecided

`TrialSpec`, `execution_records`, `runtime_adapter` and `fingerprint` all live in `benchmark/`, so
adaptive imports `benchmark/` wherever the service ends up. WP1 even leaves the service location
open (`services/` or `benchmark/`). Without a matrix of allowed imports (benchmark domain models
allowed, benchmark workflow modules not), the planned import-boundary tests cannot be written.

Separately, `adaptive/recovery.py` (sealed writes, episode locks) is already a second persistence
mechanism, despite the plan's "no second artifact store".

### I. The execution service is underspecified, which affects measurements too

- A new `Engine` is created per `_execute_durable` call, which means per adaptive attempt. MCP
  startup cost lands in the latency the controller observes, so this skews the measurements, not
  just performance.
- `rebuild_responses` runs after every attempt, so `responses.jsonl` is rewritten each time (O(N²)).
- The service needs to define lock scope, a runtime interceptor hook, per-call force/retry, and the
  `ExecutionContext` contents.

### J. Existing defects to record before fixtures freeze them

- Resuming a request in the `started` state recomputes the decision and overwrites the record with
  empty attempts (`v1.py:467-482`). The plan requires replay instead.
- With `--force`, `records` holds every record on disk. History, spent tokens and `TokenQuota`
  (`v1.py:427-454`) then include *later* requests' attempts, so future data leaks into decisions.

WP1's gate "outputs semantically unchanged" must not lock this behaviour in.

## Gaps in the work-package plan

- **Tests vs. the WP1 gate:** `tests/test_adaptive_v1_fallback.py` monkeypatches
  `execute._execute_durable` (lines 29, 104, 112). That conflicts with WP1's "no import of
  `_execute_durable`". Move these tests onto a service seam in WP0, before the refactor.
- **Ordering:** WP4 needs new definition fields (quality SLOs, assessor, partition key), but
  definitions and schema versioning only arrive in WP5. Pull the schema decision forward. Under
  `CLAUDE.md`, schema changes also need explicit approval.
- **Request-level analysis:** no work package exports or computes metrics from `requests.jsonl`,
  which any adaptive result claim needs.
- **Concrete assessors:** WP2 names no actual assessor or cost per dataset (fake, RepoQA, Lattes),
  yet WP4's gate depends on one.
- **Third controller risk:** a policy behaviour matrix is deferred to WP6. Meanwhile WP4 builds a
  new controller next to `study_policy.Controller` (520 lines) and `policy.RouterPolicy`. Do the
  matrix in WP0.
- **Smaller omissions:** `status` is not listed among the migration targets, and the plan should
  state explicitly that execution is serial (no concurrency).

## Readiness

Not ready. To unblock WP1, add a WP0 addendum that:

- decides A, B, D, H and I;
- records the defects in J;
- moves the fallback tests onto a service seam.

WP2 and WP4 additionally need E, F and G settled, plus the schema decision moved before WP4.
