# Data Model: Dataset Package Capabilities v0

**Spec**: [spec.md](spec.md)  
**Plan**: [plan.md](plan.md)  
**Date**: 2026-05-20

---

## Package Layout

```
src/ctxbench/
  dataset/
    package.py      # DatasetPackage protocol
    payloads.py     # ContextPayload, EvidencePayload, TaskPayload, OracleUnavailable
    errors.py       # error types
    registry.py     # AdapterRegistry, ResolvedDatasetRef
    capabilities.py # DatasetCapabilityReport (existing)
    resolver.py     # DatasetResolver (Spec 003, existing)
    provider.py     # LocalDatasetPackage (existing, simplified)

  adapters/
    __init__.py
    registry.py         # first-party wiring
    lattes/
      package.py        # LattesDatasetAdapter
      tools.py
      mcp_server.py
      models.py
      provider.py
      readers/
```

---

## Entities

### `ResolvedDatasetRef`

`src/ctxbench/dataset/registry.py`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Dataset identity (e.g. `"ctxbench/lattes"`) |
| `version` | `str` | Dataset version |
| `root` | `str \| None` | Local root path |
| `origin` | `str \| None` | Source URL or origin |
| `content_hash` | `str \| None` | Integrity hash from Spec 003 materialization |
| `materialized_path` | `str \| None` | Resolved local materialization path |

Built by `AdapterRegistry.resolve()` from an `ExperimentDataset`.

---

### `AdapterRegistry`

`src/ctxbench/dataset/registry.py`

| Field | Type | Notes |
|---|---|---|
| `_factories` | `dict[str, Factory]` | Maps `dataset_id → Callable[[ResolvedDatasetRef], DatasetPackage]` |

Methods:
- `register(dataset_id, factory)` — explicit first-party registration
- `resolve(dataset_ref: ExperimentDataset) → DatasetPackage` — raises `AdapterUnavailableError` if unregistered

`ctxbench.dataset.registry` defines only generic registry types and helpers. It does not define a default wired registry and does not import `ctxbench.adapters`, lazily or otherwise.

`ctxbench.adapters.registry` holds the singleton wired with `"ctxbench/lattes"`. Lifecycle composition imports `get_default_registry()` from `ctxbench.adapters.registry`.

---

### `DatasetPackage` (protocol)

`src/ctxbench/dataset/package.py`

#### Mandatory

| Method | Signature | Notes |
|---|---|---|
| `metadata()` | `→ DatasetMetadata` | Identity, domain, provenance |
| `identity()` | `→ str` | Stable dataset id |
| `version()` | `→ str` | Dataset version |
| `origin()` | `→ str \| None` | Source reference |
| `list_instance_ids()` | `→ list[str]` | Stable, consistent within a run |
| `list_task_ids()` | `→ list[str]` | Stable task id enumeration |
| `get_task(task_id)` | `→ TaskPayload` | Task description + metadata |
| `get_context(instance_id, task_id, representation)` | `→ ContextPayload` | Model-facing context payload |
| `get_evidence(instance_id, task_id)` | `→ EvidencePayload` | Evaluator-facing evidence payload |
| `capability_report()` | `→ DatasetCapabilityReport` | Conformance summary |

#### Optional (default implementations)

| Method | Default | Notes |
|---|---|---|
| `get_oracle(instance_id, task_id)` | `return ORACLE_UNAVAILABLE` | Oracle or sentinel |
| `get_task_instance(instance_id, task_id)` | `return None` | Per-instance parameters dict |
| `tool_provider()` | `return None` | Domain-specific tool service |
| `fixtures()` | `return None` | Optional provider-free conformance fixtures |

`fixtures()` is recommended but optional in v0. Dataset-contributed evaluation helpers and strategy descriptors are out of scope for the v0 protocol.

---

### Payload Types

`src/ctxbench/dataset/payloads.py`

#### `ContextPayload`

| Field | Type | Notes |
|---|---|---|
| `role` | `Literal["context"]` | Always `"context"` |
| `representation` | `str` | Value from `factors.format`; passed unmodified from experiment |
| `content` | `object` | Model-facing content. MUST be `str` in v0 for inline strategies. |
| `content_type` | `str \| None` | MIME hint: `"text/html"`, `"application/json"`, etc. |
| `metadata` | `dict[str, object]` | Adapter-internal trace info; not consumed by core |

**Used by**: `execute` phase (inline strategy only). Tool-mediated strategies use `tool_provider()`.

#### `EvidencePayload`

| Field | Type | Notes |
|---|---|---|
| `role` | `Literal["evidence"]` | Always `"evidence"` |
| `task` | `object` | Task description (adapter-defined structure) |
| `evidence` | `object` | Evaluator-facing evidence content (adapter-defined). For Lattes: dict of named context blocks. |
| `task_instance` | `object \| None` | Instance-specific task data |
| `metadata` | `dict[str, object]` | Trace metadata |

**Used by**: `eval` phase. `contextBlocks` is NOT a generic key; it remains internal to the Lattes adapter.

#### `TaskPayload`

| Field | Type | Notes |
|---|---|---|
| `task_id` | `str` | Stable task identifier |
| `statement` | `str` | Question template (may contain `{placeholder}` variables) |
| `tags` | `list[str]` | Task classification tags |
| `validation_type` | `str` | `"judge"` or other evaluation mode |
| `context_blocks` | `list[str]` | Block IDs (generic; Lattes-specific blocks resolved inside the adapter) |
| `metadata` | `dict[str, object]` | Adapter-internal extras |

**Used by**: `plan` phase (runspec generation) and optionally by `execute`.

#### `OracleUnavailable` (sentinel)

```python
class OracleUnavailable:
    """Distinct sentinel for absent oracle. Never None, never empty."""

ORACLE_UNAVAILABLE = OracleUnavailable()
```

Check: `isinstance(result, OracleUnavailable)`.

---

### Error Types

`src/ctxbench/dataset/errors.py`

| Name | Base | Raised by | When |
|---|---|---|---|
| `AdapterUnavailableError` | `ValueError` | `AdapterRegistry.resolve()` | No factory registered for `dataset_id` |
| `CapabilityUnavailableError` | `ValueError` | `executor.py` (lifecycle orchestrator) | `tool_provider()` returns `None` for tool-requiring strategy |
| `UnsupportedRepresentationError` | `ValueError` | Adapter (`get_context`) | `representation` not supported for this instance |

---

## Method Mapping: Spec → Implementation

| Spec capability (FR) | Protocol method | Notes |
|---|---|---|
| `metadata` (FR-017) | `metadata()` | Unchanged |
| `list_instances` (FR-018) | `list_instance_ids()` | Spec uses different name; semantics identical |
| `list_tasks` (FR-019) | `list_task_ids()` | Spec uses different name; semantics identical |
| `get_task` (FR-020) | `get_task(task_id) → TaskPayload` | New method |
| `get_context` (FR-021) | `get_context(instance_id, task_id, representation) → ContextPayload` | Replaces `get_context_artifact` |
| `get_evidence` (FR-022) | `get_evidence(instance_id, task_id) → EvidencePayload` | Replaces `get_evidence_artifact` |
| `get_oracle` (FR-023) | `get_oracle(instance_id, task_id) → object` | New optional; default returns `ORACLE_UNAVAILABLE` |
| `get_tools` (FR-026) | `tool_provider() → object \| None` | Spec uses different name; semantics identical |
| `fixtures` (FR-028) | `fixtures() → object \| None` | Optional; default returns `None` |

---

## Dependency Direction

```
ctxbench.dataset.*      ←── ctxbench.adapters.lattes.*
ctxbench.benchmark.*    ──► ctxbench.dataset.*
ctxbench.commands.*     ──► ctxbench.dataset.*
composition root        ──► ctxbench.adapters.registry
```

Enforced by `tests/test_import_boundaries.py`.

---

## Capability Selection Summary

| Phase | Adapter capability used |
|---|---|
| `plan` | `metadata`, `list_instance_ids`, `list_task_ids`, `get_task`, `get_task_instance` |
| `execute` (inline) | `get_context` |
| `execute` (tool-mediated) | `tool_provider` |
| `eval` | `get_evidence`, `get_oracle` |
| `export` | — (artifact-only) |
| `status` | — (artifact-only) |
