# LLMContextBench Evolution Plan

## Purpose

This document guides the staged evolution of **LLMContextBench** from its current trial-centric benchmark architecture toward a reusable context-provisioning runtime and, later, an adaptive runtime based on feedback and policy-driven decisions.

The plan intentionally preserves the current public terminology for now, including:

- `ProvisioningConfiguration`
- `Surface`
- `strategy`
- `representation`
- `TrialSpec`

The immediate goal is **architectural separation**, not naming migration.

---

## Target Architecture

```text
                       Applications
                            │
                            ▼
                      RuntimeRequest
                            │
                            ▼
                 ProvisioningController
                 ┌──────────┴──────────┐
                 │                     │
          EligibilityEvaluator   ProvisioningPolicy
                 │                     │
                 └──────────┬──────────┘
                            ▼
                  ProvisioningDecision
                            │
                            ▼
                  ProvisioningRuntime
                            │
                            ▼
                         Engine
                            │
                            ▼
                        Strategy
                            │
                            ▼
                     Model / Tools / MCP
                            │
                            ▼
                     ExecutionResult
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
        Runtime telemetry              Validator
              │                            │
              └─────────────┬──────────────┘
                            ▼
                   OperationalState


                  LLMContextBench
                     Benchmark
                         │
                      TrialSpec
                         │
                         ▼
                TrialRuntimeAdapter
                         │
                         └──────────────► same runtime
```

The **benchmark** remains responsible for:

- experiment planning;
- factor expansion;
- `TrialSpec`;
- artifacts;
- evaluation;
- metrics;
- reports;
- scientific reproducibility.

The **runtime** becomes responsible for:

- executing one provisioning request;
- resolving context and tool capabilities;
- executing a selected `ProvisioningConfiguration`;
- model/tool interaction;
- runtime telemetry;
- producing an execution result.

The **adaptive layer** is added only after the runtime boundary is stable.

---

## Architectural Invariants

The coding agent must treat the following as non-negotiable constraints.

1. **Do not rename current public concepts in this work.**  
   Keep `strategy`, `Surface`, `ProvisioningConfiguration`, `representation`, and related names unchanged.

2. **Do not change persisted artifact schemas during runtime extraction.**  
   Preserve `trials.jsonl`, `responses.jsonl`, `manifest.json`, trial IDs, provisioning artifact versions, and deterministic identities unless a later dedicated specification explicitly changes them.

3. **The runtime must not depend on benchmark concepts.**

   ```text
   runtime ─X─► TrialSpec
   runtime ─X─► Experiment
   runtime ─X─► manifest.json
   runtime ─X─► benchmark artifact paths
   ```

4. **Dependency direction must be one-way.**

   Allowed:

   ```text
   benchmark → runtime → ai/core
   application → runtime → ai/core
   ```

   Forbidden:

   ```text
   runtime → benchmark
   core → benchmark
   ```

5. **Current benchmark behavior is the regression oracle.**

6. **Use provider-free and local tests for architectural refactoring.**  
   Do not introduce network-backed tests unless explicitly required.

7. **Do not combine runtime extraction with learned adaptation.**

8. **Keep each change narrow and independently verifiable.**

---

# Phase 0 — Architecture Baseline

## Objective

Document the exact current execution path before changing it.

The agent should inspect and map:

```text
TrialSpec
  ↓
benchmark.executor.execute_runspec()
  ↓
DatasetPackage / DatasetAdapter
  ↓
AIRequest
  ↓
Engine
  ↓
StrategyAdapter
  ↓
ModelAdapter / ToolRuntime
  ↓
TrialResult
```

## Required Analysis

For every `TrialSpec` field used during execution, classify it as:

- `RUNTIME`
- `BENCHMARK`
- `BOTH`

Example:

```text
taskStatement       RUNTIME
provider            RUNTIME
modelName           RUNTIME
strategy            RUNTIME
representation      RUNTIME
surfaceSpec         RUNTIME

trialId             BENCHMARK
experimentId        BENCHMARK
repeatIndex         BENCHMARK
outputRoot          BENCHMARK
evaluationEnabled   BENCHMARK
```

## Deliverable

Create an architecture note such as:

```text
docs/architecture/runtime-extraction.md
```

It should document:

- current execution dependencies;
- runtime-required fields;
- benchmark-only fields;
- strategy-specific logic currently inside `execute_runspec()`;
- extraction seams;
- existing test coverage;
- compatibility risks.

## Acceptance Criteria

- No runtime behavior changes.
- No artifact changes.
- No naming changes.
- Dependency map reviewed before implementation begins.

---

# Phase 1 — Introduce Runtime Contracts

## Objective

Introduce the minimal trial-independent runtime API.

## Suggested Package

```text
src/ctxbench/runtime/
    __init__.py
    models.py
    runtime.py
```

Avoid over-engineering.

## RuntimeRequest

Introduce a model conceptually similar to:

```python
class RuntimeRequest(BaseModel):
    task: str
    instance_id: str
    provider: str
    model_name: str
    configuration: ProvisioningConfiguration
    surface_spec: dict[str, Any]
    params: dict[str, Any]
    metadata: dict[str, Any] = {}
```

The exact shape may differ after repository inspection.

It must not contain benchmark lifecycle concepts such as:

- `trialId`;
- `experimentId`;
- `repeatIndex`;
- evaluation settings;
- output roots;
- artifact configuration.

## ExecutionResult

Introduce a trial-independent result conceptually similar to:

```python
class ExecutionResult(BaseModel):
    response: str
    status: str
    error: str | None
    usage: dict[str, Any]
    metrics: dict[str, Any]
    trace: dict[str, Any]
    metadata: dict[str, Any]
```

It must not depend on benchmark artifact semantics.

## ProvisioningRuntime

Introduce:

```python
class ProvisioningRuntime:

    def execute(
        self,
        request: RuntimeRequest,
    ) -> ExecutionResult:
        ...
```

## Acceptance Criteria

- `RuntimeRequest` can be instantiated without `TrialSpec`.
- Runtime modules do not import benchmark models.
- No existing benchmark code must use the new runtime yet.
- Existing tests remain green.

---

# Phase 2 — Introduce the Benchmark Compatibility Adapter

## Objective

Create a clean boundary between benchmark artifacts and runtime execution.

## Suggested Module

```text
src/ctxbench/benchmark/runtime_adapter.py
```

## TrialRuntimeAdapter

Introduce something conceptually similar to:

```python
class TrialRuntimeAdapter:

    def to_runtime_request(
        self,
        trial: TrialSpec,
    ) -> RuntimeRequest:
        ...

    def to_trial_result(
        self,
        trial: TrialSpec,
        execution: ExecutionResult,
    ) -> TrialResult:
        ...
```

## Architectural Role

```text
TrialSpec
    │
    ▼
TrialRuntimeAdapter
    │
    ▼
RuntimeRequest
```

and:

```text
ExecutionResult
    │
    ▼
TrialRuntimeAdapter
    │
    ▼
TrialResult
```

## Constraint

The adapter performs **translation only**.

It must not contain:

- strategy execution;
- tool loops;
- model invocation;
- policy decisions;
- runtime monitoring logic.

## Acceptance Criteria

- Translation is deterministic.
- Existing `TrialSpec` fields remain preserved where required.
- No runtime execution logic appears in the adapter.

---

# Phase 3 — Extract the `inline` Execution Path

## Objective

Create the first complete end-to-end execution through `ProvisioningRuntime`.

Current approximate path:

```text
execute_runspec
   ↓
adapter.get_context()
   ↓
construct AIRequest
   ↓
Engine.execute()
```

Target:

```text
TrialSpec
   ↓
TrialRuntimeAdapter
   ↓
RuntimeRequest
   ↓
ProvisioningRuntime.execute()
   ↓
Engine
   ↓
ExecutionResult
   ↓
TrialRuntimeAdapter
   ↓
TrialResult
```

## Required Tests

Compare legacy and new behavior for provider-free fixtures across:

- response;
- status;
- errors;
- usage;
- metrics;
- trace;
- provisioning fields;
- persisted `TrialResult`.

## Acceptance Criteria

- `inline` execution uses the new runtime.
- Benchmark output remains equivalent.
- No artifact schema changes.
- No trial identity changes.
- Full relevant regression tests pass.

---

# Phase 4 — Extract `local_function`

## Objective

Move local-function execution behind the same runtime boundary.

Move these responsibilities from benchmark executor to runtime:

- tool provider resolution;
- tool runtime construction;
- tool-loop preparation;
- `AIRequest` construction;
- engine invocation;
- cleanup.

## Target Runtime Support

```text
ProvisioningRuntime
    ├── inline
    └── local_function
```

## Acceptance Criteria

- Both paths execute through `ProvisioningRuntime.execute()`.
- Benchmark behavior remains equivalent.
- `execute_runspec()` contains less provisioning-specific logic.
- Provider-free equivalence tests pass.

---

# Phase 5 — Complete Strategy Parity

## Objective

Move the remaining strategies through the same runtime boundary.

Add support for:

```text
local_mcp
remote_mcp
```

Target:

```text
ProvisioningRuntime
    ├── inline
    ├── local_function
    ├── local_mcp
    └── remote_mcp
```

## Desired End State

`execute_runspec()` should become conceptually close to:

```python
def execute_runspec(trial, runtime):
    runtime_request = trial_adapter.to_runtime_request(trial)
    execution = runtime.execute(runtime_request)
    return trial_adapter.to_trial_result(
        trial,
        execution,
    )
```

## Runtime-Modularization Completion Criterion

> An application can execute any supported provisioning configuration without constructing a `TrialSpec`.

At this point, runtime modularization can be considered complete.

---

# Phase 6 — Add Application-Facing Proof

## Objective

Demonstrate that the runtime is usable independently from the benchmark.

## Suggested Example

```text
examples/runtime/basic.py
```

Example shape:

```python
runtime = ProvisioningRuntime(...)

request = RuntimeRequest(
    task="...",
    ...
)

result = runtime.execute(request)

print(result.response)
```

## Constraints

The example must not depend on:

- `Experiment`;
- `TrialSpec`;
- `manifest.json`;
- planning commands;
- execution commands;
- benchmark artifact directories.

## Acceptance Criteria

- Runtime works independently of benchmark planning.
- Example uses a mock/provider-free model.
- Runtime API is documented.

---

# Phase 7 — Runtime Telemetry

## Objective

Move runtime observations into a reusable telemetry contract.

## Initial Contracts

Introduce:

```text
RuntimeEvent
TelemetrySink
```

Example events:

```text
execution.started
strategy.started
model.called
tool.called
strategy.completed
execution.completed
execution.failed
```

Suggested protocol:

```python
class TelemetrySink(Protocol):

    def emit(
        self,
        event: RuntimeEvent,
    ) -> None:
        ...
```

## Initial Implementations

```text
NullTelemetrySink
InMemoryTelemetrySink
BenchmarkTelemetrySink
```

## Constraint

Do not add yet:

- OpenTelemetry;
- Prometheus;
- distributed tracing;
- external monitoring platforms.

## Acceptance Criteria

- Runtime emits normalized events.
- Existing benchmark trace behavior remains available.
- Benchmark traces can be produced through a telemetry adapter/sink.

---

# Phase 8 — Runtime Observation and Operational State

## Objective

Introduce minimal state required for adaptation.

## Suggested Modules

```text
runtime/
    observations.py
    state.py
```

## RuntimeObservation

Initial fields:

```text
configuration
latency
success/error
tokens
timestamp
```

## OperationalState

Start simple:

```python
class ConfigurationState:
    recent_latency_ms: deque
    consecutive_errors: int
    status: Literal[
        "healthy",
        "degraded",
    ]
```

## Constraint

Use an in-memory implementation initially.

Do not introduce:

- databases;
- distributed coordination;
- persistent runtime state.

---

# Phase 9 — Minimal Operational Analyzer

## Objective

Derive operational health from runtime observations.

## Initial Rules

Example degradation rule:

```text
healthy
   ↓

p95 > threshold
for N observations

   ↓
degraded
```

Example recovery rule:

```text
degraded
   ↓

p95 < recovery threshold
for M observations

   ↓
healthy
```

Use different degradation and recovery thresholds to provide basic hysteresis.

## MAPE-K Mapping

At this stage:

```text
Monitor   = RuntimeTelemetry
Analyze   = rolling latency/error rules
Knowledge = OperationalState
```

No anomaly-detection model is required.

---

# Phase 10 — Add the Provisioning Controller

## Objective

Introduce policy-driven provisioning selection.

## Suggested Modules

```text
runtime/
    controller.py
    eligibility.py

runtime/policies/
    base.py
    fixed.py
    rules.py
```

## ProvisioningDecision

Conceptually:

```python
class ProvisioningDecision(BaseModel):
    configuration_id: str
    policy_id: str
    reason: str | None
    candidates: list[str]
    metadata: dict[str, Any]
```

## EligibilityEvaluator

It answers:

> Can this configuration currently be used?

Examples:

```text
remote_mcp unavailable
→ ineligible

privacy forbids remote access
→ ineligible

configuration health unavailable
→ ineligible
```

It does **not** answer:

> Which configuration is best?

## ProvisioningPolicy

Initial protocol:

```python
class ProvisioningPolicy(Protocol):

    def select(
        self,
        context,
        candidates,
    ) -> ProvisioningDecision:
        ...
```

---

# Phase 11 — Implement FixedPolicy

## Objective

Provide a baseline that reproduces existing fixed execution.

Example:

```python
FixedPolicy("inline-json")
```

The invariant is:

```text
FixedPolicy
+
ProvisioningRuntime
≈
current LLMContextBench execution
```

## Acceptance Criteria

- Fixed-policy execution matches manually selected configuration behavior.
- Existing benchmark experiments can use the same runtime without adaptive effects.
- No hidden configuration switching occurs.

---

# Phase 12 — Implement RulePolicy

## Objective

Introduce the first adaptive policy.

Keep it deterministic.

Example:

```text
IF preferred configuration is healthy
    use preferred configuration

ELSE
    use fallback configuration
```

or:

```text
IF local_function.p95 <= 2000 ms
    local_function

ELSE
    inline
```

## Explicitly Excluded

Do not add:

- machine learning;
- optimization solvers;
- LLM routers;
- contextual bandits;
- online learning.

---

# Phase 13 — Inter-Request Adaptation Experiment

## Objective

Produce the primary short-term adaptive-system result.

## Compare

```text
Fixed Inline
Fixed Local Function
Adaptive Rule Policy
```

## Experimental Phases

```text
Healthy
    ↓
Degraded
    ↓
Recovered
```

Example fault injection:

```text
local_function artificial latency

healthy:
    +0 ms

degraded:
    +3000 ms

recovery:
    +0 ms
```

## Measures

Collect:

- p50 latency;
- p95 latency;
- success rate;
- SLA violation rate;
- configuration switches;
- adaptation delay;
- runtime overhead;
- recovery delay.

## Candidate Research Question

> Can runtime adaptation preserve operational objectives under changing provisioning conditions better than fixed provisioning configurations?

---

# Phase 14 — Minimal Intra-Request Fallback

## Objective

Add a single, simple fallback path.

This is a stretch goal for the initial two-week timebox.

Introduce:

```text
ExecutionSession
```

Initial behavior:

```text
try configuration A

IF timeout/error
    execute configuration B
```

Example:

```text
local_function
     ↓
 timeout
     ↓
inline
```

Record:

- initial configuration;
- fallback configuration;
- fallback reason;
- first-attempt latency;
- total latency;
- total tokens;
- final result.

Do not implement arbitrary fallback graphs yet.

---

# Two-Week Timebox

## Minimum Desired Result

By the end of the initial 10-working-day sprint:

```text
✓ trial-independent runtime
✓ inline runtime
✓ local_function runtime
✓ benchmark compatibility
✓ telemetry
✓ rolling operational state
✓ simple health analysis
✓ FixedPolicy
✓ RulePolicy
✓ inter-request adaptation
✓ controlled degradation experiment
```

## Stretch Goal

```text
+ simple intra-request fallback
```

## Explicitly Not Required

```text
local_mcp adaptation
remote_mcp adaptation
quality model
shadow execution
learned policy
online learning
contextual bandit
distributed state
OpenTelemetry
```

## Stop Rule

If the inter-request adaptation experiment is working reliably, do not destabilize it merely to add stretch features.

---

# Post-Timebox Roadmap

After the vertical prototype is stable:

```text
Phase A
complete runtime parity:
local_mcp + remote_mcp

Phase B
quality signals:
validators + asynchronous outcomes

Phase C
execution adaptation:
fallback + escalation chains

Phase D
shadow execution

Phase E
offline policy evaluation

Phase F
learned selection

Phase G
online policy adaptation
```

---

# Coding-Agent Operating Procedure

For each implementation slice, the coding agent should:

1. Inspect the current implementation.
2. Describe the intended responsibility move before editing.
3. Identify architectural invariants.
4. Add or update tests first where practical.
5. Make the smallest sufficient code change.
6. Run focused tests.
7. Run the full relevant regression suite.
8. Document behavioral-equivalence evidence.
9. Stop before introducing the next architectural concern.

Each PR should answer:

```text
What responsibility moved?

From where?

To where?

Which dependency was removed?

Which behavior must remain identical?

Which tests demonstrate it?
```

---

# Recommended PR Sequence

```text
PR 1 — architecture audit and runtime contracts
PR 2 — inline runtime extraction
PR 3 — local_function runtime extraction
PR 4 — remaining strategy parity
PR 5 — application-facing example
PR 6 — runtime telemetry
PR 7 — operational state and health analysis
PR 8 — controller + FixedPolicy
PR 9 — RulePolicy + inter-request adaptation
PR 10 — optional intra-request fallback
```

---

# Definition of Success

The evolution is on the right path when:

1. the benchmark can execute through a shared runtime;
2. an application can use that runtime without benchmark artifacts;
3. fixed execution remains behaviorally equivalent;
4. telemetry can update operational state;
5. a simple rule policy can alter provisioning decisions based on observed runtime degradation;
6. the adaptive behavior can be measured experimentally against fixed baselines.

The long-term direction is:

```text
design
  ↓
benchmark
  ↓
deploy
  ↓
observe
  ↓
adapt
  ↓
re-evaluate
```

The benchmark provides controlled evidence, the runtime provides reusable execution mechanisms, and the adaptive layer converts observations and evidence into context-provisioning decisions.
