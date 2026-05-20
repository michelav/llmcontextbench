# Specification Quality Checklist: Domain Architecture Boundaries

**Purpose**: Validate roadmap-level specification completeness and quality before proceeding to planning or follow-on specs
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Roadmap-Level Discipline

- [x] Spec defines intent, scope, dependencies, and non-goals without prescribing implementation
- [x] Decisions intentionally deferred to planning or follow-on specs are listed explicitly
- [x] Dependencies on previous specs are named
- [x] Future specs enabled by this one are named
- [x] Affected concepts, artifacts, and docs are enumerated

## Boundary Discipline

- [x] Benchmark core responsibilities are described independently of any domain
- [x] Dataset/domain adapter responsibilities are described independently of any specific domain
- [x] Each of the seven boundary concerns is named with explicit responsibilities on both sides
- [x] Lattes-specific leakage categories are enumerated and quarantined
- [x] Provider-free fake-domain validation is required as the canonical boundary proof

## Notes

- All items pass. Spec is ready for planning or for follow-on per-domain or per-boundary specs.
- Scope is explicitly fenced by FR-021 through FR-025 to prevent the spec from drifting into Lattes refactor, new-domain implementation, plugin frameworks, or CLI/terminology changes.
- The seven boundary contracts (FR-006–FR-011 plus the enumeration/dataset surface implicit in FR-001) are described at the responsibility level only; concrete signatures are deferred.
- The fake-domain validation pattern is the canonical proof of correctness and is required by FR-016 through FR-020.
- The spec respects Constitution Principle VII (Boundary Isolation) and Principle XII (Simplicity), and acknowledges Principle X (Provider-Free Validation) via the fake-domain requirement.

---

# Requirements Quality Checklist: Dataset Package Capabilities and Core/Adapter Boundary

**Purpose**: Validate that the requirements in Spec 004 are clear, complete, consistent, and measurable across all 16 defined focus areas. This checklist tests the quality of the written requirements — not the implementation.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Spec 003 / Spec 004 Boundary Clarity

- [x] CHK001 - Is the separation between Spec 003 (acquisition/materialization) and Spec 004 (runtime consumption) stated unambiguously, with no lifecycle concern assigned to both? [Clarity, Spec §Relationship to Spec 003]
- [x] CHK002 - Does the statement "Lifecycle commands MUST NOT acquire datasets implicitly" (§Relationship to Spec 003) correspond to a formal FR, or is it stated only in prose without a requirement anchor? [Completeness, Spec §Relationship to Spec 003]
- [x] CHK003 - Is the handoff point between Spec 003 materialization and Spec 004 adapter resolution defined precisely enough that a reviewer can determine which spec governs the `dataset fetch → plan` transition? [Clarity, Spec §Relationship to Spec 003]

## Core / Registry / Adapter Boundary

- [x] CHK004 - Does the benchmark core's responsibility description (FR-001–FR-005) avoid naming domain-specific identifiers, file layouts, or payload structures? [Clarity, Spec §FR-001–FR-005]
- [x] CHK005 - Are the exclusive responsibilities of the core, the registry, and the adapter mutually exclusive with no gaps or overlaps? [Consistency, Spec §Core/Adapter Boundary, FR-001–FR-010]
- [x] CHK006 - Does FR-005 ("Generic lifecycle phases MUST NOT branch on concrete dataset identities") explicitly cover all five lifecycle phases, or could `export` and `status` be read as exempt? [Completeness, Spec §FR-005]
- [x] CHK007 - Is there a requirement specifying which component invokes the adapter after registry resolution, or is this intentionally deferred to planning? [Gap, Spec §Decisions Deferred to Planning]

## Dataset Package Capabilities v0

- [x] CHK008 - Are all 6 mandatory capabilities (`metadata`, `list_instances`, `list_tasks`, `get_task`, `get_context`, `get_evidence`) individually described with enough semantic detail to be unambiguous without consulting the spec authors? [Clarity, Spec §FR-017–FR-022]
- [x] CHK009 - Does the spec define whether `list_instances` returns instances in a deterministic, stable order across calls, or is ordering explicitly left unspecified? [Clarity, Gap, Spec §FR-018]
- [x] CHK010 - Is the input tuple `(instanceId, taskId, representation)` for `get_context` sufficient for all expected context scenarios, or are there cases that require additional parameters not addressed? [Completeness, Spec §FR-021]
- [x] CHK011 - Does the spec clearly state that instances are treated as opaque identifiers in v0, with no adapter-exposed per-instance metadata, or is this left implicit? [Clarity, Spec §Decisions Deferred to Planning]

## Adapter Registry v0

- [x] CHK012 - Is "explicit, in-process registry" defined precisely enough that an implementer can distinguish a conformant in-process implementation from an out-of-process one? [Clarity, Spec §Adapter Resolution and Registry v0]
- [x] CHK013 - Does FR-011 ("CTXBench MUST resolve a dataset reference to a dataset adapter before lifecycle phases consume the dataset") specify at what point in the lifecycle resolution occurs — before planning, on-demand per phase, or once per run? [Clarity, Spec §FR-011]
- [x] CHK014 - Is the distinction between the Spec 003 materialization cache and the Spec 004 adapter registry stated explicitly enough to prevent conflation? [Clarity, Spec §Adapter Resolution and Registry v0]
- [x] CHK015 - Is FR-013 ("MUST use explicit first-party registrations") consistent with the registry narrative, and does it preclude all other registration mechanisms in v0? [Consistency, Spec §FR-013, Adapter Resolution and Registry v0]

## Plugin and Dynamic Loading Exclusions

- [x] CHK016 - Are all excluded mechanisms (plugin framework, dynamic adapter discovery, Python entry points, remote code loading, third-party adapter installation) named individually in the formal scope discipline requirements (FR-052–FR-056)? [Completeness, Spec §FR-052–FR-056]
- [x] CHK017 - Are the exclusions stated consistently across the Adapter Resolution narrative, the Out of Scope list, and the FR-050–FR-060 scope discipline block — with no mechanism excluded in one location but absent from another? [Consistency, Spec §Adapter Resolution and Registry v0, Out of Scope, FR-052–FR-056]

## Temporary In-Repository Lattes Adapter

- [x] CHK018 - Is the condition permitting a temporary in-repository adapter ("only as a migration step, during Spec 004") stated precisely enough to prevent indefinite retention beyond this spec? [Clarity, Spec §Core/Adapter Boundary, FR-009]
- [x] CHK019 - Does the spec require explicitly that a temporary in-repository adapter MUST still conform to the Dataset Package Capabilities v0 contract? [Completeness, Spec §Edge Cases, FR-009]
- [x] CHK020 - Is the termination criterion for the temporary adapter (i.e., it is removed by Spec 006) traceable through FR-010 and the Out of Scope list? [Completeness, Spec §FR-010, Out of Scope]

## Future Software-Repository Adapter

- [x] CHK021 - Does FR-014's forward-compatibility constraint ("no changes required in `plan`, `execute`, `eval`, `export`, or `status`") also address the dataset management commands (`dataset fetch`, `dataset inspect`), or is that gap intentional? [Completeness, Spec §FR-014]
- [x] CHK022 - Does the spec describe what "preparing" for a future adapter concretely entails beyond registration support, or is this entirely deferred to planning? [Clarity, Spec §FR-014]

## Experiment Definition Impact

- [x] CHK023 - Does the spec define both what is prohibited in experiment definitions (adapter class names, module paths, Lattes filenames) and what is required (generic dataset reference), giving a complete picture? [Completeness, Spec §FR-034–FR-038]
- [x] CHK024 - Is `dataset.root` (FR-037) described precisely enough to distinguish a locally materialized package from an arbitrary directory that happens to contain dataset-like files? [Clarity, Spec §FR-037]
- [x] CHK025 - Does the spec address whether existing experiment definitions that currently reference Lattes-specific fields remain valid, become invalid, or require explicit migration? [Gap, Spec §Experiment Definition Impact]

## `factors.format` Semantics

- [x] CHK026 - Does the spec state at which phase an unsupported `factors.format` value causes failure — planning, adapter resolution, or execution — or is this left to implementation? [Clarity, Spec §FR-039, FR-044]
- [x] CHK027 - Does the spec describe how `format` values are communicated to the adapter — passed as-is, mapped through a translation layer, or normalized — or is this deferred to planning? [Gap, Spec §FR-039]
- [x] CHK028 - Is the semantic redefinition of `format` as "context representation" consistent between FR-039 (experiment field) and FR-021 (`get_context` parameter name `representation`)? [Consistency, Spec §FR-039, FR-021]

## Context / Evidence / Oracle Semantics

- [x] CHK029 - Are context, evidence, and oracle defined with enough precision that an implementer can classify any dataset payload without ambiguity? [Clarity, Spec §FR-029–FR-031]
- [x] CHK030 - Does FR-032 ("the same underlying payload MAY serve more than one role, but the access role MUST be recorded distinctly") define "recorded distinctly" concretely enough for implementation? [Clarity, Spec §FR-032]
- [x] CHK031 - Is the "explicit unavailable result" for oracle (FR-024) specified precisely enough that two independently written adapters would produce the same kind of result? [Clarity, Spec §FR-024]

## Optional Tools

- [x] CHK032 - Does the spec define what constitutes a "domain-specific tool" with enough clarity for an adapter author to know what to expose through the optional tools capability? [Clarity, Spec §FR-026]
- [x] CHK033 - Does the spec specify when tool availability is determined — at adapter instantiation, at strategy selection, or at execution start — or is timing left to implementation? [Gap, Spec §FR-026, FR-027]

## Error Definition Quality

- [x] CHK034 - Is "capability-unavailable error" defined with enough specificity that an implementer knows what information the error must contain (e.g., missing capability name, dataset identity)? [Clarity, Spec §FR-015, FR-027]
- [x] CHK035 - Does the spec assign responsibility for raising the capability-unavailable error to a specific component (adapter, registry, strategy, or lifecycle phase)? [Gap, Spec §FR-027]
- [x] CHK036 - Is the "capability-unavailable error" in FR-015 (registry fails to resolve a dataset) semantically consistent with the "capability-unavailable error" in FR-027 (adapter lacks tools), or do they name two different conditions under the same term? [Consistency, Spec §FR-015, FR-027]
- [x] CHK037 - Is "unsupported-representation error" defined clearly enough that an adapter author knows when to raise it versus returning an empty or fallback result? [Clarity, Spec §FR-044]
- [x] CHK038 - Is the requirement that the core MUST NOT silently fall back to a different representation stated as a formal FR, or does it appear only in the edge cases prose section? [Completeness, Spec §Edge Cases, FR-044]

## Lifecycle Phase Constraints

- [x] CHK039 - Are FR-048 and FR-049 (`export` and `status` SHOULD NOT require dataset access) sufficiently strong, or should these be MUST NOT to remove implementation ambiguity? [Clarity, Spec §FR-048, FR-049]
- [x] CHK040 - Does the spec define what `export` or `status` should do when invoked against artifacts produced by a dataset that is no longer locally available? [Coverage, Edge Case, Gap]

## Lattes Extraction Deferral to Spec 006

- [x] CHK041 - Is the deferral of Lattes extraction to Spec 006 stated both in narrative prose and as a formal requirement, with an explicit pointer to Spec 006? [Completeness, Spec §Overview, Out of Scope, FR-051]
- [x] CHK042 - Does the spec clearly distinguish between "deferring Lattes code extraction to Spec 006" and "temporarily permitting a Lattes adapter in `ctxbench-cli` during Spec 004"? [Clarity, Spec §FR-009, FR-010, FR-051]

## No Generated JSON Schema Artifacts

- [x] CHK043 - Does FR-040 exclude generated JSON Schema artifacts as a formal requirement (not merely a design note), with a clear rationale for the deferral? [Completeness, Spec §FR-040]
- [x] CHK044 - Does FR-040's exclusion scope cover only JSON Schema, or does the spec address other potential generated artifact types (e.g., OpenAPI schemas, TypeScript definitions)? [Clarity, Spec §FR-040]
