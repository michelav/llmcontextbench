# Tasks: Dataset Package Capabilities and Core/Adapter Boundary

**Input**: Design documents from `/specs/004-dataset-package-capabilities/`  
**Prerequisites**: `spec.md`, `plan.md`, `data-model.md`, `contracts/dataset-adapter.md`

## Task Format

`[ID] [P?] [Slice] Description`

- **[P]**: can run in parallel because it touches disjoint files and has no dependency on another in-flight task.
- **[Slice]**: implementation slice ID from `plan.md` (S1–S8).
- Include exact file paths where possible.
- All tasks are provider-free.

## Execution Rules

- Implement one slice at a time.
- Do not implement all tasks at once.
- End each slice with a green checkpoint before moving to the next.
- Commit after each green slice, not after every individual task.
- Do not perform opportunistic refactors.
- Do not call real LLM providers.

---

## Slice S1 — Payload types + error types

**Goal**: Create the typed payload and error vocabulary that the v0 contract depends on.  
**Validation**: `pytest -k "payloads or adapter_errors" -v`  
**Depends on**: —  
**Suggested commit**: `feat(dataset): add payload types and error types for v0 contract`

### Tasks

- [X] T001 [S1] Create `src/ctxbench/dataset/payloads.py` with `ContextPayload`, `EvidencePayload`, `TaskPayload` dataclasses and `OracleUnavailable` sentinel class + `ORACLE_UNAVAILABLE` singleton exactly as specified in `plan.md` § Payload Types
- [X] T002 [P] [S1] Create `src/ctxbench/dataset/errors.py` with `AdapterUnavailableError(ValueError)`, `CapabilityUnavailableError(ValueError)`, `UnsupportedRepresentationError(ValueError)` as specified in `plan.md` § Slice S1
- [X] T003 [S1] Create `tests/test_dataset_payloads.py` with tests: error types are `ValueError` subclasses; `ORACLE_UNAVAILABLE is not None`; `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` is `True`; `ContextPayload.role == "context"`; `EvidencePayload.role == "evidence"`; `TaskPayload.statement` exists

### Checkpoint

- [X] `pytest -k "payloads or adapter_errors" -v` passes
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S2 — `DatasetPackage` protocol + `AdapterRegistry` + `ResolvedDatasetRef`

**Goal**: Define the generic contract surface and registry skeleton that lifecycle phases will import.  
**Validation**: `pytest -k "dataset_package_contract or registry" -v`  
**Depends on**: S1  
**Suggested commit**: `feat(dataset): add DatasetPackage protocol, AdapterRegistry, and ResolvedDatasetRef`

### Tasks

- [X] T004 [S2] Update `src/ctxbench/dataset/package.py`: import `TaskPayload`, `ContextPayload`, `EvidencePayload` from `payloads.py`; add mandatory protocol methods `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`; add optional methods `get_oracle`, `get_task_instance`, `tool_provider`, `fixtures` with default implementations as specified in `plan.md` § DatasetPackage Protocol; keep existing `list_instance_ids`, `list_task_ids`, `identity`, `version`, `origin`, `metadata`, `capability_report`; **remove `get_context_artifact` and `get_evidence_artifact` from the `Protocol` definition** — they may remain as private implementation methods in `LocalDatasetPackage` but are not part of the v0 contract surface
- [X] T005 [P] [S2] Create `src/ctxbench/dataset/registry.py` with `ResolvedDatasetRef` (dataclass with `id`, `version`, `root`, `origin`, `content_hash`, `materialized_path`), `Factory` type alias, and `AdapterRegistry` class with `register(dataset_id, factory)` and `resolve(dataset_ref: ExperimentDataset | DatasetProvenance) → DatasetPackage` methods; `resolve` must normalize either input type into `ResolvedDatasetRef`; for `DatasetProvenance`, use `materialized_path` as `materialized_path`, `root` as `root`, and preserve `content_hash`; `resolve` raises `AdapterUnavailableError` if the normalized id is unregistered or missing; no default registry instance; no import of `ctxbench.adapters`
- [X] T006 [S2] Create `tests/test_dataset_adapter_registry.py` with tests: `AdapterRegistry.resolve` raises `AdapterUnavailableError` for unknown or missing id; `AdapterRegistry.resolve` returns the adapter produced by a registered factory for `ExperimentDataset`; `AdapterRegistry.resolve` returns the adapter produced by a registered factory for `DatasetProvenance` and preserves `materialized_path`/`content_hash` in the `ResolvedDatasetRef` passed to the factory; `AdapterRegistry.register` is callable with a factory; `ResolvedDatasetRef` is constructable with required fields — **note: this file will be extended in T033 (S7) with Lattes integration tests; treat T006 as the initial population only**

### Checkpoint

- [X] `pytest -k "dataset_package_contract or registry" -v` passes
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S3 — Package namespace: move Lattes, wire adapters registry, import-boundary tests

**Goal**: Move `ctxbench.datasets.lattes` to `ctxbench.adapters.lattes`; expose all v0 methods on `LattesDatasetAdapter`; wire `ctxbench.adapters.registry`; enforce import boundaries.  
**Validation**: `pytest -k "import_boundary or lattes_dataset or lattes_adapter" -v` and `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"`  
**Depends on**: S2  
**Suggested commit**: `refactor(adapters): move Lattes to ctxbench.adapters, wire registry, enforce import boundaries`

**Implementation note**: S3 is intentionally divided into sub-checkpoints because it moves code and changes the public adapter surface. Complete S3a, then S3b, then S3c, then S3d. Do not stub or empty the legacy package until the copied adapter imports and registry tests are green.

### S3a — Copy package and update internal imports

**Validation**: `python -c "import ctxbench.adapters.lattes.package"` and `pytest -k "lattes_dataset or lattes_adapter" -v`

### Tasks

- [X] T007 [S3] Create `src/ctxbench/adapters/__init__.py` as an empty package marker
- [X] T008 [S3] Copy the entire `src/ctxbench/datasets/lattes/` tree to `src/ctxbench/adapters/lattes/` (including `readers/` subdirectory and all existing modules: `__init__.py`, `package.py`, `tools.py`, `mcp_server.py`, `models.py`, `provider.py`, `readers/`)
- [X] T009 [S3] Update all internal imports in `src/ctxbench/adapters/lattes/` tree: replace every `ctxbench.datasets.lattes.*` import with `ctxbench.adapters.lattes.*`

### S3b — Rename adapter and add v0 methods

**Validation**: `pytest -k "lattes_dataset or lattes_adapter" -v`

### Tasks

- [X] T010 [S3] Rename class `LattesDatasetPackage` → `LattesDatasetAdapter` in `src/ctxbench/adapters/lattes/package.py`; update all internal references within the file and within the `adapters/lattes/` tree
- [X] T011 [S3] Add `FORMAT_ARTIFACTS` dict to `src/ctxbench/adapters/lattes/package.py` (moved from `ctxbench.dataset.provider`); add `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`, `get_task_instance(instance_id, task_id) → dict | None`, `get_oracle(instance_id, task_id) → OracleUnavailable` to `LattesDatasetAdapter` using the exact logic from `plan.md` § Slice S3
- [X] T012 [S3] Update `LocalDatasetPackage` in `src/ctxbench/dataset/provider.py`: add `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`, `get_task_instance(instance_id, task_id) → dict | None`, and `get_oracle(instance_id, task_id) → OracleUnavailable` (returning `ORACLE_UNAVAILABLE`) using existing internal methods (`get_question`, `get_context_artifact`, etc.) as backing implementation; rename the current legacy helper `get_context(context_id, format_name) -> str` to a private helper such as `_read_context_text(context_id, format_name)` and update internal callers/tests that used the old two-argument signature; keep `get_context_artifact` and `get_evidence_artifact` only as migration-private/internal helpers, not as protocol methods; `get_oracle` must be explicitly defined because Python `Protocol` default method bodies are not inherited by concrete implementors
- [X] T013 [S3] Remove Lattes specialization from `src/ctxbench/dataset/provider.py`: remove `FORMAT_ARTIFACTS` from this module, remove `_specialized_local_dataset_package`, and ensure `DatasetProvider.from_dataset` / `LocalDatasetPackage.from_dataset` no longer imports `ctxbench.datasets.lattes` or `ctxbench.adapters.lattes`; if generic context filename mapping is still needed by `LocalDatasetPackage`, import or call the existing generic helper in `src/ctxbench/dataset/contexts.py`; do not remove `DatasetProvider.from_dataset` itself in Spec 004

### S3c — Wire registry and enforce import boundaries

**Validation**: `pytest -k "import_boundary or registry or lattes_adapter" -v` and `python -c "import ctxbench.adapters.registry"`

### Tasks

- [X] T014 [S3] Create `src/ctxbench/adapters/registry.py` with a private `_registry = AdapterRegistry()`, registration of `"ctxbench/lattes"` → `LattesDatasetAdapter` factory, and `get_default_registry() → AdapterRegistry` function; only this module may import `LattesDatasetAdapter`; the factory must receive `ResolvedDatasetRef` and use `ref.materialized_path or ref.root`
- [X] T015 [S3] Create `tests/test_import_boundaries.py` with tests that: (a) no module in `ctxbench.benchmark.*` imports `ctxbench.adapters.lattes` directly; (b) no module in `ctxbench.dataset.*` imports `ctxbench.adapters`; (c) no module in `ctxbench.commands.*` imports `ctxbench.adapters.lattes` directly; (d) `src/ctxbench/dataset/provider.py` does not import `ctxbench.datasets.lattes` or `ctxbench.adapters.lattes`

### S3d — Legacy compatibility stubs

**Validation**: `pytest -k "lattes_dataset or import_boundary" -v`

### Tasks

- [X] T016 [S3] Replace all `.py` implementation files in `src/ctxbench/datasets/lattes/` with backward-compatible redirect stubs after S3a-S3c validations pass: `__init__.py` re-exports `LattesDatasetAdapter` and a compatibility alias `LattesDatasetPackage`; `package.py` re-exports `LattesDatasetAdapter` and `LattesDatasetPackage`; `provider.py`, `tools.py`, `mcp_server.py`, `models.py`, and every `readers/*.py` re-export their moved symbols from `ctxbench.adapters.lattes.*`; `readers/__init__.py` re-exports the moved reader symbols; do not delete the directory or its `__init__.py` files; remove implementation logic from the legacy modules, but keep old import paths working for compatibility
- [X] T017 [S3] Add or update compatibility tests in `tests/test_lattes_dataset_package.py` and `tests/test_lattes_sections.py` proving legacy imports from `ctxbench.datasets.lattes.package`, `ctxbench.datasets.lattes.provider`, `ctxbench.datasets.lattes.tools`, `ctxbench.datasets.lattes.mcp_server`, and `ctxbench.datasets.lattes.readers.*` still resolve to the moved adapter implementations; these tests must not require provider calls

### Checkpoint

- [X] `pytest -k "import_boundary or lattes_dataset or lattes_adapter" -v` passes
- [X] `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"` exits 0
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S4 — Planning through adapter contract

**Goal**: `runspec_generator.py` and `commands/plan.py` consume the dataset only through the `DatasetPackage` protocol; no `LocalDatasetPackage` import in lifecycle code.  
**Validation**: `pytest -k "plan or cli or runspec" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(plan): thread planning through DatasetPackage adapter contract`

### Tasks

- [X] T018 [S4] Update `src/ctxbench/dataset/resolver.py`: introduce `ResolvedDatasetForPlanning` dataclass with fields `package: DatasetPackage` and `adapter_ref: ExperimentDataset | DatasetProvenance`; keep `DatasetResolver.resolve()` return type and behavior unchanged for existing callers; add a new planning-specific method `DatasetResolver.resolve_for_planning(ref, cache) -> ResolvedDatasetForPlanning` that calls the existing resolver path and derives the adapter reference without re-resolving raw experiment input; for local-root datasets set `adapter_ref` to an `ExperimentDataset` with root/id/version/origin preserved; for cache-materialized datasets set `adapter_ref` to a `DatasetProvenance` with id/version/origin/content_hash/materialized_path from the materialization manifest; add focused tests in `tests/test_dataset_resolver.py` proving existing `resolve()` callers still receive the existing package shape and `resolve_for_planning()` preserves `id`, `version`, `origin`, `content_hash`, and `materialized_path` for adapter resolution
- [X] T019 [S4] Update `src/ctxbench/benchmark/runspec_generator.py`: change type annotation of dataset parameter to `DatasetPackage`; replace `list_question_ids()` → `list_task_ids()`; replace `get_question(id)` → `get_task(id)` and update all field references (`question.question` → `task.statement`, `question.contextBlock` → `task.context_blocks`, `question.tags` → `task.tags`, `question.validation.type` → `task.validation_type`); replace `get_question_instance(id, inst)` → `get_task_instance(inst, id)` and update parameter access (`qi.parameters` → `task_inst.get("parameters", {}) if task_inst else {}`); remove `from ctxbench.dataset.provider import LocalDatasetPackage`; update focused tests in `tests/test_cli.py` that cover planning expansion and task/instance parameter rendering
- [X] T020 [S4] Update `src/ctxbench/commands/plan.py`: replace the planning call to `DatasetResolver.resolve()` with `DatasetResolver.resolve_for_planning()`; use `resolved.adapter_ref` from `ResolvedDatasetForPlanning` and call `get_default_registry().resolve(resolved.adapter_ref)` rather than re-resolving the raw experiment input; remove any `isinstance(package, LocalDatasetPackage)` branch; import `get_default_registry` from `ctxbench.adapters.registry`; pass the adapter (not the provider/package) to `generate_runspecs(experiment, base_dir, adapter, ...)`; verify that `adapter.metadata()` is called in `plan.py` for dataset identity/provenance reporting (FR-045) — if the current plan command logs or records dataset identity, it must obtain it from `adapter.metadata()` rather than from the raw experiment definition; update focused tests in `tests/test_cli.py` and `tests/test_lifecycle_no_network.py`

### Checkpoint

- [X] `pytest -k "plan or cli or runspec" -v` passes
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S5 — Executor boundary

**Goal**: `executor.py` calls `get_context` for inline strategies and `tool_provider()` for tool-mediated strategies; removes all Lattes-specific method calls; adds canonical trace metadata fields; error propagation verified.  
**Validation**: `pytest -k "execute or lifecycle_no_network" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(execute): wire executor through DatasetPackage adapter; remove Lattes-specific calls`

### Tasks

- [X] T021 [S5] Update `src/ctxbench/benchmark/executor.py`: import `get_default_registry` from `ctxbench.adapters.registry`; replace `DatasetProvider.from_dataset` setup with `adapter = get_default_registry().resolve(runspec.dataset)` where `runspec.dataset` is a `DatasetProvenance` accepted by S2 registry normalization; do not change strategy behavior yet in this task; add focused adapter-resolution tests in `tests/test_ai.py`
- [X] T022 [S5] Update inline execution in `src/ctxbench/benchmark/executor.py`: replace `get_context_artifact` / `get_context_artifact_path` / `get_instance_dir` usage with `adapter.get_context(runspec.instanceId, runspec.questionId, runspec.format)` for the `inline` strategy; pass `ContextPayload.content` to `AIRequest.context`; add focused tests in `tests/test_ai.py` proving `get_context` is called and unsupported representations propagate as run failures without fallback
- [X] T023 [S5] Update tool-mediated execution in `src/ctxbench/benchmark/executor.py`: import `CapabilityUnavailableError` from `ctxbench.dataset.errors`; for `local_function`, `local_mcp`, and `remote_mcp`, call `adapter.tool_provider()` before the model call and raise `CapabilityUnavailableError` if it returns `None`; for `local_function` and `local_mcp`, pass the returned provider/service into the existing local function or local MCP runtime factories; for `remote_mcp`, record the returned provider/service in the `AIRequest.metadata` under a generic key such as `"dataset_tool_provider"` for provider-native remote MCP adapters while preserving the existing provider-native remote MCP model path; do not call `get_context` as a fallback for any tool-mediated strategy; add focused tests in `tests/test_ai.py` for `local_function`, `local_mcp`, `remote_mcp`, and missing capability, proving `get_context()` is not called for tool-mediated strategies
- [X] T024 [S5] Update provider-native remote MCP tests in `tests/test_ai.py`: verify the `remote_mcp` execution path remains distinct from `local_mcp`, records `strategy.remote_mcp.execute`, includes the adapter-provided tool service in request metadata for provider-native remote MCP handling, and does not introduce inline context fallback or Lattes-specific file access
- [X] T025 [S5] Update executor request metadata in `src/ctxbench/benchmark/executor.py`: rename `lattes_id` → `instance_id`; add `"context_representation": runspec.format` and `"context_obtained": runspec.strategy == "inline"`; remove `"context_path"` and `"instance_dir"`; keep strategy fallback compatibility only where existing strategy code still reads `lattes_id`; add focused tests in `tests/test_ai.py` for metadata fields and absence of removed fields
- [X] T026 [S5] Add a focused executor/registry failure test in `tests/test_lifecycle_no_network.py` verifying that when `get_default_registry().resolve()` receives a `DatasetProvenance` or `ExperimentDataset` whose materialized path does not exist on disk, the run fails with `AdapterUnavailableError` or another explicit named adapter error — not a generic `FileNotFoundError` or unhandled exception; use a local mock adapter/registry fixture in this test file and no real provider calls

### Checkpoint

- [X] `pytest -k "execute or lifecycle_no_network" -v` passes
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S6 — Evaluation boundary

**Goal**: `evaluation.py` obtains evidence and oracle through the adapter; records oracle availability; oracle is never sent to LLM judges.  
**Validation**: `pytest -k "eval" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(eval): wire evaluation through get_evidence and get_oracle; record oracle trace fields`

### Tasks

- [X] T027 [S6] Update `src/ctxbench/benchmark/evaluation.py`: import `get_default_registry` from `ctxbench.adapters.registry`; replace provider-cache construction based on `DatasetProvider.from_dataset` with adapter-cache construction based on `get_default_registry().resolve(result.dataset)` where `result.dataset` is a `DatasetProvenance` accepted by S2 registry normalization; do not change judge prompt construction in this task; add focused adapter-resolution tests in `tests/test_ai.py`
- [X] T028 [S6] Update evidence handling in `src/ctxbench/benchmark/evaluation.py`: replace `get_question` / `get_context_blocks` calls with `adapter.get_evidence(result.instanceId, result.questionId)` → `EvidencePayload`; access judge evidence through `evidence_payload.evidence`; access task block IDs via `evidence_payload.task.get("context_blocks", []) if isinstance(evidence_payload.task, dict) else []` — guard required because `EvidencePayload.task` is typed `object`, not `dict`; add a focused test in `tests/test_ai.py` verifying `get_evidence` is called and `EvidencePayload.evidence` is passed to the judge prompt builder
- [X] T029 [S6] Update oracle handling in `src/ctxbench/benchmark/evaluation.py`: import `OracleUnavailable` from `ctxbench.dataset.payloads`; call `adapter.get_oracle(result.instanceId, result.questionId)` → `oracle_result`; derive `oracle_available = not isinstance(oracle_result, OracleUnavailable)`; ensure `oracle_result` is NOT passed to `build_evaluation_job`, `_judge_request`, or any judge prompt constructor; add focused tests in `tests/test_ai.py` for unavailable oracle, oracle availability recording, and oracle isolation from prompts
- [X] T030 [S6] Update evaluation trace metadata in `src/ctxbench/benchmark/evaluation.py`: add `"evidence_obtained": True`, `"oracle_available": oracle_available`, and `"oracle_used": False`; add focused tests in `tests/test_ai.py` proving evaluation proceeds with `ORACLE_UNAVAILABLE` and records `oracle_used` as `False`; use local mock adapters/registries in `tests/test_ai.py` — no real provider calls

### Checkpoint

- [X] `pytest -k "eval" -v` passes
- [X] no provider-backed execution
- [X] no opportunistic refactor
- [X] diff is reviewable
- [X] `worklog.md` updated

---

## Slice S7 — Lattes adapter conformance + provider-free tests

**Goal**: Validate that the `FakeDatasetAdapter` and the real Lattes adapter satisfy the v0 contract; registry resolves correctly; experiment fixtures are clean.  
**Validation**: `pytest -k "fake_dataset or registry or lattes_adapter" -v`  
**Depends on**: S3  
**Suggested commit**: `test(adapters): add fake adapter conformance tests and experiment fixture validation`

### Tasks

- [ ] T031 [S7] Create `tests/test_fake_dataset_adapter.py` with a `FakeDatasetAdapter` class implementing all mandatory v0 capabilities using hard-coded in-memory data; add tests: `FakeDatasetAdapter` satisfies `DatasetPackage` protocol (structural subtyping); `get_context` with unsupported representation raises `UnsupportedRepresentationError`; `get_oracle` returns `ORACLE_UNAVAILABLE` (not `None`); `get_task` returns `TaskPayload` with non-empty `statement`; `get_evidence` returns `EvidencePayload` with `role == "evidence"`
- [ ] T032 [S7] Create or update the canonical experiment definition fixture at `tests/fixtures/experiment.json`; it must contain `dataset.id`, `dataset.version`, `dataset.root`, and `factors.format` with realistic values for a Lattes experiment — no adapter class names, no module paths, no Lattes-specific filenames; this fixture is used by T034
- [ ] T033 [P] [S7] Add registry integration tests to `tests/test_dataset_adapter_registry.py` (extending the file created in T006): `get_default_registry().resolve(ExperimentDataset(id="ctxbench/lattes", ...))` returns a `LattesDatasetAdapter` instance; `get_default_registry().resolve(DatasetProvenance(id="ctxbench/lattes", ..., materialized_path=...))` returns a `LattesDatasetAdapter` instance; `get_default_registry().resolve(ExperimentDataset(id="ctxbench/unknown", ...))` raises `AdapterUnavailableError`; `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` is `True`
- [ ] T034 [S7] Add experiment definition fixture test in `tests/test_experiment_fixtures.py`: load `tests/fixtures/experiment.json`; assert it contains no adapter class name, no Python module path, no Lattes-specific filename (e.g. `clean.html`, `parsed.json`); assert `factors.format` values (if present) are plain strings; assert `dataset.id` is present and is a string matching a registered id (e.g. `"ctxbench/lattes"`)

### Checkpoint

- [ ] `pytest -k "fake_dataset or registry or lattes_adapter" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S8 — Architecture docs + artifact-only command validation

**Goal**: Architecture documentation reflects the new adapter boundary; `export` and `status` are validated as artifact-only under dataset-unavailable conditions.  
**Validation**: `pytest -k "export or status" -v`  
**Depends on**: S5, S6  
**Suggested commit**: `docs(architecture): update adapter boundary, vocabulary, workflow, and artifact contracts`

### Tasks

- [ ] T035 [S8] Update `docs/architecture/container.md`: add Adapter Registry v0 as the composition point between the benchmark core and dataset adapters; show `ctxbench.adapters.registry` as the only lifecycle module that imports concrete adapter classes
- [ ] T036 [P] [S8] Update `docs/architecture/component.md`: show `ctxbench.dataset` as generic contracts layer; `ctxbench.adapters.registry` as first-party wiring; `ctxbench.adapters.lattes` as a concrete first-party adapter; draw the dependency direction (core → dataset ← adapters)
- [ ] T037 [P] [S8] Update `docs/architecture/vocabulary.md`: define `format` as "context representation request passed unmodified to the adapter as the `representation` parameter of `get_context`"; explicitly state it is not a physical filename or file format
- [ ] T038 [P] [S8] Update `docs/architecture/workflow.md`: clarify that adapter resolution occurs once per run before any lifecycle phase consumes the dataset; clarify that `export` and `status` are artifact-only and succeed when the dataset is not materialized
- [ ] T039 [S8] Update `docs/architecture/artifact-contracts.md`: document additions to executor trace metadata (`context_representation`, `context_obtained`); document removals (`context_path`, `instance_dir`); document additions to evaluation trace metadata (`evidence_obtained`, `oracle_available`, `oracle_used`); record that `lattes_id` → `instance_id` rename is backward-compatible via strategy fallback
- [ ] T040 [S8] Add or update shared artifact-only fixtures in `tests/fixtures/artifact_only_unavailable_dataset/` proving lifecycle commands can operate from existing run artifacts when `dataset.root` is absent or not materialized; first check for existing run artifact stubs (responses.jsonl, evals.jsonl, or equivalent); if none exist, create minimal stubs — e.g. empty JSONL files or single-row JSONL stubs — sufficient for export/status tests; the dataset reference in the fixture must point to a nonexistent path; do not call real providers
- [ ] T041 [S8] Add or update tests in `tests/test_lifecycle_no_network.py` proving `ctxbench export` operates from the T040 artifacts when the dataset is unavailable; verify the command exits 0 and uses only artifact data; do not call real providers
- [ ] T042 [S8] Add or update tests in `tests/test_lifecycle_no_network.py` proving `ctxbench status` operates from the T040 artifacts when the dataset is unavailable; verify the command exits 0 and produces expected output using only artifact data; do not call real providers

### Checkpoint

- [ ] `pytest -k "export or status" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Final Audit

- [ ] T043 [Audit] Run full focused validation suite: `pytest tests/ -x --ignore=tests/fixtures` — all slices green, no provider calls
- [ ] T044 [Audit] Verify import boundary with `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"` — exits 0
- [ ] T045 [Audit] Update `specs/004-dataset-package-capabilities/worklog.md` with final slice completions, deviations from plan, and lessons learned
- [ ] T046 [Audit] Update `specs/004-dataset-package-capabilities/usage.jsonl` — record token usage as `unavailable` if API usage data was not captured during implementation
- [ ] T047 [Audit] Inspect lifecycle imports after S4-S6 and update `src/ctxbench/dataset/provider.py` only if needed: if `DatasetProvider.from_dataset` becomes dead code for lifecycle phases, add `# deprecated: no longer called by lifecycle phases; retained for Spec 004 migration safety` without removing it; if it remains used by non-lifecycle utilities, record that explicitly in `worklog.md`; do not remove `DatasetProvider.from_dataset` in Spec 004
- [ ] T048 [Audit] Record follow-ups: confirm `context_path` / `instance_dir` removal has no downstream analysis script dependency; confirm `lattes_id` → `instance_id` rename is backward-compatible; note Spec 006 deferred items; record decision on `DatasetProvider.from_dataset` — if it remains deprecated-internal after this spec, schedule its removal in Spec 006 alongside the Lattes adapter relocation

---

## Dependencies and Execution Order

```
S1
└── S2
    └── S3
        ├── S4  (independent of S5, S6, S7 once S3 is green)
        ├── S5  (independent of S4, S6, S7 once S3 is green)
        ├── S6  (independent of S4, S5, S7 once S3 is green)
        ├── S7  (independent of S4, S5, S6 once S3 is green)
        └── S8  (depends on S5 and S6 trace decisions; does not depend on S7 unless reusing S7 fixtures)
            └── Final Audit
```

- S4, S5, S6, S7 may be implemented in any order once S3 is green.
- S8 should wait until trace metadata changes in S5 and S6 are known; S8 may reuse S7 fixtures but must not depend on S7 unless that reuse is explicit in the implementation.
- Final Audit depends on all slices being complete.

## Provider and Cost Controls

- Do not run real provider-backed `ctxbench execute` or `ctxbench eval`.
- All tests must use fixtures, mocks, or existing local artifacts.
- No API keys, provider tokens, or network access required at any checkpoint.
- Quickstart and experiment fixture tests must use the canonical `tests/fixtures/experiment.json` fixture or equivalent.
