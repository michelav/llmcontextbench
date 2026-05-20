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

- [ ] T001 [S1] Create `src/ctxbench/dataset/payloads.py` with `ContextPayload`, `EvidencePayload`, `TaskPayload` dataclasses and `OracleUnavailable` sentinel class + `ORACLE_UNAVAILABLE` singleton exactly as specified in `plan.md` § Payload Types
- [ ] T002 [P] [S1] Create `src/ctxbench/dataset/errors.py` with `AdapterUnavailableError(ValueError)`, `CapabilityUnavailableError(ValueError)`, `UnsupportedRepresentationError(ValueError)` as specified in `plan.md` § Slice S1
- [ ] T003 [S1] Create `tests/test_dataset_payloads.py` with tests: error types are `ValueError` subclasses; `ORACLE_UNAVAILABLE is not None`; `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` is `True`; `ContextPayload.role == "context"`; `EvidencePayload.role == "evidence"`; `TaskPayload.statement` exists

### Checkpoint

- [ ] `pytest -k "payloads or adapter_errors" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S2 — `DatasetPackage` protocol + `AdapterRegistry` + `ResolvedDatasetRef`

**Goal**: Define the generic contract surface and registry skeleton that lifecycle phases will import.  
**Validation**: `pytest -k "dataset_package_contract or registry" -v`  
**Depends on**: S1  
**Suggested commit**: `feat(dataset): add DatasetPackage protocol, AdapterRegistry, and ResolvedDatasetRef`

### Tasks

- [ ] T004 [S2] Update `src/ctxbench/dataset/package.py`: import `TaskPayload`, `ContextPayload`, `EvidencePayload` from `payloads.py`; add mandatory protocol methods `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`; add optional methods `get_oracle`, `get_task_instance`, `tool_provider`, `fixtures` with default implementations as specified in `plan.md` § DatasetPackage Protocol; keep existing `list_instance_ids`, `list_task_ids`, `identity`, `version`, `origin`, `metadata`, `capability_report`; **remove `get_context_artifact` and `get_evidence_artifact` from the `Protocol` definition** — they may remain as private implementation methods in `LocalDatasetPackage` but are not part of the v0 contract surface
- [ ] T005 [P] [S2] Create `src/ctxbench/dataset/registry.py` with `ResolvedDatasetRef` (dataclass with `id`, `version`, `root`, `origin`, `content_hash`, `materialized_path`), `Factory` type alias, and `AdapterRegistry` class with `register(dataset_id, factory)` and `resolve(dataset_ref: ExperimentDataset) → DatasetPackage` methods; `resolve` raises `AdapterUnavailableError` if `dataset_ref.id` is unregistered or `None`; no default registry instance; no import of `ctxbench.adapters`
- [ ] T006 [S2] Create `tests/test_dataset_adapter_registry.py` with tests: `AdapterRegistry.resolve` raises `AdapterUnavailableError` for unknown id; `AdapterRegistry.resolve` returns the adapter produced by a registered factory; `AdapterRegistry.register` is callable with a factory; `ResolvedDatasetRef` is constructable with required fields — **note: this file will be extended in T025 (S7) with Lattes integration tests; treat T006 as the initial population only**

### Checkpoint

- [ ] `pytest -k "dataset_package_contract or registry" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S3 — Package namespace: move Lattes, wire adapters registry, import-boundary tests

**Goal**: Move `ctxbench.datasets.lattes` to `ctxbench.adapters.lattes`; expose all v0 methods on `LattesDatasetAdapter`; wire `ctxbench.adapters.registry`; enforce import boundaries.  
**Validation**: `pytest -k "import_boundary or lattes_dataset or lattes_adapter" -v` and `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"`  
**Depends on**: S2  
**Suggested commit**: `refactor(adapters): move Lattes to ctxbench.adapters, wire registry, enforce import boundaries`

### Tasks

- [ ] T007 [S3] Create `src/ctxbench/adapters/__init__.py` as an empty package marker
- [ ] T008 [S3] Copy the entire `src/ctxbench/datasets/lattes/` tree to `src/ctxbench/adapters/lattes/` (including `readers/` subdirectory and all existing modules: `__init__.py`, `package.py`, `tools.py`, `mcp_server.py`, `models.py`, `provider.py`, `readers/`)
- [ ] T009 [S3] Update all internal imports in `src/ctxbench/adapters/lattes/` tree: replace every `ctxbench.datasets.lattes.*` import with `ctxbench.adapters.lattes.*`
- [ ] T010 [S3] Rename class `LattesDatasetPackage` → `LattesDatasetAdapter` in `src/ctxbench/adapters/lattes/package.py`; update all internal references within the file and within the `adapters/lattes/` tree
- [ ] T011 [S3] Add `FORMAT_ARTIFACTS` dict to `src/ctxbench/adapters/lattes/package.py` (moved from `ctxbench.dataset.provider`); add `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`, `get_task_instance(instance_id, task_id) → dict | None`, `get_oracle(instance_id, task_id) → OracleUnavailable` to `LattesDatasetAdapter` using the exact logic from `plan.md` § Slice S3
- [ ] T012 [P] [S3] Create `src/ctxbench/adapters/registry.py` with a private `_registry = AdapterRegistry()`, registration of `"ctxbench/lattes"` → `LattesDatasetAdapter` factory, and `get_default_registry() → AdapterRegistry` function; only this module may import `LattesDatasetAdapter`
- [ ] T013 [S3] Remove `FORMAT_ARTIFACTS` dict and `_specialized_local_dataset_package` function from `src/ctxbench/dataset/provider.py`; check whether `DatasetProvider.from_dataset` is still called by any lifecycle code after S3–S6 — if it becomes dead code, add a `# deprecated: no longer called by lifecycle phases; retained for Spec 004 migration safety` comment without removing it (removal deferred to Spec 006); do not remove it silently
- [ ] T014 [S3] Add `get_task(task_id) → TaskPayload`, `get_context(instance_id, task_id, representation) → ContextPayload`, `get_evidence(instance_id, task_id) → EvidencePayload`, `get_task_instance(instance_id, task_id) → dict | None`, and `get_oracle(instance_id, task_id) → OracleUnavailable` (returning `ORACLE_UNAVAILABLE`) to `LocalDatasetPackage` in `src/ctxbench/dataset/provider.py` using existing internal methods (`get_question`, `get_context_artifact`, etc.) as the backing implementation — `get_oracle` must be explicitly defined because Python `Protocol` default method bodies are not inherited by concrete implementors
- [ ] T015 [P] [S3] Empty all `.py` implementation files in `src/ctxbench/datasets/lattes/` (including `tools.py`, `models.py`, `mcp_server.py`, `provider.py`, and any `readers/` modules); replace `src/ctxbench/datasets/lattes/__init__.py` with a stub that re-exports `LattesDatasetAdapter` from `ctxbench.adapters.lattes` for backward compatibility; similarly stub `readers/__init__.py` if needed; do not delete the directory or its `__init__.py` files — leave them as redirect stubs only
- [ ] T016 [S3] Create `tests/test_import_boundaries.py` with tests that: (a) no module in `ctxbench.benchmark.*` imports `ctxbench.adapters.lattes` directly; (b) no module in `ctxbench.dataset.*` imports `ctxbench.adapters`; (c) no module in `ctxbench.commands.*` imports `ctxbench.adapters.lattes` directly

### Checkpoint

- [ ] `pytest -k "import_boundary or lattes_dataset or lattes_adapter" -v` passes
- [ ] `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"` exits 0
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S4 — Planning through adapter contract

**Goal**: `runspec_generator.py` and `commands/plan.py` consume the dataset only through the `DatasetPackage` protocol; no `LocalDatasetPackage` import in lifecycle code.  
**Validation**: `pytest -k "plan or cli or runspec" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(plan): thread planning through DatasetPackage adapter contract`

### Tasks

- [ ] T017 [S4] Update `src/ctxbench/benchmark/runspec_generator.py`: change type annotation of dataset parameter to `DatasetPackage`; replace `list_question_ids()` → `list_task_ids()`; replace `get_question(id)` → `get_task(id)` and update all field references (`question.question` → `task.statement`, `question.contextBlock` → `task.context_blocks`, `question.tags` → `task.tags`, `question.validation.type` → `task.validation_type`); replace `get_question_instance(id, inst)` → `get_task_instance(inst, id)` and update parameter access (`qi.parameters` → `task_inst.get("parameters", {}) if task_inst else {}`); remove `from ctxbench.dataset.provider import LocalDatasetPackage`
- [ ] T018 [S4] Update `src/ctxbench/commands/plan.py`: after `DatasetResolver.resolve()`, call `get_default_registry().resolve(experiment.dataset)` — where `experiment.dataset` is the `ExperimentDataset` object — to obtain the adapter (the registry builds `ResolvedDatasetRef` internally); remove any `isinstance(package, LocalDatasetPackage)` branch; import `get_default_registry` from `ctxbench.adapters.registry`; pass the adapter (not the provider/package) to `generate_runspecs(experiment, base_dir, adapter, ...)`; verify that `adapter.metadata()` is called in `plan.py` for dataset identity/provenance reporting (FR-045) — if the current plan command logs or records dataset identity, it must obtain it from `adapter.metadata()` rather than from the raw experiment definition

### Checkpoint

- [ ] `pytest -k "plan or cli or runspec" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S5 — Executor boundary

**Goal**: `executor.py` calls `get_context` for inline strategies and `tool_provider()` for tool-mediated strategies; removes all Lattes-specific method calls; adds canonical trace metadata fields; error propagation verified.  
**Validation**: `pytest -k "execute or lifecycle_no_network" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(execute): wire executor through DatasetPackage adapter; remove Lattes-specific calls`

### Tasks

- [ ] T019 [S5] Update `src/ctxbench/benchmark/executor.py`: import `get_default_registry` from `ctxbench.adapters.registry` and `CapabilityUnavailableError` from `ctxbench.dataset.errors`; replace `DatasetProvider.from_dataset` / `get_context_artifact` / `get_context_artifact_path` / `get_instance_dir` calls with `adapter = get_default_registry().resolve(runspec.dataset)` followed by `adapter.get_context(runspec.instanceId, runspec.questionId, runspec.format)` for inline strategies; for tool-mediated strategies (`local_function`, `local_mcp`, `remote_mcp`), call `adapter.tool_provider()` and raise `CapabilityUnavailableError` if it returns `None`; rename `lattes_id` → `instance_id` in metadata; add `"context_representation": runspec.format` and `"context_obtained": runspec.strategy == "inline"` to trace metadata; remove `"context_path"` and `"instance_dir"` from trace metadata
- [ ] T020 [S5] Create or update executor tests: add a test using a mock adapter that verifies `get_context` is called for the `inline` strategy and its `content` is passed to `AIRequest.context`; add a test verifying `tool_provider()` is called for `local_function` and `local_mcp` strategies; add a test verifying `CapabilityUnavailableError` is raised when `tool_provider()` returns `None`; add a test verifying that an `UnsupportedRepresentationError` raised by `adapter.get_context()` propagates as a run failure (i.e., is not caught and silently swallowed by the executor); add a test verifying that when `get_default_registry().resolve()` is called with an `ExperimentDataset` whose materialized path does not exist on disk, the run fails with `AdapterUnavailableError` or an explicit named error — not a generic `FileNotFoundError` or unhandled exception (FR-049b); use a mock or `FakeDatasetAdapter` — no real provider calls

### Checkpoint

- [ ] `pytest -k "execute or lifecycle_no_network" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S6 — Evaluation boundary

**Goal**: `evaluation.py` obtains evidence and oracle through the adapter; records oracle availability; oracle is never sent to LLM judges.  
**Validation**: `pytest -k "eval" -v`  
**Depends on**: S3  
**Suggested commit**: `feat(eval): wire evaluation through get_evidence and get_oracle; record oracle trace fields`

### Tasks

- [ ] T021 [S6] Update `src/ctxbench/benchmark/evaluation.py`: import `get_default_registry` from `ctxbench.adapters.registry` and `OracleUnavailable` from `ctxbench.dataset.payloads`; replace `DatasetProvider.from_dataset` / `get_question` / `get_context_blocks` calls with `adapter = get_default_registry().resolve(result.dataset)`; call `adapter.get_evidence(result.instanceId, result.questionId)` → `EvidencePayload`; call `adapter.get_oracle(result.instanceId, result.questionId)` → `oracle_result`; derive `oracle_available = not isinstance(oracle_result, OracleUnavailable)`; access evidence via `evidence_payload.evidence`; access task block IDs via `evidence_payload.task.get("context_blocks", []) if isinstance(evidence_payload.task, dict) else []` — guard required because `EvidencePayload.task` is typed `object`, not `dict`, and `.get()` without a guard will raise `AttributeError` at runtime if the adapter returns a non-dict task value (see plan.md §Slice S6); add `"evidence_obtained": True`, `"oracle_available": oracle_available`, `"oracle_used": False` to the evaluation trace; ensure `oracle_result` is NOT passed to `build_evaluation_job` or any judge prompt constructor
- [ ] T022 [S6] Create or update evaluation tests: add a test using a mock adapter verifying `get_evidence` is called and `EvidencePayload.evidence` is passed to the judge prompt builder; add a test verifying `get_oracle` is called and `oracle_available` is recorded in the evaluation trace; add a test verifying that when `get_oracle` returns `ORACLE_UNAVAILABLE`, evaluation still proceeds using evidence only and `oracle_used` is `False`; add a test verifying `oracle_result` is never passed to `build_evaluation_job`; use a mock or `FakeDatasetAdapter` — no real provider calls

### Checkpoint

- [ ] `pytest -k "eval" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Slice S7 — Lattes adapter conformance + provider-free tests

**Goal**: Validate that the `FakeDatasetAdapter` and the real Lattes adapter satisfy the v0 contract; registry resolves correctly; experiment fixtures are clean.  
**Validation**: `pytest -k "fake_dataset or registry or lattes_adapter" -v`  
**Depends on**: S3  
**Suggested commit**: `test(adapters): add fake adapter conformance tests and experiment fixture validation`

### Tasks

- [ ] T023 [S7] Create `tests/test_fake_dataset_adapter.py` with a `FakeDatasetAdapter` class implementing all mandatory v0 capabilities using hard-coded in-memory data; add tests: `FakeDatasetAdapter` satisfies `DatasetPackage` protocol (structural subtyping); `get_context` with unsupported representation raises `UnsupportedRepresentationError`; `get_oracle` returns `ORACLE_UNAVAILABLE` (not `None`); `get_task` returns `TaskPayload` with non-empty `statement`; `get_evidence` returns `EvidencePayload` with `role == "evidence"`
- [ ] T024 [P] [S7] Locate the canonical experiment definition fixture used by tests (search `tests/fixtures/` and `tests/` for any `experiment.json` or equivalent); if it exists, verify it is usable by T026; if it does not exist, create a minimal `tests/fixtures/experiment.json` containing `dataset.id`, `dataset.version`, `dataset.root`, and `factors.format` with realistic values for a Lattes experiment — no adapter class names, no module paths, no Lattes-specific filenames
- [ ] T025 [P] [S7] Add registry integration tests to `tests/test_dataset_adapter_registry.py` (extending the file created in T006): `get_default_registry().resolve(ExperimentDataset(id="ctxbench/lattes", ...))` returns a `LattesDatasetAdapter` instance; `get_default_registry().resolve(ExperimentDataset(id="ctxbench/unknown", ...))` raises `AdapterUnavailableError`; `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` is `True`
- [ ] T026 [S7] Add experiment definition fixture test in `tests/test_fake_dataset_adapter.py` (or a new `tests/test_experiment_fixtures.py`): load the fixture from T024 (`tests/fixtures/experiment.json` or equivalent); assert it contains no adapter class name, no Python module path, no Lattes-specific filename (e.g. `clean.html`, `parsed.json`); assert `factors.format` values (if present) are plain strings; assert `dataset.id` is present and is a string matching a registered id (e.g. `"ctxbench/lattes"`)

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

- [ ] T027 [S8] Update `docs/architecture/container.md`: add Adapter Registry v0 as the composition point between the benchmark core and dataset adapters; show `ctxbench.adapters.registry` as the only lifecycle module that imports concrete adapter classes
- [ ] T028 [P] [S8] Update `docs/architecture/component.md`: show `ctxbench.dataset` as generic contracts layer; `ctxbench.adapters.registry` as first-party wiring; `ctxbench.adapters.lattes` as a concrete first-party adapter; draw the dependency direction (core → dataset ← adapters)
- [ ] T029 [P] [S8] Update `docs/architecture/vocabulary.md`: define `format` as "context representation request passed unmodified to the adapter as the `representation` parameter of `get_context`"; explicitly state it is not a physical filename or file format
- [ ] T030 [P] [S8] Update `docs/architecture/workflow.md`: clarify that adapter resolution occurs once per run before any lifecycle phase consumes the dataset; clarify that `export` and `status` are artifact-only and succeed when the dataset is not materialized
- [ ] T031 [S8] Update `docs/architecture/artifact-contracts.md`: document additions to executor trace metadata (`context_representation`, `context_obtained`); document removals (`context_path`, `instance_dir`); document additions to evaluation trace metadata (`evidence_obtained`, `oracle_available`, `oracle_used`); record that `lattes_id` → `instance_id` rename is backward-compatible via strategy fallback
- [ ] T032 [P] [S8] Add or update tests in `tests/` proving `ctxbench export` operates from existing run artifacts when the `dataset.root` path is absent or not materialized: first check `tests/fixtures/` for existing run artifact stubs (responses.jsonl, evals.jsonl, or equivalent); if none exist, create minimal stubs — e.g. empty JSONL files or single-row JSONL stubs — sufficient for the export command to run; the dataset reference in the fixture must point to a nonexistent path to verify dataset-free operation; do not call real providers
- [ ] T033 [P] [S8] Add or update tests in `tests/` proving `ctxbench status` operates from existing run artifacts when the `dataset.root` path is absent or not materialized: reuse the stubs created in T032 (or create equivalents); verify the command exits 0 and produces expected output using only artifact data; the dataset reference must point to a nonexistent path; do not call real providers

### Checkpoint

- [ ] `pytest -k "export or status" -v` passes
- [ ] no provider-backed execution
- [ ] no opportunistic refactor
- [ ] diff is reviewable
- [ ] `worklog.md` updated

---

## Final Audit

- [ ] T034 [Audit] Run full focused validation suite: `pytest tests/ -x --ignore=tests/fixtures` — all slices green, no provider calls
- [ ] T035 [Audit] Verify import boundary with `python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"` — exits 0
- [ ] T036 [Audit] Update `specs/004-dataset-package-capabilities/worklog.md` with final slice completions, deviations from plan, and lessons learned
- [ ] T037 [Audit] Update `specs/004-dataset-package-capabilities/usage.jsonl` — record token usage as `unavailable` if API usage data was not captured during implementation
- [ ] T038 [Audit] Record follow-ups: confirm `context_path` / `instance_dir` removal has no downstream analysis script dependency; confirm `lattes_id` → `instance_id` rename is backward-compatible; note Spec 006 deferred items; record decision on `DatasetProvider.from_dataset` — if it remains deprecated-internal after this spec, schedule its removal in Spec 006 alongside the Lattes adapter relocation

---

## Dependencies and Execution Order

```
S1
└── S2
    └── S3
        ├── S4  (independent of S5, S6, S7 once S3 is green)
        ├── S5  (independent of S4, S6, S7 once S3 is green)
        ├── S6  (independent of S4, S5, S7 once S3 is green)
        └── S7  (independent of S4, S5, S6 once S3 is green)
            └── S8 (depends on S5 and S6 trace decisions)
                └── Final Audit
```

- S4, S5, S6, S7 may be implemented in any order once S3 is green.
- S8 should wait until trace metadata changes in S5 and S6 are known.
- Final Audit depends on all slices being complete.

## Provider and Cost Controls

- Do not run real provider-backed `ctxbench execute` or `ctxbench eval`.
- All tests must use fixtures, mocks, or existing local artifacts.
- No API keys, provider tokens, or network access required at any checkpoint.
- Quickstart and experiment fixture tests must use the canonical `tests/fixtures/experiment.json` fixture or equivalent.
