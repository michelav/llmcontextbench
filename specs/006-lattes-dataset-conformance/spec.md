# Feature Specification: Lattes Dataset Extraction

**Feature Branch**: `chore/architecture-redesign-roadmap`
**Created**: 2026-05-11
**Status**: Draft
**Input**: Extract the current Lattes dataset from the `ctxbench-cli` tool repository into an external `ctxbench/lattes` dataset package, and migrate it to the dataset extension contracts (Spec 003), the core/adapter boundary (Spec 004), and the artifact role/representation model (Spec 005), while preserving existing experiment behavior where practical.

## Overview

Lattes is the first concrete dataset CTXBench was built around. Today, Lattes data, code, questions, mappings, readers, and evaluation evidence live **inside** the `ctxbench-cli` repository. This spec defines the migration of those Lattes-specific assets into an external dataset package — `ctxbench/lattes` — and aligns them with the contracts established by the earlier roadmap specs:

- **Spec 003** defines the dataset extension contracts that an external dataset package must implement.
- **Spec 004** defines the boundary between the core engine and dataset-specific code.
- **Spec 005** defines artifact roles (*source*, *context*, *evidence*, *normalized/derived*, *metadata*) and the *(role, representation)* handle.
- **Spec 001** defines the target terminology (*task*, *trial*, *response*, `trialId`, `taskId`).
- **Spec 002** defines artifact contracts (identity, version, canonical vs derived).

This spec is the **first conformance migration**: it proves the contracts work by removing Lattes from `ctxbench-cli` and reattaching it via the contract surface. It does **not** redefine any contract. Where the migration reveals a genuine gap, the gap is escalated to the spec that owns the contract (002, 003, 004, or 005) — not patched here.

The spec is intentionally lightweight: it describes *what moves*, *what stays*, *how Lattes assets map onto the role/representation model*, *how compatibility is preserved where practical*, and *how the migration is staged*. Concrete file paths, reader signatures, schema layouts, package release mechanics, and migration order are deferred to planning.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Lattes lives in its own dataset package (Priority: P1)

A researcher wants to update Lattes parsing rules without touching `ctxbench-cli`. After migration, Lattes data, parsing code, task definitions, and dataset-specific tools live in the external `ctxbench/lattes` package. The researcher edits and releases Lattes independently from the engine.

**Why this priority**: This is the entire purpose of the extraction. Without it, Lattes-specific concerns continue to pollute the engine and block boundary discipline.

**Independent Test**: After migration, the `ctxbench-cli` source tree contains no Lattes-specific files; running a Lattes experiment requires the external `ctxbench/lattes` package to be installed.

**Acceptance Scenarios**:

1. **Given** an installation of `ctxbench-cli` only, **When** a Lattes experiment is requested, **Then** the engine reports that the Lattes dataset is not available and identifies the missing dataset package by name.
2. **Given** an installation of `ctxbench-cli` plus the `ctxbench/lattes` package, **When** a Lattes experiment is requested, **Then** the engine resolves Lattes through the dataset extension contracts and runs without any Lattes-specific code path inside the engine.

---

### User Story 2 - Lattes experiments still work after migration (Priority: P1)

A researcher has existing Lattes experiment configurations (instances to run, strategies selected, evaluation expectations). After migration, the same configurations continue to produce equivalent results when run against the external `ctxbench/lattes` package, except where a compatibility break is documented as unavoidable.

**Why this priority**: The migration must not destroy existing research. If experiments cannot be reproduced after the move, the extraction is a regression even if the architecture is cleaner.

**Independent Test**: A pre-migration Lattes experiment and a post-migration Lattes experiment using the same instances, strategy, and configuration produce equivalent trials and evaluation outcomes, modulo terminology and explicitly documented breaks.

**Acceptance Scenarios**:

1. **Given** a pre-migration Lattes experiment configuration, **When** the same instances and strategy run against `ctxbench-cli` + `ctxbench/lattes`, **Then** trial inputs are equivalent and evaluation outcomes are equivalent for the cases where compatibility is preserved.
2. **Given** an unavoidable compatibility break (e.g., a renamed task identifier scheme), **When** the migration is performed, **Then** the break is documented with its scope and a clear migration step for affected experiments.

---

### User Story 3 - Lattes artifacts are addressable by role and representation (Priority: P1)

When a strategy needs Lattes context or the evaluation phase needs Lattes evidence, neither selects by physical filename. Instead, they request artifacts through the role/representation handle defined in Spec 005, and the `ctxbench/lattes` package declares which of its files fill each role.

**Why this priority**: The role/representation model only delivers value if at least one real dataset uses it. Lattes is the proof.

**Independent Test**: A reviewer can read the `ctxbench/lattes` package's role declarations and determine which Lattes file fills the *context*, *evidence*, *source*, *normalized*, or *metadata* role without inspecting strategy or evaluation code.

**Acceptance Scenarios**:

1. **Given** the migrated `ctxbench/lattes` package, **When** a strategy requests *context* in a markup representation, **Then** the cleaned/minified Lattes HTML is resolved.
2. **Given** the migrated `ctxbench/lattes` package, **When** the evaluation phase requests *evidence*, **Then** the Lattes blocks JSON is resolved.
3. **Given** the migrated `ctxbench/lattes` package, **When** a strategy requests *context* in a structured-object representation, **Then** the parsed Lattes JSON is resolved (the same payload that also fills the *normalized* role).

---

### User Story 4 - Lattes-specific tools are exposed through the dataset package (Priority: P2)

Lattes ships with dataset-specific helpers (e.g., readers that turn raw artifacts into something a strategy can consume, or extractors used by evaluation). After migration, these helpers live in `ctxbench/lattes` and are exposed to `ctxbench-cli` only through the dataset package contract — never imported directly by the engine or by generic strategies.

**Why this priority**: Without this, Lattes-specific helper code stays in `ctxbench-cli` and re-creates the boundary leak the extraction was meant to remove.

**Independent Test**: The engine and the four generic strategies (*inline*, *local_function*, *local_mcp*, *remote_mcp*) contain zero direct imports of Lattes-specific code; any Lattes helper invoked during execution or evaluation is reached only through the dataset package contract.

**Acceptance Scenarios**:

1. **Given** a strategy that needs a Lattes-specific reader to assemble context, **When** the strategy executes, **Then** the reader is obtained through the dataset package contract and not by direct import.
2. **Given** the evaluation phase, **When** it needs Lattes-specific evidence extraction, **Then** that extraction is provided by the Lattes evidence provider exposed through the dataset package contract.

---

### Edge Cases

- A Lattes file does not cleanly fit any of the five roles defined in Spec 005. The migration must either justify which role it belongs to (and record that justification in the package's role declarations) or recognize that the file is not actually a dataset artifact and route it accordingly (e.g., as metadata or as internal-only data not exposed through the contract).
- An existing Lattes experiment configuration uses the legacy `questionId`/`runId`/`answer` terminology. The migration must define how those identifiers translate (or are regenerated) under the target `taskId`/`trialId`/`response` terminology from Spec 001.
- An existing Lattes question has no question-instance mapping (or has multiple). The migration must define the canonical task-instance mapping shape and how the legacy data is converted.
- `ctxbench-cli` references a Lattes file directly by path inside the engine or inside a generic strategy. The migration must remove that direct reference, not relocate it. Direct path references are a boundary violation regardless of which side of the migration they live on.
- The Lattes parsed JSON payload fills two roles simultaneously (*normalized* and *context*). The migration must declare both without duplicating the underlying payload (per Spec 005 multi-role payload handling).
- A Lattes asset has no analogue in the role/representation model (e.g., curriculum metadata about the donor researcher). The migration routes it as a *metadata* artifact and forbids it from being mistaken for *context* or *evidence*.
- The version of `ctxbench/lattes` installed does not satisfy the version handshake declared by `ctxbench-cli`. The engine must refuse to run with a deterministic, identifiable error rather than silently using whatever is present.

## Requirements *(mandatory)*

### Functional Requirements

#### Inventory of current Lattes assets

- **FR-001**: The migration MUST produce an inventory of every Lattes-specific file currently inside `ctxbench-cli` — data files (HTML, parsed JSON, blocks JSON), code (parsers, readers, extractors, dataset-specific tools), task/question definitions, question-instance mappings, and evaluation evidence definitions.
- **FR-002**: The migration MUST identify, for each item in the inventory, whether it MOVES to `ctxbench/lattes`, REMAINS in `ctxbench-cli`, or is DELETED (i.e., its responsibility is absorbed by a generic contract).
- **FR-003**: The migration MUST identify every direct reference from `ctxbench-cli` engine or generic strategy code to Lattes-specific identifiers, paths, or symbols. Every such reference is a boundary violation and MUST be removed during the migration, not relocated.
- **FR-004**: The migration MUST identify Lattes-specific helpers (readers, extractors, dataset tools) that are invoked at execution time, at evaluation time, or both, so each can be routed through the correct extension point in Spec 003.
- **FR-005**: The migration MUST identify Lattes assets that have no role in the Spec 005 model and decide explicitly how each is handled (as *metadata*, as internal-only data not exposed, or as a signal that a real contract gap exists in Spec 005).

#### Migration target — what moves to `ctxbench/lattes`

- **FR-006**: All Lattes data files MUST move to `ctxbench/lattes` and be declared by *(role, representation)* under Spec 005, not by physical filename.
- **FR-007**: All Lattes-specific parsing code MUST move to `ctxbench/lattes`.
- **FR-008**: All Lattes-specific readers and dataset tools used during strategy execution MUST move to `ctxbench/lattes` and be exposed through the dataset package contract from Spec 003.
- **FR-009**: All Lattes-specific evidence extractors used during evaluation MUST move to `ctxbench/lattes` and be exposed through the evidence-artifact provider from Spec 003 / Spec 004.
- **FR-010**: All Lattes task definitions (formerly *questions*) MUST move to `ctxbench/lattes` and use target terminology from Spec 001 (`taskId`, *task*).
- **FR-011**: All Lattes task-instance mappings (formerly *question-instance mappings*) MUST move to `ctxbench/lattes` and use target terminology from Spec 001.

#### Migration boundary — what remains in `ctxbench-cli`

- **FR-012**: `ctxbench-cli` MUST retain the core engine, the generic phases (`plan`, `execute`, `eval`, `export`, `status`), the four generic strategies (*inline*, *local_function*, *local_mcp*, *remote_mcp*), generic evaluation, and the contract definitions themselves.
- **FR-013**: `ctxbench-cli` MUST NOT contain any Lattes-specific data, code, identifiers, task definitions, mappings, readers, extractors, or paths after the migration. The only Lattes-related content allowed is the dataset name in version-handshake metadata, configuration examples, and documentation.
- **FR-014**: `ctxbench-cli` MUST NOT import any symbol from `ctxbench/lattes` directly. All access goes through the dataset extension contracts.

#### Role/representation mapping (per Spec 005)

- **FR-015**: Lattes **raw HTML** MUST be declared as the *source* artifact.
- **FR-016**: Lattes **cleaned/minified HTML** MUST be declared as a *context* artifact in a markup-bearing representation.
- **FR-017**: Lattes **parsed JSON** MUST be declared with **two roles**: *normalized/derived* (it is a deterministic derivation of the source) and *context* (it is also offered to strategies as a structured-object representation), without duplicating the underlying payload.
- **FR-018**: Lattes **blocks JSON** MUST be declared as an *evidence* artifact.
- **FR-019**: Any Lattes asset not covered by FR-015–FR-018 (e.g., curriculum-level metadata about the donor researcher) MUST be declared as *metadata* and MUST NOT be selectable as *context* or *evidence*.
- **FR-020**: The Lattes package MUST NOT introduce new artifact roles beyond the five defined in Spec 005.
- **FR-021**: The Lattes package MUST use domain-neutral representation names (per Spec 005 FR-003); the names MUST NOT include Lattes-specific terminology.

#### Terminology and identifier mapping (per Spec 001)

- **FR-022**: Lattes **questions** MUST be renamed to *tasks* and addressed by `taskId`. The migration MUST define how legacy `questionId` values are converted (preserved, transformed, or regenerated) and MUST document the transformation deterministically.
- **FR-023**: Lattes **question-instance mappings** MUST be renamed to *task-instance mappings*.
- **FR-024**: Legacy terminology (`questionId`, `runId`, `answer`, `query`, `queries.jsonl`, `answers.jsonl`, `copa`) MUST NOT appear in the migrated Lattes package, in line with Spec 001's no-compatibility-aliases policy.

#### Distribution and extension-contract conformance (per Spec 003)

- **FR-025**: The `ctxbench/lattes` package MUST conform to all mandatory dataset extension contracts defined in Spec 003.
- **FR-026**: The `ctxbench/lattes` package MUST register its tasks, task-instance mappings, context-artifact provider, and evidence-artifact provider through the contracts from Spec 003.
- **FR-027**: If the migration reveals a genuine gap in the Spec 003 contracts (i.e., an extension point that Lattes legitimately needs but cannot express), the gap MUST be escalated to Spec 003 as an amendment — it MUST NOT be patched by accommodating Lattes-specific behavior inside `ctxbench-cli`.
- **FR-028**: The `ctxbench/lattes` package MUST declare a dataset identity and a dataset version per Spec 003, so every run records which Lattes version produced it.

#### Boundary conformance (per Spec 004)

- **FR-029**: After migration, the core engine and generic strategies in `ctxbench-cli` MUST contain zero direct references to Lattes — no imports, no path constants, no symbol names, no task identifiers.
- **FR-030**: Lattes-specific code MUST cross the boundary only through the dataset extension contracts; it MUST NOT be reachable through any other path (provider adapters, generic strategies, generic evaluation, or CLI internals).

#### Compatibility and reproducibility

- **FR-031**: For Lattes experiment configurations that the migration declares **compatible**, running the same instances and the same strategy against `ctxbench-cli` + `ctxbench/lattes` MUST produce equivalent trial inputs and equivalent evaluation outcomes (modulo terminology rename).
- **FR-032**: For Lattes experiment configurations that the migration declares **incompatible**, the migration MUST document the break, its scope, and the manual or automated step required to update the configuration.
- **FR-033**: Every Lattes run MUST record the `ctxbench-cli` version and the `ctxbench/lattes` package version that produced it, per Spec 003 reproducibility requirements.
- **FR-034**: The `ctxbench-cli` version and the `ctxbench/lattes` package version MUST be checked at run-start via a version handshake. If the handshake fails, the engine MUST refuse to run with a deterministic, identifiable error — it MUST NOT silently fall back.

#### Migration process

- **FR-035**: The migration MUST be documented as a reproducible sequence of steps (which assets move, in what order, and what verifies the move).
- **FR-036**: The migration MUST define what acceptance evidence is required to declare the extraction complete (at minimum: the inventory from FR-001, the boundary check from FR-029/FR-030, the equivalence check from FR-031, and the version handshake from FR-034).
- **FR-037**: The migration MUST NOT require any provider-backed execution to verify the extraction. Verification MUST use offline fixtures, recorded traces, or provider-free strategies, per Constitution Principle X.

#### Scope discipline

- **FR-038**: This spec MUST NOT introduce a software-repository dataset or any second domain. That is a separate spec.
- **FR-039**: This spec MUST NOT introduce new generic strategies. Dataset-specific *presets* (i.e., parameterized configurations of existing strategies) are allowed only if Lattes genuinely requires them; a new generic strategy is not.
- **FR-040**: This spec MUST NOT change provider behavior, model-provider adapters, or LLM-provider integration.
- **FR-041**: This spec MUST NOT introduce a plugin framework, dynamic remote code execution, or any extension mechanism beyond the contracts defined by Spec 003.
- **FR-042**: This spec MUST NOT redesign the dataset artifact role model (governed by Spec 005), the dataset extension contracts (governed by Spec 003), the core/adapter boundary (governed by Spec 004), the artifact contracts (governed by Spec 002), or the CLI/terminology (governed by Spec 001). If a real gap is uncovered, escalate to the owning spec.
- **FR-043**: This spec MUST NOT execute or rely on provider-backed commands for validation.

### Key Entities *(include if feature involves data)*

- **Lattes Dataset Package**: The external `ctxbench/lattes` package that contains all Lattes-specific data, code, task definitions, mappings, readers, and evidence extractors after migration. Conforms to the Spec 003 dataset extension contracts.
- **Lattes Inventory**: The enumeration of every Lattes-specific file and symbol currently inside `ctxbench-cli`, classified as MOVE / REMAIN / DELETE. Produced once during migration; consulted to verify completeness.
- **Lattes Task**: The renamed *question*, addressed by `taskId` per Spec 001. Lives in the Lattes package.
- **Lattes Task-Instance Mapping**: The renamed *question-instance mapping*. Lives in the Lattes package.
- **Lattes Source Artifact**: The raw Lattes HTML, declared in the *source* role per Spec 005.
- **Lattes Context Artifact (markup)**: The cleaned/minified Lattes HTML, declared in the *context* role with a markup-bearing representation.
- **Lattes Normalized + Context Artifact (structured)**: The parsed Lattes JSON, declared simultaneously in the *normalized/derived* role and the *context* role (structured-object representation), per Spec 005 multi-role payload handling.
- **Lattes Evidence Artifact**: The Lattes blocks JSON, declared in the *evidence* role per Spec 005, consumed by evaluation through the evidence-artifact provider.
- **Lattes Reader / Tool**: Dataset-specific helper code that turns Lattes artifacts into a form usable by a strategy or by evaluation. Exposed only through the Spec 003 dataset package contract.
- **Lattes Version Handshake**: The recorded pair of `ctxbench-cli` version and `ctxbench/lattes` package version that produced a given run; consulted at run-start and stored in run output.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After migration, the `ctxbench-cli` source tree contains zero Lattes-specific data files, Lattes-specific code, Lattes-specific task or mapping definitions, Lattes-specific identifiers, and zero direct imports or path references to Lattes.
- **SC-002**: A Lattes experiment can be run against `ctxbench-cli` + `ctxbench/lattes` without any provider-backed execution and without any Lattes-specific code path inside `ctxbench-cli`.
- **SC-003**: For every Lattes experiment configuration declared compatible, the post-migration trial inputs and evaluation outcomes are equivalent to the pre-migration baseline for the same configuration (modulo terminology rename). Incompatible configurations have a documented, scoped break note.
- **SC-004**: Every Lattes artifact is addressable by *(role, representation)* per Spec 005; a reviewer can determine which Lattes file fills which role without inspecting strategy or evaluation code.
- **SC-005**: Every Lattes run records both the `ctxbench-cli` version and the `ctxbench/lattes` package version. A version-handshake failure stops the run with a deterministic, identifiable error.
- **SC-006**: The migration steps are documented as a reproducible sequence and the acceptance evidence (inventory, boundary check, equivalence check, version handshake) is captured.

## Assumptions

- Spec 001 (command model and target terminology), Spec 002 (artifact contracts), Spec 003 (dataset extension contracts), Spec 004 (core/adapter boundary), and Spec 005 (role/representation model) are accepted and stable at the point this migration begins.
- `ctxbench/lattes` will be developed as the implementation target of this migration in parallel with `ctxbench-cli`'s removal of Lattes-specific code. The two repositories are released in coordination via the version handshake.
- The set of Lattes-specific assets currently inside `ctxbench-cli` is finite and enumerable from a single inventory pass; nothing is dynamically generated at runtime that the inventory would miss.
- The Lattes parsed JSON payload is permitted to fill two roles (*normalized/derived* and *context*) per Spec 005 multi-role payload handling, without payload duplication.
- Existing Lattes experiment configurations using legacy terminology (`questionId`, `runId`, `answer`, `queries.jsonl`, `answers.jsonl`) are migrated as part of the renaming work covered by Spec 001 and are not preserved as compatibility aliases here.
- No provider-backed execution is required to verify the extraction; verification uses recorded fixtures and provider-free strategies (Constitution Principle X).
- The mapping from raw HTML → source, cleaned HTML → context, parsed JSON → normalized/context, and blocks JSON → evidence is correct as stated. If the migration discovers a deeper-than-trivial structural mismatch, that is treated as a real gap in Spec 005 and escalated, not patched here.

## Dependencies

- **Spec 001 — Command model and phase renaming** — terminology baseline (`task`, `trial`, `response`, `taskId`, `trialId`); legacy names removed.
- **Spec 002 — Artifact contracts** — defines what an artifact is (identity, version, canonical vs derived); not redefined here.
- **Spec 003 — Dataset distribution and extension contracts** — defines what `ctxbench/lattes` must implement to be a valid external dataset package.
- **Spec 004 — Domain architecture boundaries** — defines the core/adapter boundary that the migration must respect.
- **Spec 005 — Dataset artifact model** — defines the role/representation handle that the Lattes package must use to expose its artifacts.

## Future specs enabled by this one

- **Lattes package release and versioning policy** — how `ctxbench/lattes` versions are cut, deprecated, and matched against `ctxbench-cli` versions.
- **Lattes-specific presets** — parameterized configurations of generic strategies (if and only if Lattes requires them in practice).
- **Compat shim removal** — if a transition window is introduced during migration, a follow-on spec defines when and how it ends.
- **Second-domain conformance (e.g., software-repository dataset)** — uses the contracts validated by this migration as the conformance template.

## In scope

- Inventory of Lattes assets currently in `ctxbench-cli`.
- Move of Lattes data, code, task definitions, mappings, readers, and evidence extractors to `ctxbench/lattes`.
- Mapping of Lattes artifacts to *(role, representation)* per Spec 005.
- Mapping of Lattes questions and question-instance mappings to tasks and task-instance mappings per Spec 001.
- Exposure of Lattes-specific readers and tools through the Spec 003 dataset package contract.
- Exposure of Lattes evidence through the Spec 003 / Spec 004 evidence-artifact provider.
- Compatibility expectations and break documentation.
- Version handshake between `ctxbench-cli` and `ctxbench/lattes`.
- Migration steps and acceptance evidence.

## Out of scope

- Implementing a software-repository dataset or any second domain.
- Introducing new generic strategies (dataset-specific *presets* only if Lattes genuinely requires them).
- Changing provider behavior, model-provider adapters, or LLM-provider integration.
- Introducing a plugin framework, dynamic remote code execution, or any extension mechanism beyond Spec 003 contracts.
- Redesigning the role/representation model (Spec 005), the dataset extension contracts (Spec 003), the core/adapter boundary (Spec 004), the artifact contracts (Spec 002), or the CLI/terminology (Spec 001).
- Provider-backed execution for verification.
- Long-lived legacy compatibility aliases for terminology renamed by Spec 001.

## Decisions deferred to planning

- The concrete migration order (which assets move first, and which can move in parallel).
- The concrete file layout of `ctxbench/lattes`.
- The concrete reader signatures, schema layouts, and helper interfaces exposed by `ctxbench/lattes`.
- Whether a short-lived compatibility shim is offered during transition, and how it is gated.
- The deterministic rule for converting legacy `questionId` values into `taskId` values (preserve, transform, or regenerate).
- Whether the parsed-JSON multi-role payload is published as one artifact with two role declarations or as two artifacts sharing a payload reference (constrained by Spec 005's no-duplication rule either way).
- The concrete release/versioning cadence for `ctxbench/lattes` (covered by a follow-on spec listed above).
- The concrete contents of a Lattes "preset" if one proves necessary, and the rule that decides when a preset is justified.
