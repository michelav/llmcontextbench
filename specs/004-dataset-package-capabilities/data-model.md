# Data Model: Dataset Package Capabilities v0

**Spec**: [spec.md](spec.md)  
**Plan**: [plan.md](plan.md)  
**Date**: 2026-05-19

---

## Entities

### AdapterRegistry

`src/ctxbench/dataset/registry.py`

| Field | Type | Notes |
|---|---|---|
| `_registry` | `dict[str, Callable[[str], DatasetPackage]]` | Maps `dataset_id → factory`. Factory receives resolved local root path. |

Methods:
- `register(dataset_id, factory)` — explicit first-party registration only
- `resolve(dataset_ref: ExperimentDataset) → DatasetPackage` — raises `AdapterUnavailableError` if no adapter

Default instance: `_default_registry`, wired with `"ctxbench/lattes"` at module import.

---

### DatasetPackage (protocol — extended)

`src/ctxbench/dataset/package.py`

Mandatory methods (all existing + new):

| Method | Signature | Notes |
|---|---|---|
| `metadata()` | `→ DatasetMetadata` | Dataset identity, domain, description, provenance |
| `identity()` | `→ str` | Stable dataset identifier |
| `version()` | `→ str` | Dataset version |
| `origin()` | `→ str | None` | Source URL or local root |
| `list_instance_ids()` | `→ list[str]` | Stable instanceId enumeration |
| `list_task_ids()` | `→ list[str]` | Stable taskId enumeration |
| `get_task()` | `(task_id: str) → object` | **New**. Task object with prompt-ready statement. |
| `get_context_artifact()` | `(instance_id, task_id, strategy, format_name) → object` | Context payload for model |
| `get_evidence_artifact()` | `(instance_id, task_id) → object` | Evidence payload for evaluator |
| `get_oracle()` | `(instance_id, task_id) → object` | **New optional**. Returns `ORACLE_UNAVAILABLE` if absent. |
| `fixtures()` | `→ object` | Provider-free validation fixtures |
| `capability_report()` | `→ DatasetCapabilityReport` | Conformance summary |

Optional methods (unchanged):
- `tool_provider() → object | None`
- `evaluation_helpers() → object | None`
- `strategy_descriptors() → list[StrategyDescriptor] | None`

---

### Error Types

`src/ctxbench/dataset/errors.py`

| Name | Base | Raised by | When |
|---|---|---|---|
| `AdapterUnavailableError` | `ValueError` | `AdapterRegistry.resolve()` | No adapter registered for the given `dataset_id` |
| `CapabilityUnavailableError` | `ValueError` | `executor.py` | Adapter does not provide `tool_provider()` but strategy requires tools |
| `UnsupportedRepresentationError` | `ValueError` | Adapter (Lattes or future) | Requested `representation` / `format` not supported |

### OracleUnavailable (sentinel)

`src/ctxbench/dataset/errors.py`

```python
class OracleUnavailable:
    """Distinct sentinel returned by get_oracle() when no oracle is available."""

ORACLE_UNAVAILABLE = OracleUnavailable()
```

Not `None`, not empty dict. `isinstance(result, OracleUnavailable)` is the check.

---

## Relationships

```
ExperimentDataset
    └──(id, root)──► AdapterRegistry.resolve()
                          │
                          ▼
                     DatasetPackage  ◄─── LocalDatasetPackage (temp, in-repo)
                          │               └── LattesDatasetPackage (temp, in-repo)
                          │
              ┌───────────┼──────────────┐
              ▼           ▼              ▼
        get_context  get_evidence   get_oracle
         (execute)    (evaluate)   (evaluate)
```

---

## Existing Types (unchanged)

- `DatasetMetadata` — `package.py`, used in `metadata()`
- `DatasetCapabilityReport` — `capabilities.py`, used in `capability_report()`
- `StrategyDescriptor` — `package.py`, used in `strategy_descriptors()`
- `DatasetResolver` — `resolver.py`, S3 local-file resolver (not the adapter registry)
- `MaterializationManifest` — `materialization.py`, S3 provenance record

---

## Method Mapping: Spec → Implementation

| Spec capability (FR) | Implementation method | Notes |
|---|---|---|
| `metadata` (FR-017) | `metadata()` | Unchanged |
| `list_instances` (FR-018) | `list_instance_ids()` | Spec name differs; semantics identical |
| `list_tasks` (FR-019) | `list_task_ids()` | Spec name differs; semantics identical |
| `get_task` (FR-020) | `get_task(task_id)` | New; delegates to `get_question` in current adapters |
| `get_context` (FR-021) | `get_context_artifact(instance_id, task_id, strategy, format_name)` | Signature broader; `strategy` currently unused by Lattes |
| `get_evidence` (FR-022) | `get_evidence_artifact(instance_id, task_id)` | Unchanged |
| `get_oracle` (FR-023) | `get_oracle(instance_id, task_id)` | New; returns `ORACLE_UNAVAILABLE` in v0 adapters |
| `get_tools` (FR-026) | `tool_provider()` | Spec name differs; semantics identical |
| `fixtures` (FR-028) | `fixtures()` | Unchanged |
