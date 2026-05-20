# Plan: Dataset Package Capabilities and Core/Adapter Boundary

**Branch**: `feat/dataset-boundaries-capabilities` | **Date**: 2026-05-20 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/004-dataset-package-capabilities/spec.md`

---

## Summary

Introduce the Adapter Registry v0 and the Dataset Package Capabilities v0 contract. Establish two sibling packages — `ctxbench.dataset` for generic contracts and `ctxbench.adapters` for concrete first-party adapters — with strict import boundaries. Move `ctxbench.datasets.lattes` to `ctxbench.adapters.lattes`. Define payload types (`ContextPayload`, `EvidencePayload`, `TaskPayload`) and error types. Rename `get_context_artifact` → `get_context` and `get_evidence_artifact` → `get_evidence`. Thread all lifecycle phases through the adapter contract. Fix `runspec_generator.py` to use the `DatasetPackage` protocol rather than `LocalDatasetPackage` directly. Move the Lattes-specific `FORMAT_ARTIFACTS` table out of the core.

---

## Decisions

1. Canonical method names: `get_context`, `get_evidence`, `get_oracle`, `get_task`, `get_task_instance`.
2. `get_context_artifact` and `get_evidence_artifact` may exist as **temporary internal wrappers** inside existing implementations during migration, but are not part of the v0 contract surface.
3. Payload types live in `ctxbench.dataset.payloads`: `ContextPayload`, `EvidencePayload`, `TaskPayload`, `OracleUnavailable`, `ORACLE_UNAVAILABLE`.
4. Error types live in `ctxbench.dataset.errors`: `AdapterUnavailableError`, `CapabilityUnavailableError`, `UnsupportedRepresentationError`.
5. `AdapterRegistry` lives in `ctxbench.dataset.registry`. It defines the generic class and `ResolvedDatasetRef`. It imports **nothing** from `ctxbench.adapters`.
6. First-party registry wiring lives in `ctxbench.adapters.registry`. It imports `LattesDatasetAdapter` and registers it.
7. Generic lifecycle code (`benchmark/`, `commands/`) imports from `ctxbench.dataset.*` and `ctxbench.adapters.registry`. It MUST NOT import from `ctxbench.adapters.lattes` directly.
8. `ctxbench.datasets.lattes` is moved to `ctxbench.adapters.lattes` in Spec 004.
9. `FORMAT_ARTIFACTS` moves from `ctxbench.dataset.provider` to the Lattes adapter.
10. `runspec_generator.py` is updated to accept `DatasetPackage` protocol (not `LocalDatasetPackage`). Per-instance parameters are retrieved via optional `get_task_instance(instance_id, task_id)`.
11. `evaluation.py` uses `get_evidence` which returns `EvidencePayload`. It no longer reads Lattes-specific keys (`contextBlocks`, `get_context_blocks`).
12. `executor.py` calls `get_context` for inline strategies; uses `tool_provider()` for tool-mediated strategies. It does not call `get_context` for tool-mediated strategies.
13. Oracle is queried by `eval` when the adapter supports it. Oracle is never automatically sent to LLM judges; it is used only by oracle-configured evaluators.
14. Registry factory receives `ResolvedDatasetRef` (not a bare root string).
15. `lattes_id` metadata field in executor renamed to `instance_id`.

---

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: pyproject.toml, flake.nix  
**Storage**: local JSON/JSONL artifacts only  
**Testing**: pytest, provider-free fixtures/mocks  
**Target Platform**: CLI  
**Project Type**: single Python CLI project  
**Constraints**: provider-free validation; no full benchmark unless explicitly approved  
**Scale/Scope**: large — 3 new packages, 3 new modules, ~10 files modified, ~500 lines of net change (mostly moves and renames)

---

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| Phase separation | pass | Registry resolves once per run; each phase uses only the adapter capabilities it is responsible for |
| Cost/evaluation separation | pass | No cost-tracking changes |
| Metric provenance | pass | No metric changes |
| Artifact contracts | pass | Artifact schemas unchanged; `dataset` provenance fields unchanged; `trials.jsonl` and `responses.jsonl` unaffected |
| Strategy comparability | pass | `get_context` replaces internal Lattes-specific reads; strategy semantics unchanged |
| Dataset/domain isolation | **core purpose** | This spec enforces the boundary |
| Provider isolation | pass | No AI provider adapter changes |
| Provider-free validation | pass | `FakeDatasetAdapter` fixture validates the full v0 contract without real data |
| Documentation impact | pass | CLAUDE.md active-plan pointer updated; no CLI help or README changes required |
| Simplicity / research sufficiency | pass | Registry is a dict; payload types are dataclasses; no plugin machinery; no new abstraction layers beyond what the spec requires |

---

## Capability Selection Rules

The dataset adapter provides capabilities. It does not decide which capability is used. The benchmark core, strategy, and evaluation engine decide.

| Consumer | Condition | Capability called |
|---|---|---|
| `plan` | always | `metadata`, `list_instance_ids`, `list_task_ids`, `get_task`, `get_task_instance` (optional) |
| `execute` | inline strategies | `get_context` |
| `execute` | tool-mediated strategies (`local_function`, `local_mcp`, remote MCP) | `tool_provider` |
| `execute` | all strategies | `get_task` when the strategy needs task text before calling the model |
| `eval` | judge-based evaluation | `get_evidence` |
| `eval` | deterministic / schema / heuristic evaluation | `get_oracle` when available |
| `eval` | all modes | record oracle availability when queried |
| `export` | always | no dataset capability; artifact-only |
| `status` | always | no dataset capability; artifact-only |

**Important**: Tool-mediated strategies (`local_function`, `local_mcp`) obtain context through `tool_provider()`, not through `get_context`. The benchmark MUST NOT call `get_context` as a fallback to get Lattes files for tool-mediated strategies. Context access and tool access are distinct capabilities. If a tool-mediated strategy explicitly needs model-facing context in addition to tools, it is responsible for calling `get_context` via the adapter explicitly, not as a hidden fallback.

---

## Package Namespaces and Layering

### Target Layout

```
src/ctxbench/
  dataset/
    __init__.py
    package.py          # DatasetPackage protocol; ResolvedDatasetRef (or imported from registry)
    payloads.py         # ContextPayload, EvidencePayload, TaskPayload, OracleUnavailable, ORACLE_UNAVAILABLE
    errors.py           # AdapterUnavailableError, CapabilityUnavailableError, UnsupportedRepresentationError
    registry.py         # AdapterRegistry class; ResolvedDatasetRef; no concrete adapter imports
    capabilities.py     # DatasetCapabilityReport (existing, keep)
    resolver.py         # DatasetResolver (Spec 003 local-file resolution, keep)
    provider.py         # LocalDatasetPackage (generic fallback, simplified)

  adapters/
    __init__.py
    registry.py         # first-party wiring: register("ctxbench/lattes", LattesDatasetAdapter)
    lattes/
      __init__.py
      package.py        # LattesDatasetAdapter (renamed from LattesDatasetPackage)
      tools.py
      mcp_server.py
      models.py
      provider.py       # LattesToolService (existing, kept in adapter)
      readers/
        __init__.py
        base.py
        html_reader.py
        json_reader.py
```

### Dependency Direction

```
ctxbench.dataset        ← ctxbench.adapters.<domain>
ctxbench.benchmark      → ctxbench.dataset
ctxbench.commands       → ctxbench.dataset
composition root        → ctxbench.adapters.registry
```

### Layering Rules (enforced by import-boundary tests)

- `ctxbench.dataset` MUST NOT import from `ctxbench.adapters`.
- `ctxbench.benchmark` MUST NOT import from `ctxbench.adapters.lattes` directly.
- `ctxbench.commands` MUST NOT import from `ctxbench.adapters.lattes` directly.
- `ctxbench.adapters.lattes` MAY import from `ctxbench.dataset.*`.
- `ctxbench.adapters.registry` imports `LattesDatasetAdapter` and is the ONLY non-adapter module allowed to import concrete adapters.
- New code MUST NOT be added under `ctxbench.datasets` (the old plural package). It is frozen pending cleanup.

### Migration from `ctxbench.datasets`

`ctxbench.datasets.lattes` is moved to `ctxbench.adapters.lattes` in Spec 004:
- All files are moved; module paths update.
- `LattesDatasetPackage` is renamed to `LattesDatasetAdapter`.
- Internal cross-imports within the lattes package update to `ctxbench.adapters.lattes.*`.
- The sole external caller (`ctxbench.dataset.provider._specialized_local_dataset_package`) is removed as part of registry cleanup; the import chain is broken.
- `ctxbench.datasets/__init__.py` remains but is emptied (existing code may still import from it; no new code is added).

---

## Payload Types

All payload types live in `src/ctxbench/dataset/payloads.py`.

### `ContextPayload`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ContextPayload:
    role: Literal["context"]
    representation: str
    content: object
    content_type: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

- `representation`: the representation string passed by the experiment (`factors.format`).
- `content`: the model-facing context payload. In v0, MUST be a string for all representations consumed by inline strategies. Non-string content is reserved for future payload subtypes.
- `content_type`: MIME hint (e.g. `"text/html"`, `"application/json"`). Optional.
- `metadata`: adapter-internal trace information. Not consumed by the core.

**Semantics**:
- The core MUST NOT know whether `content` came from `clean.html`, `parsed.json`, an API response, or a generated object.
- For Lattes `html`: `content` = cleaned HTML string, `content_type` = `"text/html"`.
- For Lattes `json`: `content` = JSON-serialized string, `content_type` = `"application/json"`.
- If a future strategy needs file-backed context, it should be represented in `metadata` or via a future payload subtype. File-backed context machinery is out of scope for Spec 004.
- The executor passes `context_payload.content` to `AIRequest.context`.

### `EvidencePayload`

```python
@dataclass
class EvidencePayload:
    role: Literal["evidence"]
    task: object
    evidence: object
    task_instance: object | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

- `task`: the task description (adapter-defined structure). For Lattes: a dict with fields `id`, `statement`, `tags`, `validation_type`, `context_blocks`.
- `evidence`: the evaluator-facing evidence payload (adapter-defined). For Lattes: a dict of named context blocks used by the judge.
- `task_instance`: optional instance-specific task data (adapter-defined).
- `metadata`: trace metadata.

**Semantics**:
- `contextBlocks` is NOT a key in the generic contract. It may remain an internal Lattes detail inside the Lattes adapter.
- The generic evaluator accesses `payload.evidence` to build the judge prompt. It does not access `payload.task["contextBlocks"]` directly.
- For Lattes, the adapter populates `evidence` with the context blocks needed by the judge (previously `get_context_blocks`), under generic keys.

### `TaskPayload`

```python
@dataclass
class TaskPayload:
    task_id: str
    statement: str
    tags: list[str] = field(default_factory=list)
    validation_type: str = "judge"
    context_blocks: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
```

- `statement`: the question template string (may contain `{placeholder}` variables).
- `context_blocks`: list of block IDs used by this task (generic; Lattes-specific blocks stay in the adapter).
- `validation_type`: `"judge"` or other evaluation mode.
- Template rendering (substituting placeholders from `get_task_instance`) remains in `runspec_generator.py`.

### `OracleUnavailable` (sentinel)

```python
class OracleUnavailable:
    """Distinct sentinel returned when no oracle is available."""

ORACLE_UNAVAILABLE = OracleUnavailable()
```

Not `None`, not empty dict. Check with `isinstance(result, OracleUnavailable)`.

---

## `DatasetPackage` Protocol (revised)

`src/ctxbench/dataset/package.py`

### Mandatory capabilities

```python
class DatasetPackage(Protocol):
    def metadata(self) -> DatasetMetadata: ...
    def identity(self) -> str: ...
    def version(self) -> str: ...
    def origin(self) -> str | None: ...
    def list_instance_ids(self) -> list[str]: ...
    def list_task_ids(self) -> list[str]: ...
    def get_task(self, task_id: str) -> TaskPayload: ...
    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextPayload: ...
    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload: ...
    def fixtures(self) -> object: ...
    def capability_report(self) -> DatasetCapabilityReport: ...
```

### Optional capabilities (with default implementations)

```python
    def get_oracle(self, instance_id: str, task_id: str) -> object:
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        return None

    def tool_provider(self) -> object | None:
        return None

    def evaluation_helpers(self) -> object | None:
        return None

    def strategy_descriptors(self) -> list[StrategyDescriptor] | None:
        return None
```

**Backward compatibility**: existing implementations that define `get_context_artifact` and `get_evidence_artifact` must add `get_context` and `get_evidence` wrappers. The old names may be kept internally but are not part of the v0 contract.

---

## `AdapterRegistry` and `ResolvedDatasetRef`

`src/ctxbench/dataset/registry.py`

### `ResolvedDatasetRef`

```python
@dataclass(slots=True)
class ResolvedDatasetRef:
    id: str
    version: str
    root: str | None = None
    origin: str | None = None
    content_hash: str | None = None
    materialized_path: str | None = None
```

Constructed by the registry from the incoming `ExperimentDataset` + materialization info.

### `AdapterRegistry`

```python
Factory = Callable[[ResolvedDatasetRef], DatasetPackage]

class AdapterRegistry:
    def register(self, dataset_id: str, factory: Factory) -> None: ...
    def resolve(self, dataset_ref: ExperimentDataset) -> DatasetPackage: ...
        # builds ResolvedDatasetRef from dataset_ref, calls factory
        # raises AdapterUnavailableError if no factory registered for dataset_ref.id

def get_default_registry() -> AdapterRegistry:
    # returns the singleton registry populated by ctxbench.adapters.registry
```

`ctxbench.dataset.registry` defines only the class and `get_default_registry()`. It does NOT wire concrete adapters.

### `ctxbench.adapters.registry`

```python
# src/ctxbench/adapters/registry.py
from ctxbench.dataset.registry import AdapterRegistry
from ctxbench.adapters.lattes.package import LattesDatasetAdapter

_registry = AdapterRegistry()
_registry.register(
    "ctxbench/lattes",
    lambda ref: LattesDatasetAdapter(ref.materialized_path or ref.root),
)

def get_default_registry() -> AdapterRegistry:
    return _registry
```

Lifecycle modules import `get_default_registry` from `ctxbench.adapters.registry`, not from `ctxbench.dataset.registry`.

---

## Oracle Behavior in Evaluation

- `eval` SHOULD call `get_oracle(instance_id, task_id)` for each evaluated response.
- If the adapter does not implement `get_oracle`, it returns `ORACLE_UNAVAILABLE` (default protocol implementation).
- The evaluator MUST record whether oracle was available, whether it was used, and whether it was unavailable.
- Oracle MUST NOT be automatically sent to LLM judges. LLM-as-judge evaluation receives `EvidencePayload.evidence` only.
- Oracle is used ONLY by evaluators or evaluation modes explicitly configured for oracle-based validation (exact match, schema, heuristic, reference-aware judging).
- If oracle is unavailable, evaluation MUST continue when evidence-based evaluation is supported.
- Oracle availability and usage MUST be traceable in the evaluation trace artifact.

In v0, the Lattes adapter returns `ORACLE_UNAVAILABLE` from `get_oracle`. Oracle-based evaluation modes are not activated by default for Lattes experiments.

---

## Experiment Definition Impact

No structural changes to experiment definition files in Spec 004. Semantic clarifications only:

| Field | Semantics |
|---|---|
| `dataset.id` | Used by Adapter Registry v0 to select the adapter. E.g. `"ctxbench/lattes"`. |
| `dataset.root` | Local path to an already materialized dataset package (Spec 003 artifact). |
| `dataset.version` | Versioned dataset reference; required with `dataset.id`. |
| `factors.format` | Context representation request. Passed unmodified to adapter as `representation` parameter of `get_context`. Not a filename. |

Experiment definitions MUST NOT name adapter classes, Python modules, parser names, tool implementation names, or Lattes-specific filenames.

A documentation/test task is included in S7 to ensure example experiments and fixtures reflect this interpretation.

---

## Trace Capability Recording

Using the existing trace mechanism (no new trace architecture):

After `get_context` is called, the executor records in `AIRequest.metadata`:
```python
"context_representation": runspec.format,
"context_obtained": True,
```

After evaluation, the evaluator records in the evaluation trace:
```python
"evidence_obtained": True,
"oracle_available": not isinstance(oracle_result, OracleUnavailable),
"oracle_used": False,  # v0: oracle is never used in judge evaluation
```

Tool capability is already traceable via `CapabilityUnavailableError` on failure.

---

## Files Likely Affected

### New files

| File | Purpose |
|---|---|
| `src/ctxbench/dataset/payloads.py` | `ContextPayload`, `EvidencePayload`, `TaskPayload`, `OracleUnavailable`, `ORACLE_UNAVAILABLE` |
| `src/ctxbench/dataset/errors.py` | `AdapterUnavailableError`, `CapabilityUnavailableError`, `UnsupportedRepresentationError` |
| `src/ctxbench/dataset/registry.py` | `AdapterRegistry`, `ResolvedDatasetRef`, `get_default_registry` stub |
| `src/ctxbench/adapters/__init__.py` | package marker |
| `src/ctxbench/adapters/registry.py` | first-party wiring: registers `ctxbench/lattes` → `LattesDatasetAdapter` |
| `src/ctxbench/adapters/lattes/__init__.py` | package marker (moved from `datasets/lattes`) |
| `src/ctxbench/adapters/lattes/package.py` | `LattesDatasetAdapter` (moved + renamed) |
| `src/ctxbench/adapters/lattes/tools.py` | moved from `datasets/lattes` |
| `src/ctxbench/adapters/lattes/mcp_server.py` | moved from `datasets/lattes` |
| `src/ctxbench/adapters/lattes/models.py` | moved from `datasets/lattes` |
| `src/ctxbench/adapters/lattes/provider.py` | moved from `datasets/lattes` |
| `src/ctxbench/adapters/lattes/readers/` | moved from `datasets/lattes/readers/` |
| `tests/test_dataset_adapter_registry.py` | registry tests |
| `tests/test_dataset_payloads.py` | payload type + sentinel tests |
| `tests/test_import_boundaries.py` | import-boundary validation |

### Modified files

| File | Change |
|---|---|
| `src/ctxbench/dataset/package.py` | Add `get_task`, `get_context`, `get_evidence`, `get_oracle`, `get_task_instance` to protocol; import `TaskPayload`, `ContextPayload`, `EvidencePayload` from `payloads.py` |
| `src/ctxbench/dataset/provider.py` | Remove `FORMAT_ARTIFACTS`, remove `_specialized_local_dataset_package`; add `get_task`, `get_context`, `get_evidence`, `get_oracle`, `get_task_instance` to `LocalDatasetPackage` |
| `src/ctxbench/benchmark/runspec_generator.py` | Use `DatasetPackage` protocol (not `LocalDatasetPackage`); use `get_task` / `get_task_instance` instead of `get_question` / `get_question_instance` |
| `src/ctxbench/benchmark/executor.py` | Use registry; call `get_context` for inline; call `tool_provider()` for tool-mediated; rename `lattes_id` → `instance_id`; add trace fields |
| `src/ctxbench/benchmark/evaluation.py` | Use registry; call `get_evidence` → `EvidencePayload`; call `get_oracle`; record oracle availability; remove `get_question`/`get_context_blocks` |
| `src/ctxbench/commands/plan.py` | Import `DatasetPackage` protocol; use registry for conformance; pass adapter to `generate_runspecs` |

### Not changing

| File | Reason |
|---|---|
| `src/ctxbench/commands/export.py` | Artifact-only; no dataset access (FR-048) |
| `src/ctxbench/commands/status.py` | Artifact-only; no dataset access (FR-049) |
| `src/ctxbench/commands/eval.py` | Orchestration layer; inner `evaluation.py` changes cover the boundary |
| `src/ctxbench/dataset/resolver.py` | Spec 003 materialization resolver; separate concern |
| `src/ctxbench/ai/strategies/` | `lattes_id`/`instance_id` fallback already in place; metadata rename at source (executor) is sufficient |
| `src/ctxbench/ai/engine.py`, `runtime.py` | No dataset coupling |

---

## Implementation Slices

| Slice | Goal | Likely files | Validation | Depends on |
|---|---|---|---|---|
| S1 | Payload types + error types | `payloads.py` (new), `errors.py` (new), `tests/test_dataset_payloads.py` | `pytest -k payloads or adapter_errors` | — |
| S2 | `DatasetPackage` protocol + `AdapterRegistry` + `ResolvedDatasetRef` | `package.py`, `registry.py` (new) | `pytest -k dataset_package_contract or registry` | S1 |
| S3 | Package namespace: move `ctxbench.datasets.lattes` → `ctxbench.adapters.lattes`, add `ctxbench.adapters.registry`, import-boundary tests | `adapters/` tree (new), `datasets/lattes/` (emptied), `tests/test_import_boundaries.py` | `pytest -k import_boundary or lattes_dataset` | S2 |
| S4 | Adapt `runspec_generator.py` + `commands/plan.py` through adapter contract | `runspec_generator.py`, `commands/plan.py`, `dataset/provider.py` | `pytest -k plan or cli or runspec` | S3 |
| S5 | Executor boundary: `get_context` for inline, `tool_provider` for tools, trace fields | `benchmark/executor.py` | `pytest -k execute or lifecycle_no_network` | S3 |
| S6 | Evaluation boundary: `get_evidence` → `EvidencePayload`, `get_oracle`, oracle trace recording | `benchmark/evaluation.py` | `pytest -k eval` | S3 |
| S7 | Lattes adapter conformance + provider-free tests | `adapters/lattes/package.py`, `tests/test_fake_dataset_adapter.py`, `tests/test_dataset_adapter_registry.py` | `pytest -k fake_dataset or registry or lattes_adapter` | S3 |

Slices S4, S5, S6, and S7 are independent once S3 is green.

---

### Slice detail: S1 — Payload types + error types

`src/ctxbench/dataset/payloads.py`:
- `ContextPayload(role, representation, content, content_type, metadata)` — `content` is `str` in v0 for inline-strategy use
- `EvidencePayload(role, task, evidence, task_instance, metadata)` — no Lattes-specific keys
- `TaskPayload(task_id, statement, tags, validation_type, context_blocks, metadata)`
- `OracleUnavailable` class + `ORACLE_UNAVAILABLE` singleton

`src/ctxbench/dataset/errors.py`:
- `AdapterUnavailableError(ValueError)` — registry cannot resolve dataset identity
- `CapabilityUnavailableError(ValueError)` — adapter does not provide a required capability
- `UnsupportedRepresentationError(ValueError)` — adapter cannot serve the requested representation

Tests:
- Error types are `ValueError` subclasses
- `ORACLE_UNAVAILABLE` is not `None`, not a dict, is `OracleUnavailable` instance
- `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` → `True`

---

### Slice detail: S2 — Protocol + registry

`src/ctxbench/dataset/package.py` changes:
- Import `TaskPayload`, `ContextPayload`, `EvidencePayload` from `payloads.py`
- Replace `get_context_artifact` with `get_context(instance_id, task_id, representation) → ContextPayload`
- Replace `get_evidence_artifact` with `get_evidence(instance_id, task_id) → EvidencePayload`
- Add mandatory: `get_task(task_id) → TaskPayload`
- Add optional (with defaults): `get_oracle`, `get_task_instance`, `tool_provider`, `evaluation_helpers`, `strategy_descriptors`
- Keep `list_instance_ids`, `list_task_ids`, `identity`, `version`, `origin`, `metadata`, `fixtures`, `capability_report` unchanged

`src/ctxbench/dataset/registry.py`:
```python
@dataclass(slots=True)
class ResolvedDatasetRef:
    id: str; version: str; root: str | None; origin: str | None
    content_hash: str | None; materialized_path: str | None

Factory = Callable[[ResolvedDatasetRef], DatasetPackage]

class AdapterRegistry:
    _factories: dict[str, Factory]
    def register(self, dataset_id: str, factory: Factory) -> None
    def resolve(self, dataset_ref: ExperimentDataset) -> DatasetPackage
        # raises AdapterUnavailableError if dataset_ref.id not registered
        # raises AdapterUnavailableError if dataset_ref.id is None

def get_default_registry() -> AdapterRegistry:
    # imports lazily from ctxbench.adapters.registry to avoid circular imports
    from ctxbench.adapters.registry import get_default_registry as _get
    return _get()
```

---

### Slice detail: S3 — Package namespace cleanup

Steps:
1. Create `src/ctxbench/adapters/__init__.py` (empty)
2. Copy `src/ctxbench/datasets/lattes/` tree to `src/ctxbench/adapters/lattes/`
3. Update all internal imports: `ctxbench.datasets.lattes.*` → `ctxbench.adapters.lattes.*`
4. Rename `LattesDatasetPackage` → `LattesDatasetAdapter` in `adapters/lattes/package.py`
5. Add `get_context`, `get_evidence`, `get_task`, `get_task_instance`, `get_oracle` to `LattesDatasetAdapter` using the new payload types
6. Remove `FORMAT_ARTIFACTS` from `ctxbench.dataset.provider`; move to `LattesDatasetAdapter`
7. Create `src/ctxbench/adapters/registry.py`:
   ```python
   from ctxbench.adapters.lattes.package import LattesDatasetAdapter
   _registry = AdapterRegistry()
   _registry.register("ctxbench/lattes", lambda ref: LattesDatasetAdapter(ref.materialized_path or ref.root))
   def get_default_registry() -> AdapterRegistry: return _registry
   ```
8. Remove `_specialized_local_dataset_package` from `ctxbench.dataset.provider`
9. Empty `src/ctxbench/datasets/lattes/` (leave `__init__.py` stub pointing to new location)
10. Add `tests/test_import_boundaries.py`:
    - Assert no import of `ctxbench.adapters.lattes` in `ctxbench.benchmark.*`
    - Assert no import of `ctxbench.adapters` in `ctxbench.dataset.*`

`LattesDatasetAdapter.get_context`:
```python
def get_context(self, instance_id, task_id, representation) -> ContextPayload:
    filename = self.FORMAT_ARTIFACTS.get(representation, representation)
    path = Path(self.dataset_paths.contexts) / instance_id / filename
    if not path.exists():
        raise UnsupportedRepresentationError(
            f"Representation '{representation}' not available for instance '{instance_id}'"
        )
    content_type = "text/html" if filename.endswith(".html") else "application/json"
    content = path.read_text("utf-8") if content_type == "text/html" else json.dumps(load_json(path))
    return ContextPayload(role="context", representation=representation, content=content, content_type=content_type)
```

`LattesDatasetAdapter.get_evidence`:
```python
def get_evidence(self, instance_id, task_id) -> EvidencePayload:
    task = self.get_task(task_id)
    blocks = self._load_context_blocks(instance_id)  # internal method; returns dict[str, object]
    task_inst = self.get_task_instance(instance_id, task_id)
    return EvidencePayload(
        role="evidence",
        task={"task_id": task.task_id, "statement": task.statement, "context_blocks": task.context_blocks},
        evidence=blocks,  # dict of block content; no "contextBlocks" key exposed generically
        task_instance=task_inst,
    )
```

`LattesDatasetAdapter.get_task`:
```python
def get_task(self, task_id) -> TaskPayload:
    q = self.get_question(task_id)  # existing internal method
    return TaskPayload(
        task_id=q.id,
        statement=q.question,
        tags=list(q.tags),
        validation_type=q.validation.type,
        context_blocks=list(q.contextBlock),
    )
```

`LattesDatasetAdapter.get_task_instance`:
```python
def get_task_instance(self, instance_id, task_id) -> dict[str, object] | None:
    qi = self._get_question_instance(task_id, instance_id)  # existing internal method
    if qi is None:
        return None
    return {"parameters": dict(qi.parameters)}
```

`LocalDatasetPackage` additions (in `provider.py`):
```python
def get_task(self, task_id) -> TaskPayload:
    q = self.get_question(task_id)
    return TaskPayload(task_id=q.id, statement=q.question, tags=list(q.tags),
                       validation_type=q.validation.type, context_blocks=list(q.contextBlock))

def get_context(self, instance_id, task_id, representation) -> ContextPayload:
    # existing get_context_artifact logic, but returns ContextPayload
    ...

def get_evidence(self, instance_id, task_id) -> EvidencePayload:
    # existing get_evidence_artifact logic, but returns EvidencePayload with generic keys
    ...

def get_task_instance(self, instance_id, task_id) -> dict[str, object] | None:
    qi = self.get_question_instance(task_id, instance_id)
    return {"parameters": dict(qi.parameters)} if qi is not None else None
```

---

### Slice detail: S4 — Planning through adapter

`src/ctxbench/benchmark/runspec_generator.py`:
- Type annotation: `dataset_package: DatasetPackage` (not `LocalDatasetPackage`)
- Replace `dataset_package.list_question_ids()` → `dataset_package.list_task_ids()`
- Replace `dataset_package.get_question(question_id)` → `task = dataset_package.get_task(question_id)`
- Replace `dataset_package.get_question_instance(question_id, instance_id)` → `task_inst = dataset_package.get_task_instance(instance_id, question_id)`
- Replace `question.question` → `task.statement`
- Replace `question.contextBlock` → `task.context_blocks`
- Replace `question.tags` → `task.tags`
- Replace `question.validation.type` → `task.validation_type`
- Replace `question_instance.parameters` → `task_inst.get("parameters", {}) if task_inst else {}`
- Remove import `from ctxbench.dataset.provider import LocalDatasetPackage`

`src/ctxbench/commands/plan.py`:
- After `DatasetResolver.resolve()`, call `get_default_registry().resolve(resolved_ref)` to get the adapter
- Replace `isinstance(package, LocalDatasetPackage)` with protocol-based capability check
- Pass `adapter` to `generate_runspecs(experiment, base_dir, adapter, ...)`

---

### Slice detail: S5 — Executor boundary

`src/ctxbench/benchmark/executor.py` — before (violations):
```python
provider = DatasetProvider.from_dataset(runspec.dataset)
context = provider.get_context(runspec.instanceId, runspec.format)  # Lattes-specific
context_path = provider.get_context_artifact_path(...)  # Lattes-specific
instance_dir = provider.get_instance_dir(...)  # Lattes-specific
lattes_id = runspec.instanceId
metadata = {..., "lattes_id": lattes_id, "instance_dir": ..., "context_path": ...}
```

After (through adapter contract):
```python
from ctxbench.adapters.registry import get_default_registry
adapter = get_default_registry().resolve(runspec.dataset)

# Inline strategies: get context payload
if runspec.strategy == "inline":
    ctx = adapter.get_context(runspec.instanceId, runspec.questionId, runspec.format)
    context_content = ctx.content  # str in v0
else:
    context_content = ""  # tool-mediated; context comes through tool_provider

metadata = {
    ...,
    "instance_id": runspec.instanceId,
    "context_representation": runspec.format,
    "context_obtained": runspec.strategy == "inline",
    # context_path and instance_dir removed (Lattes-internal)
}
```

Tool capability check in `_build_tool_runtime_factories`:
```python
from ctxbench.dataset.errors import CapabilityUnavailableError
# replace ValueError with:
raise CapabilityUnavailableError(
    f"Strategy '{runspec.strategy}' requires tool capability; "
    f"adapter for '{runspec.dataset.id}' does not provide tools."
)
```

---

### Slice detail: S6 — Evaluation boundary

`src/ctxbench/benchmark/evaluation.py` — before (violations):
```python
provider = DatasetProvider.from_dataset(result.dataset)
question = provider.get_question(result.questionId)  # Lattes-specific
block_ids = list(question.contextBlock)
all_blocks = provider.get_context_blocks(result.instanceId)  # Lattes-specific
```

After:
```python
from ctxbench.adapters.registry import get_default_registry
adapter = get_default_registry().resolve(result.dataset)
evidence_payload = adapter.get_evidence(result.instanceId, result.questionId)  # → EvidencePayload
oracle_result = adapter.get_oracle(result.instanceId, result.questionId)       # → object | OracleUnavailable
oracle_available = not isinstance(oracle_result, OracleUnavailable)

# evidence_payload.evidence contains the block content (generic dict, no "contextBlocks" key)
# evidence_payload.task contains task metadata with context_blocks list
block_ids = evidence_payload.task.get("context_blocks", []) if isinstance(evidence_payload.task, dict) else []
all_blocks = evidence_payload.evidence  # dict of block content
context_payload, missing = _get_context_blocks(all_blocks, block_ids)
```

Trace recording additions:
```python
"evidence_obtained": True,
"oracle_available": oracle_available,
"oracle_used": False,  # v0: oracle never used in LLM-as-judge path
```

**Oracle / judge separation rule enforced in code**:
- `build_evaluation_job` does not pass `oracle_result` to `JUDGE_PROMPT`.
- `oracle_result` is recorded in the evaluation trace only.

---

### Slice detail: S7 — Conformance tests

`tests/test_fake_dataset_adapter.py` (new or update `test_dataset_package_contract.py`):
```python
class FakeDatasetAdapter:
    """Minimal adapter implementing all v0 mandatory capabilities."""
    def get_task(self, task_id) -> TaskPayload: return TaskPayload(task_id=task_id, statement="Q?")
    def get_context(self, instance_id, task_id, representation) -> ContextPayload:
        if representation not in ("text", "json"): raise UnsupportedRepresentationError(representation)
        return ContextPayload(role="context", representation=representation, content="ctx")
    def get_evidence(self, instance_id, task_id) -> EvidencePayload:
        return EvidencePayload(role="evidence", task={"task_id": task_id}, evidence={})
    def get_oracle(self, instance_id, task_id): return ORACLE_UNAVAILABLE
    # ... other required methods
```

Tests:
- `FakeDatasetAdapter` satisfies `DatasetPackage` protocol
- `get_context` with unsupported representation raises `UnsupportedRepresentationError`
- `get_oracle` returns `ORACLE_UNAVAILABLE` (not `None`)
- Registry resolves `ctxbench/lattes` to a `LattesDatasetAdapter` instance
- Registry raises `AdapterUnavailableError` for unknown id
- `isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)` is `True`

Experiment definition fixture test:
- Load `experiment.json`; verify no adapter class name, module path, or Lattes filename is referenced
- Verify `factors.format` values are strings (not filenames)

---

## Migration Impact

| Surface | Impact |
|---|---|
| Experiment definitions | None — `dataset.id`, `dataset.root`, `dataset.version`, `factors.format` unchanged |
| Artifact schemas | None — `trials.jsonl`, `responses.jsonl`, `evals.jsonl` field names unchanged |
| CLI behavior | None — same commands, same flags |
| `context_path` metadata field | Removed from executor metadata; no strategy reads it (verified by grep) |
| `instance_dir` metadata field | Removed from executor metadata; no strategy reads it (verified by grep) |
| `lattes_id` metadata field | Renamed to `instance_id`; strategies' `_resolve_lattes_id` already falls back to `instance_id` |
| `ctxbench.datasets.lattes` imports | Redirected to `ctxbench.adapters.lattes`; old package left with stub `__init__.py` |
| `LattesDatasetPackage` class name | Renamed to `LattesDatasetAdapter` inside `ctxbench.adapters.lattes` |
| `DatasetProvider.from_dataset` | Still works for `LocalDatasetPackage` use cases; `_specialized_local_dataset_package` removed |
| `get_context_artifact` / `get_evidence_artifact` | Internal wrappers may remain in `LocalDatasetPackage`; removed from protocol surface |
| `contextBlock` field in `RunSpec`/`RunResult` | Unchanged (comes from `TaskPayload.context_blocks`; artifact field preserved) |
| Test fixtures | `CompleteDatasetPackage` in `test_dataset_package_contract.py` gains `get_task`, `get_context`, `get_evidence`, `get_oracle`, `get_task_instance` |

---

## Architectural Impact

- **Package boundary**: `ctxbench.dataset` and `ctxbench.adapters` are sibling packages with enforced import direction. No circular imports.
- **Registry as single binding point**: `dataset.id == "ctxbench/lattes"` appears only in `ctxbench.adapters.registry`.
- **Protocol completeness**: `DatasetPackage` now covers all six mandatory and four optional capabilities with named payload types.
- **Evaluator decoupling**: `evaluation.py` no longer accesses `contextBlocks`, `get_question`, or `get_context_blocks`. It uses `EvidencePayload`.
- **Planning decoupling**: `runspec_generator.py` no longer imports `LocalDatasetPackage`, `Question`, or `QuestionInstance`.
- **Executor decoupling**: `executor.py` no longer calls Lattes-specific methods; calls only `get_context` (inline) or `tool_provider()` (tools).
- **Remaining Lattes coupling**: `LattesDatasetAdapter` internally still uses Lattes-specific parsing. This is correct — all Lattes logic belongs in the Lattes adapter.
- **`LocalDatasetPackage` scope**: Remains as a generic fallback for local dataset roots without a registered adapter. Its Lattes-specific methods (`get_question`, `get_context_blocks`, etc.) remain as internal implementation details, not protocol surface.

---

## Risks

| Risk | Mitigation |
|---|---|
| `evaluation.py` evidence unpack: `evidence_payload.evidence` structure differs from old `all_blocks` dict | Run `pytest -k eval` immediately after S6; audit `_get_context_blocks` caller sites |
| `runspec_generator.py`: `TaskPayload` fields may miss something `Question` model had (e.g. template rendering edge cases) | Run `pytest -k plan or runspec` after S4; compare rendered trial payloads |
| Lattes import move: internal lattes cross-imports may be missed | Run full import scan with `python -c "import ctxbench"` after S3; run `pytest tests/` |
| `context_path`/`instance_dir` removal from metadata: analysis scripts reading raw traces may break | Document removal; existing tests already verify no strategy reads these fields |
| `get_default_registry()` lazy import in `ctxbench.dataset.registry` may create subtle import order issues | Test with `pytest -k registry` and verify no import errors at module load |
| Oracle trace fields: adding `oracle_available` / `oracle_used` to evaluation output changes eval trace schema | Verify these are additive (not breaking); update `test_artifact_contracts.py` if eval trace schema is tested |

---

## Validation

Provider-free validation per slice:

```bash
# S1:
pytest -k "payloads or adapter_errors" -v

# S2:
pytest -k "dataset_package_contract or registry" -v

# S3:
pytest -k "import_boundary or lattes_dataset or lattes_adapter" -v
python -c "import ctxbench.benchmark.executor; import ctxbench.benchmark.evaluation"

# S4:
pytest -k "plan or cli or runspec" -v

# S5:
pytest -k "execute or lifecycle_no_network" -v

# S6:
pytest -k "eval" -v

# S7:
pytest -k "fake_dataset or registry or lattes_adapter" -v

# Full (after all slices):
pytest tests/ -x --ignore=tests/fixtures
```

No real LLM provider call is required at any slice boundary.

---

## Questions Answered

| Question | Answer |
|---|---|
| Which component decides which capability to call? | The benchmark core (lifecycle phases, strategy, evaluation engine) decides. The adapter only provides capabilities. |
| What does `get_context` return? | `ContextPayload(role, representation, content, content_type, metadata)`. `content` is a string in v0. |
| Which strategies use `get_context`? | `inline` only. Tool-mediated strategies use `tool_provider()`. |
| How does judge evaluation receive evidence? | Via `EvidencePayload.evidence` returned by `get_evidence`. No Lattes-specific keys in the generic contract. |
| When is oracle queried? | During `eval`, for all evaluated responses. |
| When is oracle sent to an evaluator? | Never automatically. Only oracle-configured evaluation modes use it. LLM judges receive evidence only. |
| How does the experiment definition select a dataset and context representation? | `dataset.id` selects the adapter via the registry. `factors.format` is the representation request passed to `get_context`. |
| Where do generic dataset contracts live? | `ctxbench.dataset.*` |
| Where do concrete first-party adapters live? | `ctxbench.adapters.*` |
| Which modules may import concrete adapters? | Only `ctxbench.adapters.registry`. Lifecycle modules import only `get_default_registry`. |
| What remains deferred to Spec 006? | Moving `LattesDatasetAdapter` to the external `ctxbench/lattes` package. |

---

## Process Logging

Level 2 change. Create or update:
- `specs/004-dataset-package-capabilities/worklog.md` — record slice completions, decisions, and any deviations

---

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `LocalDatasetPackage` methods still call `get_question` etc. internally | `LocalDatasetPackage` is the temp in-repo adapter (FR-009); internal methods are adapter-private | Renaming all internal methods would be premature given Spec 006 will restructure the Lattes adapter entirely |
| `evaluation.py` must unpack `EvidencePayload.evidence` dict | Evidence structure is adapter-defined opaque payload; the evaluator uses it without knowing Lattes layout | A typed `EvidencePayload.evidence` would leak Lattes schema into the core contract |
