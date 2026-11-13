
# LLMContextBench — Use Cases for Self-Adaptive Context Provisioning Studies

**Document type:** Functional use cases and acceptance criteria  
**Target audience:** LLMContextBench maintainers, implementing agents, and researchers  
**Reference:** https://github.com/michelav/llmcontextbench  
**Scope:** Requirements for conducting workload-driven experiments involving context provisioning, resource constraints, latency, and answer quality.

## 1. Objective

LLMContextBench shall enable researchers to investigate whether dynamically selecting context provisioning configurations improves the satisfaction of service-level objectives (SLOs) under varying workloads.

The framework should support experimental scenarios in which architectural alternatives exhibit different characteristics regarding token consumption, execution latency, and response quality.

A typical study involves an LLM-based service receiving requests over time. Each request requires access to external context, such as technical documentation or source code repositories.

The application operates under resource constraints and quality requirements. An adaptation policy decides which provisioning configuration should be used for each request.

Researchers should be able to compare adaptive policies against static configurations under reproducible experimental conditions.

The requirements below describe the capabilities researchers must have available. They do not prescribe a specific implementation architecture or require LLMContextBench to implement a complete self-adaptive application.

---

## UC-01 — Configure a Reproducible Multi-Configuration Experiment


**User story**

As a researcher, I want to define multiple context provisioning configurations for the same dataset, tasks, and LLM so that I can compare their effects on quality, latency, and resource consumption.

**Example**

I want to evaluate the following configurations for a code review dataset:

- An inline configuration that provides the available source context directly.
- A local function configuration that exposes repository inspection operations.
- A local MCP configuration exposing equivalent operations.
- A remote MCP configuration.

I also want to compare configurations exposing different subsets of repository information.

**Required capabilities**

- Define and identify multiple provisioning configurations.
- Specify their strategy, representation, and context-access surface.
- Define which operations are exposed by operation-mediated configurations.
- Validate compatibility with the dataset and model.
- Execute identical tasks using different configurations.
- Preserve the effective configuration definition with each trial.

**Acceptance criteria**

- The researcher can select configurations by stable identifiers.
- The same task can be executed using each selected configuration.
- Configuration definitions are preserved in experiment artifacts.
- Two configurations with different definitions remain distinguishable in analysis.
- Experiments remain reproducible even if configuration files are modified afterward.

**Current project assessment**

The repository already supports named configurations, representations, full-context surfaces, and operation surfaces.

An extension would only be needed for additional forms of context selection, such as dynamically selected inline subsets, if required by the experimental scenarios.

---

## UC-02 — Characterize the Performance and Quality of Provisioning Configurations


**User story**

As a researcher, I want to measure the behavior of each provisioning configuration before introducing adaptation so that I can identify meaningful architectural trade-offs.

**Example**

For each configuration, I want to know:

- How many tokens are consumed per task?
- What is the execution latency distribution?
- What is the response quality?
- How many model and tool calls are required?
- Does performance vary according to task complexity?

**Required capabilities**

- Execute representative tasks under each configuration.
- Repeat executions to account for variability.
- Collect token usage, including available cache-related information.
- Measure execution latency and tool overhead.
- Evaluate response quality.
- Aggregate results by configuration, dataset, and task category.
- Export measurements for independent analysis.

**Acceptance criteria**

- The researcher can compare quality, latency, and token usage across configurations.
- Results include distributions rather than only averages.
- Individual execution measurements remain available.
- The researcher can identify configurations that are dominated by alternatives.
- Performance characterization can be performed independently of adaptive execution.

**Current project assessment**

The existing `plan`, `execute`, `eval`, and `metrics` commands provide most of this functionality.

The adaptive study should reuse these measurements whenever possible.

---

## UC-03 — Define a Workload Using Benchmark Tasks


**User story**

As a researcher, I want to define a workload containing multiple requests derived from benchmark tasks so that I can evaluate how context provisioning configurations behave under realistic service demand.

**Example**

I want to simulate a technical support service receiving 500 requests during a five-hour operating window.

The requests should be derived from a technical support dataset, while their arrival times follow a configurable temporal distribution.

Some requests should refer to the same documents, allowing context reuse.

**Required capabilities**

- Define a workload as a sequence of request arrivals.
- Associate each request with an existing dataset task and instance.
- Specify arrival times or interarrival intervals.
- Define workload duration and request arrival rates.
- Support variable demand, including bursts and low-activity periods.
- Support concurrent requests.
- Preserve session or context reuse relationships when available.
- Support deterministic workload generation using random seeds.
- Import traces from external sources.
- Allow explicit task repetition when the workload contains more requests than unique benchmark tasks.

**Acceptance criteria**

- The researcher can generate or import a workload without executing the LLM.
- Each request references a valid benchmark task and instance.
- The workload can be reproduced using the same definition and seed.
- Different provisioning policies can execute exactly the same request sequence.
- Workload arrival rates do not depend on how quickly previous requests finish.
- Repeated tasks, reused documents, and synthetic timestamps are identifiable.

**Important requirement**

The framework must distinguish real workload traces from synthetic or trace-driven workloads.

Associating benchmark questions with timestamps from an independent production trace must not be presented as an original production workload.

---

## UC-04 — Define Resource Budgets and Service-Level Objectives


**User story**

As a researcher, I want to define resource constraints and SLOs so that I can evaluate whether a provisioning configuration or adaptation policy satisfies the operational requirements of an LLM-based service.

**Example**

I want to configure an application with the following illustrative objectives:

- P95 response latency below 8 seconds.
- At least 85% correct responses.
- No more than 2 million accounted tokens during a five-hour window.
- At least 98% of requests completed successfully.

**Required capabilities**

- Define SLOs independently of provisioning configurations.
- Define latency thresholds and measurement windows.
- Define quality thresholds and evaluation criteria.
- Define resource budgets and renewal windows.
- Support multiple simultaneous budget constraints.
- Distinguish throughput, availability, and successful completion.
- Define how failures, timeouts, and rejected requests affect SLO calculations.
- Validate the configuration before execution.

**Acceptance criteria**

- Multiple objectives can be configured within one experiment.
- Budget renewal behavior is deterministic and inspectable.
- SLO definitions remain unchanged when comparing policies.
- Each SLO has an explicit measurement unit, aggregation rule, and evaluation window.
- The researcher can determine whether each SLO was satisfied.

**Important requirement**

Provider rate limits, token budgets, monetary costs, and subscription usage quotas must be represented as distinct resource constraints.

The framework must not assume that the reported number of tokens directly represents an opaque provider subscription quota.

---

## UC-05 — Execute a Workload Using a Fixed Provisioning Configuration


**User story**

As a researcher, I want to execute the same workload using a fixed provisioning configuration so that I can establish a baseline against which adaptive policies will be compared.

**Example**

I want to execute a five-hour workload three times:

- Always using Inline.
- Always using Local Functions.
- Always using Remote MCP.

**Required capabilities**

- Execute timestamped requests using a selected configuration.
- Support request concurrency and queueing.
- Apply configured resource constraints.
- Collect per-request latency and resource usage.
- Record rejected, failed, and timed-out requests.
- Preserve workload-level results.
- Support repeated experimental executions.

**Acceptance criteria**

- Each baseline receives the same request arrivals and tasks.
- Request arrival time, execution start time, and completion time are recorded separately.
- Queueing delays are included in end-to-end service latency.
- Resource limits affect execution according to their declared semantics.
- The researcher can determine when a static configuration exhausted its available budget.
- Baseline outputs can be evaluated using the existing quality evaluation mechanisms.

**Important requirement**

The current trial execution lifecycle should be reused. Workload execution should not require implementing an independent model inference engine.

---

## UC-06 — Execute a Workload with Runtime Configuration Selection


**User story**

As a researcher, I want an adaptation policy to select the context provisioning configuration for incoming requests so that I can investigate whether runtime adaptation improves SLO satisfaction.

**Example**

A controller initially selects Inline.

As workload demand increases, the controller observes that the remaining token budget may be insufficient to sustain the service.

It selects Local Functions for subsequent requests.

When the budget is renewed, the controller may select Inline again.

**Required capabilities**

- Integrate an adaptation policy or external controller.
- Expose the available provisioning configurations.
- Provide runtime observations to the controller.
- Request a configuration decision for each incoming request or decision interval.
- Execute requests using the selected configuration.
- Record configuration selections and changes.
- Support stateful controllers.
- Handle unavailable configurations or invalid decisions.
- Support a configured fallback behavior when no configuration is feasible.

**Acceptance criteria**

- The controller can select different configurations during the same workload.
- The selected configuration is recorded for every request.
- The experiment records the operational state available when the decision was made.
- The controller cannot access future workload events or reference answers unless a specific offline oracle experiment explicitly permits it.
- A controller can be replaced without modifying the provisioning strategies.
- Static policies can use the same execution interface.

**Important requirement**

LLMContextBench should not require a particular adaptation algorithm.

Threshold-based, predictive, rule-based, and MAPE-K controllers should be able to use the same experimental capabilities.

---

## UC-07 — Monitor Resource Consumption and Operational State During Execution


**User story**

As a researcher, I want to monitor resource consumption and service performance while the workload is executing so that adaptation policies can make decisions using current operational information.

**Example**

At a given point in the workload, the controller needs to know:

- Remaining token budget.
- Time until budget renewal.
- Recent resource consumption rate.
- Recent request arrival rate.
- Current latency observations.
- Number of active or queued requests.
- Available configuration performance estimates.

**Required capabilities**

- Maintain shared resource accounting across requests.
- Update resource consumption using execution measurements.
- Support rolling observation windows.
- Expose current budget state.
- Calculate recent latency and throughput indicators.
- Make observable metrics available to external controllers.
- Distinguish measured, reported, derived, estimated, and unavailable values.
- Preserve monitoring observations for later inspection.

**Acceptance criteria**

- Resource consumption is accumulated correctly across requests.
- Multiple requests cannot overspend a shared budget due to accounting races.
- Budget renewal occurs according to configured rules.
- The controller receives observations corresponding to the current workload state.
- Unavailable measurements are not silently replaced by zero.
- Monitoring data can be correlated with subsequent adaptation decisions.

**Important requirement**

The existing TPM/RPM rate-control functionality should not be treated as equivalent to long-window resource budget accounting.

---

## UC-08 — Evaluate Response Quality and SLO Compliance


**User story**

As a researcher, I want to evaluate the actual quality and operational outcomes of an executed workload so that I can determine whether the application satisfied its SLOs.

**Example**

An adaptive policy may reduce token consumption and avoid quota exhaustion but produce lower-quality responses.

I want to determine whether the resource savings justify the quality degradation and whether the configured SLOs were violated.

**Required capabilities**

- Evaluate outputs using the dataset's configured evaluation method.
- Support domain-specific evaluation methods.
- Associate evaluation outcomes with individual workload requests.
- Aggregate quality across the workload and relevant time windows.
- Calculate latency SLO violations.
- Calculate budget exhaustion events.
- Calculate request success and availability indicators.
- Distinguish violations caused by service execution from those caused by insufficient answer quality.
- Preserve separate execution and evaluation resource consumption.

**Acceptance criteria**

- The researcher can calculate quality, latency, and resource outcomes for the complete workload.
- Results distinguish service success from answer correctness.
- The evaluation includes a declared policy for unanswered requests.
- Quality results can be grouped by configuration, task category, and workload period.
- The framework identifies which SLOs were violated and when.
- Post-execution quality evaluation does not retroactively alter the observations available to the controller.

**Important requirement**

Quality ground truth must remain separate from runtime quality estimates.

If an experiment uses quality feedback during adaptation, its availability and delay must be explicitly modeled.

---

## UC-09 — Compare Static and Adaptive Policies Under Identical Conditions


**User story**

As a researcher, I want to compare static and adaptive policies under identical workload conditions so that I can determine whether adaptation provides measurable benefits.

**Example**

I want to compare:

- Static Inline.
- Static Local Functions.
- Static Remote MCP.
- Reactive quota-aware policy.
- Predictive quota-aware policy.
- Multi-objective SLO-aware policy.

**Required capabilities**

- Define and identify multiple candidate policies.
- Execute the same workload for each policy.
- Preserve equivalent resource constraints and SLOs.
- Compare completed requests, quality, latency, and token usage.
- Compare premature budget exhaustion and SLO violations.
- Measure configuration switches.
- Aggregate results across experimental repetitions.
- Export data for statistical analysis.

**Acceptance criteria**

- Policies are evaluated using equivalent inputs and conditions.
- Results identify differences in quality, resource efficiency, and SLO compliance.
- The framework reports whether adaptation provides benefits over the best applicable static baselines.
- Policy results can be analyzed by workload scenario.
- Repeated executions can be compared statistically.
- Results distinguish measured executions from simulation-based estimates.

**Expected research outcome**

The researcher can determine whether adaptive context provisioning improves multi-objective SLO satisfaction rather than simply reducing resource consumption.

---

## UC-10 — Inspect, Reproduce, and Diagnose Adaptive Experiments


**User story**

As a researcher, I want to inspect the sequence of requests, configuration decisions, resource measurements, and quality outcomes so that I can explain why an adaptation policy succeeded or failed.

**Example**

An adaptive controller unexpectedly violates the latency SLO after switching from Inline to Remote MCP.

I want to inspect the execution history to determine whether the violation resulted from additional model calls, tool latency, queueing, or inappropriate controller decisions.

**Required capabilities**

- Preserve workload definitions and input task references.
- Record request arrival, dispatch, and completion events.
- Record selected configurations.
- Record adaptation decisions and their associated observations.
- Preserve resource accounting and budget resets.
- Correlate request records with trial results and execution traces.
- Support inspection of individual requests and complete workloads.
- Export structured data for independent analysis.
- Preserve dataset versions, configuration definitions, policy parameters, and model settings.

**Acceptance criteria**

- Every adaptive request can be traced to its selected configuration.
- The researcher can reconstruct the sequence of adaptation decisions.
- SLO violations can be correlated with execution events.
- Experiments can be inspected without executing LLM calls again.
- Existing artifact provenance and metric semantics are preserved.

---

# 3. End-to-End Research Workflow

The use cases should enable the following researcher workflow:

**Step 1 — Select a dataset**

The researcher selects an existing domain-specific dataset package, such as technical support or code review.

**Step 2 — Define configurations**

The researcher selects the candidate context provisioning configurations.

**Step 3 — Characterize configurations**

LLMContextBench executes representative tasks and generates quality, latency, and resource consumption measurements.

**Step 4 — Define a workload**

The researcher selects or generates a temporal workload referencing tasks from the dataset.

**Step 5 — Define SLOs**

The researcher configures quality, latency, resource budget, and availability objectives.

**Step 6 — Run static baselines**

The workload is executed using each fixed configuration.

**Step 7 — Run adaptive policies**

The same workload is executed while an adaptation controller selects configurations at runtime.

**Step 8 — Evaluate quality and SLO compliance**

LLMContextBench evaluates the responses and calculates workload-level operational outcomes.

**Step 9 — Compare policies**

The researcher compares static and adaptive approaches and investigates conditions under which different policies are preferable.

**Step 10 — Inspect and reproduce results**

The framework exposes artifacts, metrics, and traces sufficient to explain and reproduce the study.

---

# 4. Minimum Acceptance Scenario

The adaptive study capabilities should be considered minimally functional when a researcher can complete the following experiment:

**Given:**

- One versioned dataset containing executable tasks and reference evaluation data.
- Two named provisioning configurations.
- One fixed LLM.
- A workload containing timestamped requests.
- A shared token budget with a renewal window.
- A latency SLO.
- A response quality objective.
- One static policy.
- One adaptive policy.

**When:**

The researcher executes the workload using each policy and evaluates the resulting responses.

**Then:**

LLMContextBench must provide:

1. The configuration selected for every request.
2. Per-request and aggregate token consumption.
3. End-to-end latency measurements.
4. Budget consumption and exhaustion events.
5. Quality evaluation results.
6. SLO compliance results.
7. A comparison between static and adaptive execution.
8. Sufficient artifacts to reproduce and inspect the experiment.

The minimum experiment must demonstrate the ability to evaluate adaptation, not necessarily that the adaptive policy performs better.

---

# 5. Out of Scope for the Initial Extension

The initial adaptive study functionality does not need to provide:

- A built-in machine learning model for predicting optimal configurations.
- A complete MAPE-K framework.
- A production-grade LLM serving platform.
- Automatic discovery of optimal SLO thresholds.
- Automatic dataset generation.
- Real-time human evaluation of every response.
- A graphical monitoring dashboard.
- Automatic switching between different answering models.

These capabilities may be introduced later, but they are not necessary for evaluating whether architectural adaptation improves SLO satisfaction.

The primary responsibility of LLMContextBench is to **provide controlled experimental conditions, execute configurable provisioning alternatives, capture observations, and evaluate adaptive behavior**.

