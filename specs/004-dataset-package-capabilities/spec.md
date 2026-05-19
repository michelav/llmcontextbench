# Feature Specification: Dataset Package Capabilities and Core/Adapter Boundary

**Feature Branch**: `004-dataset-package-capabilities`  
**Created**: 2026-05-19  
**Status**: Draft  
**Depends on**: Spec 003  
**Supersedes parts of**: Spec 005  

> **Note on Spec 005**: The superseding claim is limited to the role axis. Spec 004 encodes artifact role implicitly in method names (`get_context`, `get_evidence`, `get_oracle`) rather than as a parameter. Spec 005's full `(role, representation)` model is out of scope for v0.

## Overview

This specification defines the runtime boundary between the CTXBench benchmark core and dataset-specific adapters.

Spec 003 defines how external dataset packages are acquired, materialized, cached, inspected, and recorded for provenance. This specification defines how the benchmark runtime consumes a resolved dataset package.

The goal is to make CTXBench sufficiently domain-neutral to run experiments over datasets that live outside the benchmark tool repository, while keeping the current design simple enough for the next implementation step.

The benchmark core owns the generic lifecycle:

```text
plan → execute → eval → export → status
```

Dataset adapters own dataset-specific behavior. A dataset adapter implements the Dataset Package Capabilities v0 contract for one concrete dataset or domain.

This specification introduces:

- a core/adapter boundary;
- a minimal Dataset Package Capabilities v0 contract;
- a minimal Adapter Registry v0;
- explicit semantics for context, evidence, and oracle;
- the impact of the new boundary on experiment definitions;
- a temporary in-repository adapter path for Lattes.

This specification does not move the Lattes adapter implementation to `ctxbench/lattes`. Spec 004 introduces the boundary. Spec 006 moves Lattes across that boundary.

This specification also does not introduce a plugin framework, dynamic adapter discovery, Python package entry points, remote code loading, third-party adapter installation, multiple datasets per experiment, workspaces, sandboxes, executable oracle machinery, or dataset-contributed strategies.

## Relationship to Spec 005

Spec 004 encodes artifact role in method names rather than as a parameter, replacing Spec 005's `(role, representation)` handle with dedicated access methods. One gap remains: Spec 004 does not expose a way for adapters to declare the *normalized/derived* role required by Spec 006 FR-017. If that becomes necessary, a capabilities v1 amendment will add a `get_artifacts()` or role-declaration surface.

## Relationship to Spec 003

Spec 003 owns dataset acquisition and materialization. It answers:

- where a dataset package comes from;
- how it is fetched;
- how it is verified;
- where it is cached;
- how provenance is recorded.

Spec 004 owns runtime consumption of an already resolved dataset package. It answers:

- which adapter is responsible for a resolved dataset;
- which instances exist;
- which tasks exist;
- what context a model may receive;
- what evidence an evaluator may use;
- whether an oracle is available;
- whether tools are available.

Lifecycle commands MUST NOT acquire datasets implicitly. They consume a resolved dataset reference and interact with it only through the adapter boundary defined here.

## Core/Adapter Boundary

CTXBench separates the benchmark core from dataset adapters.

The **benchmark core** lives in `ctxbench-cli` and owns the generic lifecycle: planning, execution, evaluation, export, and status reporting. It also owns generic strategy orchestration, response collection, evaluation orchestration, artifact writing, and run status inspection.

The benchmark core MUST NOT know how a concrete dataset stores tasks, instances, context, evidence, oracle data, or tools. It MUST NOT depend on domain-specific filenames, directory layouts, parsers, tool implementations, or payload structures.

A **dataset adapter** implements the Dataset Package Capabilities v0 contract for one concrete dataset or domain. The adapter owns all dataset-specific behavior, including internal file layout, parsing, representation mapping, context selection, evidence selection, oracle availability, and domain-specific tools.

The core interacts with a dataset only through an adapter implementing the Dataset Package Capabilities v0 contract.

A dataset adapter MAY be implemented temporarily inside `ctxbench-cli` during Spec 004. This is allowed only as a migration step. The final relocation of the Lattes adapter implementation to `ctxbench/lattes` is deferred to Spec 006.

## Adapter Resolution and Registry v0

CTXBench MUST resolve a materialized dataset package to a dataset adapter before the benchmark lifecycle consumes the dataset.

The Adapter Registry v0 is an explicit, in-process registry that maps a dataset identity or dataset kind to an adapter factory implementing the Dataset Package Capabilities v0 contract.

The registry exists only to centralize adapter selection. It MUST NOT become a plugin framework in Spec 004.

The registry v0 MUST support, at minimum:

- the current Lattes dataset, through a temporary or external Lattes adapter;
- a future software-repository dataset adapter.

Generic lifecycle phases MUST NOT branch on concrete dataset identities. Dataset identity binding is allowed only inside the adapter registry or resolver.

The registry v0 MAY use explicit first-party registrations. Dynamic plugin discovery, Python package entry points, remote code loading, third-party adapter installation, and plugin marketplaces are out of scope.

## Dataset Package Capabilities v0

A resolved dataset adapter MUST expose the following mandatory capabilities:

```text
metadata
list_instances
list_tasks
get_task
get_context
get_evidence
```

A resolved dataset adapter MAY expose the following optional capabilities:

```text
get_oracle
get_tools
fixtures
```

The contract is intentionally minimal. It is designed to support the current Lattes dataset and to leave a narrow path for a second dataset domain without introducing a broad plugin architecture.

## Context, Evidence, and Oracle

The benchmark distinguishes three roles:

- **Context**: what the model under test may receive during execution.
- **Evidence**: what the evaluator or judge may receive during evaluation.
- **Oracle**: an expected or authoritative criterion used to evaluate a response, when available.

Evidence and oracle are distinct.

Evidence supports judgment. Oracle defines or constrains the expected outcome.

A dataset may provide evidence without an oracle. This is common for LLM-as-judge evaluation.

A dataset may provide an oracle without exposing it as model-facing context. This is common for exact-match, schema-based, heuristic, or executable evaluation. Executable oracle machinery is not introduced in v0.

If no oracle is available for a given task instance, the dataset adapter MUST return an explicit unavailable result. It MUST NOT fabricate an oracle.

## Experiment Definition Impact

The Dataset Package Capabilities v0 contract changes how experiment definitions refer to datasets.

Before this specification, an experiment could rely on a local dataset layout and on generic code that knew how to interpret Lattes-like files. After this specification, an experiment references a dataset package, and the benchmark resolves that dataset to an adapter through the Adapter Registry v0.

The experiment definition MUST remain domain-neutral. It MUST NOT name concrete adapter classes, Python modules, parser implementations, tool implementation names, Lattes-specific files, or dataset-specific readers.

The experiment definition identifies the dataset. The adapter registry resolves the dataset to an adapter. The adapter provides capabilities to the benchmark core.

In v0, the experiment definition MAY continue to use the existing `format` factor name for compatibility. However, within the Dataset Package Capabilities contract, `format` MUST be interpreted as the requested context representation provided by the dataset adapter.

A future cleanup MAY rename `format` to `representation` or `contextRepresentation`, but that rename is out of scope for this specification unless already required by accepted canonical terminology.

Experiment definition validation remains owned by the current Pydantic model layer in `ctxbench-cli`. This specification does not require generated JSON Schema artifacts. A future specification may decide to publish generated schemas for experiment definitions and produced artifacts.

## User Scenarios & Testing

### User Story 1 - Understand the Core/Adapter Boundary (Priority: P1)

A researcher or contributor reads the specification and can determine whether a benchmark concern belongs to the benchmark core, the adapter registry, or a dataset adapter.

**Why this priority**: Without a clear boundary, every new dataset encourages ad-hoc edits to generic lifecycle code and weakens the benchmark's ability to compare context provisioning strategies across domains.

**Independent Test**: A reviewer can classify any concern related to instances, tasks, context, evidence, oracle, or tools as core-owned, registry-owned, or adapter-owned without reading implementation code.

**Acceptance Scenarios**:

1. **Given** a contributor sees code that reads a concrete dataset file inside `plan`, **When** they apply this spec, **Then** the code is classified as a boundary violation.
2. **Given** a contributor sees adapter-specific parsing code inside a dataset adapter, **When** they apply this spec, **Then** the code is classified as adapter-owned behavior.
3. **Given** a contributor sees dataset identity mapped to an adapter factory inside the registry, **When** they apply this spec, **Then** the code is classified as registry-owned behavior.

---

### User Story 2 - Resolve a Dataset Through a Minimal Registry (Priority: P1)

A benchmark lifecycle phase receives a resolved dataset reference. Before it uses the dataset, CTXBench resolves the dataset to an adapter through the Adapter Registry v0.

**Why this priority**: The benchmark already needs to support Lattes and a future software-repository dataset. A single resolver prevents dataset-specific selection logic from leaking into lifecycle phases.

**Independent Test**: `plan`, `execute`, and `eval` consume a dataset through an adapter returned by the registry. No lifecycle phase branches on a concrete dataset identity.

**Acceptance Scenarios**:

1. **Given** a dataset reference with `dataset.id = "ctxbench/lattes"`, **When** the registry resolves it, **Then** it returns the Lattes adapter.
2. **Given** a future software-repository dataset identity, **When** the registry resolves it, **Then** no changes are required in `plan`, `execute`, `eval`, `export`, or `status`.
3. **Given** an unknown dataset identity, **When** the registry cannot resolve it, **Then** the benchmark fails with a deterministic adapter-unavailable error.

---

### User Story 3 - Execute Using Dataset-Provided Context (Priority: P1)

A strategy requests context for a trial. The dataset adapter resolves the request to the appropriate dataset-specific payload. The core and strategy do not name physical files.

**Why this priority**: This is the central requirement for comparing context provisioning strategies across domains without coupling strategies to Lattes files.

**Independent Test**: Execution requests context through the adapter capability, not through direct file access or Lattes-specific filename mapping.

**Acceptance Scenarios**:

1. **Given** an inline strategy requests `format = "html"` for Lattes, **When** the request reaches the Lattes adapter, **Then** the adapter decides how to resolve that representation internally.
2. **Given** an inline strategy requests `format = "json"` for Lattes, **When** the request reaches the Lattes adapter, **Then** the core does not know whether the underlying payload comes from a file, derived object, or another representation.
3. **Given** an unsupported context representation, **When** the adapter cannot resolve it, **Then** the run fails with an unsupported-representation error naming the requested representation.

---

### User Story 4 - Evaluate Using Evidence and Optional Oracle (Priority: P1)

The evaluation phase asks the dataset adapter for evidence and, when available, an oracle. The evaluator uses these payloads without knowing the dataset's internal layout.

**Why this priority**: Evaluation must remain reusable across datasets. Lattes may use evidence blocks and optional heuristic or reference oracles. A software repository dataset may later use annotations, expected files, or test-related metadata.

**Independent Test**: Evaluation proceeds when an oracle is unavailable and records oracle availability when it is used.

**Acceptance Scenarios**:

1. **Given** a Lattes task that is judge-only, **When** evaluation requests an oracle, **Then** the adapter returns an explicit unavailable result and evaluation proceeds using evidence.
2. **Given** a Lattes task with deterministic validation, **When** evaluation requests an oracle, **Then** the adapter returns an available oracle.
3. **Given** a dataset provides evidence and oracle from the same underlying payload, **When** evaluation requests them, **Then** evidence and oracle are still recorded as distinct roles.

---

### User Story 5 - Use Tools Only When the Dataset Provides Them (Priority: P2)

Tool-mediated strategies require domain-specific tools. If the adapter provides tools, the strategy uses them through the optional tool capability. If tools are not available, the run fails clearly.

**Why this priority**: Tool-based strategies are central to CTXBench, but tools are necessarily domain-specific. The core must not hard-code Lattes tool names or schemas.

**Independent Test**: Tool-mediated strategies obtain tools only through the adapter capability or fail with a capability-unavailable error.

**Acceptance Scenarios**:

1. **Given** a selected strategy requires tools and the adapter provides them, **When** execution starts, **Then** the strategy receives the adapter-provided tool provider.
2. **Given** a selected strategy requires tools and the adapter does not provide them, **When** execution starts, **Then** the run fails with a capability-unavailable error.
3. **Given** a generic strategy implementation, **When** reviewing imports, **Then** it does not import Lattes-specific tool implementations directly.

---

### User Story 6 - Preserve Experiment Definition Simplicity (Priority: P2)

A researcher writes an experiment definition that identifies the dataset and selects factors such as model, strategy, and format. The file does not contain adapter implementation names or dataset-specific filenames.

**Why this priority**: Dataset adapters should be selected by the registry, not by experiment authors naming implementation classes.

**Independent Test**: A valid experiment identifies a dataset with a generic dataset reference and continues to use `format` as the requested context representation in v0.

**Acceptance Scenarios**:

1. **Given** an experiment references `dataset.id = "ctxbench/lattes"`, **When** planning starts, **Then** the registry resolves the Lattes adapter.
2. **Given** an experiment uses `factors.format = ["html", "json"]`, **When** execution runs, **Then** those values are interpreted as context representation requests.
3. **Given** an experiment names a concrete adapter module or class, **When** validation runs, **Then** the experiment is rejected or classified as invalid for this spec's boundary.

---

## Edge Cases

- A dataset adapter cannot provide tools. Tool-mediated strategies fail with a capability-unavailable error. Inline strategies may still run.
- A dataset adapter cannot provide an oracle. Evaluation proceeds using evidence when the evaluator supports evidence-only assessment.
- A requested context representation is unsupported. The adapter raises an unsupported-representation error. The core does not silently fall back to a different representation.
- A temporary Lattes adapter remains in `ctxbench-cli`. This is allowed during Spec 004 only if generic lifecycle code consumes it exclusively through the adapter contract.
- The registry cannot resolve a dataset identity. The benchmark fails deterministically before planning or execution consumes dataset contents.
- A dataset has internal files whose names resemble Lattes files. The core still treats those names as internal to the adapter.
- An experiment uses `format` in factors. In v0 this remains valid, but its meaning is context representation, not physical file format.
- A future software-repository dataset needs workspaces or executable oracles. Those capabilities are out of scope for Spec 004 and must be introduced by a future specification if needed.

## Requirements

### Core Responsibilities

- **FR-001**: The benchmark core MUST own the generic lifecycle: planning, execution orchestration, strategy orchestration, response collection, evaluation orchestration, export, and status reporting.
- **FR-002**: The benchmark core MUST express its dataset-facing behavior using generic vocabulary: `dataset`, `instance`, `task`, `trial`, `context`, `evidence`, `oracle`, `tool`, `response`, and `evaluation`.
- **FR-003**: The benchmark core MUST interact with datasets only through adapters implementing the Dataset Package Capabilities v0 contract.
- **FR-004**: The benchmark core MUST NOT directly import, parse, traverse, or interpret domain-specific dataset payloads.
- **FR-005**: Generic lifecycle phases MUST NOT branch on concrete dataset identities.

### Adapter Responsibilities

- **FR-006**: A dataset adapter MUST implement the Dataset Package Capabilities v0 contract for one concrete dataset or domain.
- **FR-007**: A dataset adapter MUST own domain-specific parsing, decoding, layout interpretation, representation mapping, context selection, evidence selection, oracle availability, and domain-specific tools.
- **FR-008**: A dataset adapter MAY use domain-specific terminology internally, but its core-facing surface MUST expose generic vocabulary.
- **FR-009**: A dataset adapter MAY be implemented temporarily inside `ctxbench-cli` during Spec 004.
- **FR-010**: Moving the Lattes adapter implementation from `ctxbench-cli` to `ctxbench/lattes` is deferred to Spec 006.

### Adapter Registry v0

- **FR-011**: CTXBench MUST resolve a dataset reference to a dataset adapter before lifecycle phases consume the dataset.
- **FR-012**: The Adapter Registry v0 MUST be the only component allowed to bind a concrete dataset identity or dataset kind to a concrete adapter implementation.
- **FR-013**: The Adapter Registry v0 MUST use explicit first-party registrations.
- **FR-014**: The Adapter Registry v0 MUST support the current Lattes dataset and prepare for a future software-repository dataset without requiring changes in `plan`, `execute`, `eval`, `export`, or `status`.
- **FR-015**: If no adapter can be resolved, the registry MUST fail deterministically with an adapter-unavailable error.
- **FR-016**: Dynamic plugin discovery, Python package entry points, remote code loading, third-party adapter installation, and plugin marketplaces are out of scope for Spec 004.

### Mandatory Dataset Package Capabilities

- **FR-017 — Metadata**: A dataset adapter MUST expose dataset identity, dataset version, human-readable name, domain, description, and origin or provenance reference when available.
- **FR-018 — Instance enumeration**: A dataset adapter MUST enumerate benchmark instances using stable `instanceId` values.
- **FR-019 — Task enumeration**: A dataset adapter MUST enumerate benchmark tasks using stable `taskId` values.
- **FR-020 — Task loading**: A dataset adapter MUST resolve a `taskId` to a task object containing, at minimum, a prompt-ready task statement or enough generic information for a strategy to construct one.
- **FR-021 — Context access**: A dataset adapter MUST provide context for a given `(instanceId, taskId, representation)` request.
- **FR-022 — Evidence access**: A dataset adapter MUST provide evidence for a given `(instanceId, taskId)` request.

### Optional Dataset Package Capabilities

- **FR-023 — Oracle access**: A dataset adapter MAY provide an oracle for a given `(instanceId, taskId)`.
- **FR-024**: If no oracle is available, the adapter MUST return an explicit unavailable result. It MUST NOT fabricate an oracle.
- **FR-025**: An oracle is distinct from evidence. Evidence is material used to support judgment. Oracle is an expected answer, validation rule, reference output, reference label, or authoritative outcome used to evaluate a response.
- **FR-026 — Tool access**: A dataset adapter MAY provide domain-specific tools for tool-mediated strategies.
- **FR-027**: If tools are unavailable and the selected strategy requires tools, execution MUST fail with a capability-unavailable error.
- **FR-028 — Fixtures**: A dataset adapter SHOULD provide small provider-free fixtures for conformance validation. Fixtures are recommended but not mandatory in v0.

### Context, Evidence, and Oracle Semantics

- **FR-029**: Context is what the model under test may receive during execution.
- **FR-030**: Evidence is what the evaluator or judge may receive during evaluation.
- **FR-031**: Oracle is an expected or authoritative criterion used for evaluation when available.
- **FR-032**: The same underlying payload MAY serve more than one role, but the access role MUST be recorded distinctly.
- **FR-033**: The benchmark runtime MUST record whether context, evidence, and oracle were available and used for each trial or evaluation when that information is available at runtime.

### Experiment Definition Requirements

- **FR-034**: The experiment definition MUST identify the dataset using a generic dataset reference, not dataset-specific file paths or adapter classes.
- **FR-035**: When `dataset.id` is present, the Adapter Registry v0 MUST use it, together with any required dataset metadata, to resolve the dataset adapter.
- **FR-036**: The experiment definition MUST NOT contain concrete adapter class names, Python module paths, parser names, tool implementation names, or Lattes-specific filenames.
- **FR-037**: The `dataset.root` field MAY be used to reference an already materialized local dataset package.
- **FR-038**: The `dataset.id` and `dataset.version` fields SHOULD be used when the experiment refers to a versioned dataset package.
- **FR-039**: In v0, `factors.format` SHALL remain the public experiment field for compatibility, but its semantic meaning MUST be "context representation requested from the dataset adapter."
- **FR-040**: This specification MUST NOT require generated JSON Schema artifacts for experiment definitions. Validation remains owned by the Pydantic model layer unless a future specification changes that decision.
- **FR-041**: This specification MUST NOT force a broad rename of existing experiment fields unless the rename is already required by accepted canonical terminology.

### Dataset Layout Isolation

- **FR-042**: Physical filenames and directory layout are dataset-internal concerns.
- **FR-043**: The benchmark core MUST NOT map context representations directly to dataset-specific filenames.
- **FR-044**: If a representation is unsupported for a task or dataset, the adapter MUST fail deterministically with an unsupported-representation error.

### Lifecycle Phase Requirements

- **FR-045**: `plan` MUST use dataset metadata, instance enumeration, task enumeration, and task loading through the resolved adapter.
- **FR-046**: `execute` MUST use task loading, context access, and optional tools through the resolved adapter.
- **FR-047**: `eval` MUST use evidence access and optional oracle access through the resolved adapter.
- **FR-048**: `export` SHOULD operate only on already produced benchmark artifacts and SHOULD NOT require dataset access.
- **FR-049**: `status` SHOULD operate only on already produced benchmark artifacts and SHOULD NOT require dataset access.

### Scope Discipline

- **FR-050**: This specification MUST NOT modify Spec 003.
- **FR-051**: This specification MUST NOT move Lattes code or data to `ctxbench/lattes`.
- **FR-052**: This specification MUST NOT introduce a plugin framework.
- **FR-053**: This specification MUST NOT introduce dynamic adapter discovery.
- **FR-054**: This specification MUST NOT introduce Python package entry-point loading.
- **FR-055**: This specification MUST NOT introduce remote code loading.
- **FR-056**: This specification MUST NOT introduce third-party adapter installation.
- **FR-057**: This specification MUST NOT introduce multiple datasets per experiment.
- **FR-058**: This specification MUST NOT introduce API-backed runtime datasets.
- **FR-059**: This specification MUST NOT introduce workspaces, sandboxes, or executable oracle machinery.
- **FR-060**: This specification MUST NOT introduce dataset-contributed strategies.

## Key Entities

- **Benchmark Core**: The generic CTXBench runtime responsible for lifecycle phases, strategy orchestration, evaluation orchestration, artifact writing, export, and status reporting.
- **Dataset Adapter**: A component that implements the Dataset Package Capabilities v0 contract for one concrete dataset or domain.
- **Adapter Registry v0**: An explicit, in-process registry that maps a dataset identity or dataset kind to an adapter factory. It centralizes adapter selection without introducing plugin loading.
- **Dataset Package**: A resolved dataset package that may be materialized from a local path, cache, descriptor, or distribution mechanism governed by Spec 003.
- **Instance**: One benchmark unit identified by `instanceId`.
- **Task**: One benchmark task identified by `taskId`.
- **Context**: Payload provided to the model under test during execution.
- **Evidence**: Payload provided to the evaluator or judge during evaluation.
- **Oracle**: Optional expected answer, validation rule, reference output, reference label, or authoritative outcome.
- **Tool Provider**: Optional dataset adapter capability that exposes domain-specific operations to tool-mediated strategies.
- **Temporary In-Repository Adapter**: A dataset adapter implemented inside `ctxbench-cli` as a migration step. The Lattes adapter MAY remain in this form during Spec 004.

## Success Criteria

- **SC-001**: A reviewer can identify the responsibilities of the benchmark core, adapter registry, and dataset adapters without reading implementation code.
- **SC-002**: `plan`, `execute`, and `eval` consume datasets through adapters resolved by the Adapter Registry v0.
- **SC-003**: Generic lifecycle code contains no direct mapping from context representation names to Lattes physical filenames.
- **SC-004**: The Adapter Registry v0 supports explicit first-party registration for the current Lattes dataset and a future software-repository adapter path.
- **SC-005**: Evaluation can distinguish evidence-only tasks from tasks with an available oracle.
- **SC-006**: Tool-mediated strategies obtain tools through the adapter boundary or fail with a capability-unavailable error.
- **SC-007**: Existing experiment definitions using `factors.format` remain valid in v0, with `format` documented as a context representation request.
- **SC-008**: No experiment definition needs to name a concrete adapter class, Python module, parser, or dataset-specific filename.
- **SC-009**: `export` and `status` remain artifact-only unless a future spec explicitly changes that rule.

## In Scope

- Core/adapter boundary.
- Adapter Registry v0 with explicit first-party registrations.
- Dataset Package Capabilities v0.
- Mandatory capabilities: metadata, instances, tasks, context, evidence.
- Optional capabilities: oracle, tools, fixtures.
- Distinction between context, evidence, and oracle.
- Dataset layout isolation.
- Experiment definition impact related to dataset references and `format` semantics.
- Temporary in-repository Lattes adapter support during migration.

## Out of Scope

- Modifying Spec 003.
- Moving Lattes code or data to `ctxbench/lattes`.
- Full removal of Lattes-specific implementation from `ctxbench-cli` (deferred to Spec 006).
- Implementing the software-repository dataset.
- Plugin framework.
- Dynamic adapter discovery.
- Python package entry-point loading.
- Remote code loading.
- Third-party adapter installation.
- Multiple datasets per experiment.
- API-backed runtime datasets.
- Workspaces and sandboxes.
- Executable oracle machinery.
- Dataset-contributed strategies.
- Generated JSON Schema artifacts.
- Broad renaming of existing experiment definition fields.
- New generic strategies.
- Concrete Python class names, module layout, or method signatures beyond what planning requires.

## Decisions Deferred to Planning

- Concrete interface names and method signatures.
- Concrete module layout for the adapter contract and registry.
- Concrete representation of unavailable capabilities.
- Concrete representation of unsupported-representation errors.
- Concrete payload shapes for task, context, evidence, oracle, and tools.
- How the registry stores explicit first-party registrations.
- How the temporary Lattes adapter is wired without spreading Lattes-specific behavior through generic lifecycle phases.
- How context/evidence/oracle/tool access is recorded in traces.
- Whether `format` remains long-term or is later renamed to `representation` or `contextRepresentation`.
- How provider-free fixtures validate adapter conformance.
- How a future software-repository adapter will exercise the same registry and capabilities.
- Whether instances carry adapter-exposed metadata in v0, and whether `list_instances` accepts a filter.

## Future Work

The following topics are intentionally deferred:

- Spec 006: move the Lattes adapter implementation to `ctxbench/lattes` and make Lattes the first external dataset package conforming to this contract.
- Spec 007 or later: define the software-repository dataset and its adapter.
- A future adapter-registration specification may introduce plugin loading if first-party explicit registration becomes insufficient.
- A future schema specification may publish generated schemas for experiment definitions, trials, responses, evaluations, judge votes, dataset descriptors, and exported analysis files.
