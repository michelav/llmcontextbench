# Contract: Dataset Package Capabilities v0

**Defined in**: `src/ctxbench/dataset/package.py` (`DatasetPackage` protocol)  
**Registry**: `src/ctxbench/dataset/registry.py` (`AdapterRegistry`)  
**Errors**: `src/ctxbench/dataset/errors.py`  
**Spec**: [spec.md](../spec.md)

---

## Purpose

Every dataset adapter registered with the Adapter Registry v0 MUST conform to this contract. The contract is expressed as a Python `Protocol` (structural subtyping). No explicit inheritance is required.

---

## Mandatory Capabilities

All six mandatory capabilities MUST be implemented. A `DatasetCapabilityReport` with `conformant=False` signals a non-conformant adapter.

### `metadata() → DatasetMetadata`

Returns identity, version, name, domain, description, and provenance. Never raises.

### `list_instance_ids() → list[str]`

Returns a stable list of `instanceId` strings. The list MUST be stable across calls within a single run. May return an empty list.

### `list_task_ids() → list[str]`

Returns a stable list of `taskId` strings. May return an empty list.

### `get_task(task_id: str) → object`

Returns a task object containing at minimum a prompt-ready task statement. Raises `KeyError` (or equivalent) if `task_id` is unknown.

### `get_context_artifact(instance_id: str, task_id: str, strategy: str, format_name: str) → object`

Returns the context payload for the model under test. Raises `UnsupportedRepresentationError` if `format_name` is not supported. The core MUST NOT catch this error and substitute a different format.

### `get_evidence_artifact(instance_id: str, task_id: str) → object`

Returns the evidence payload for the evaluator. The structure of the payload is adapter-defined; the core treats it as opaque.

---

## Optional Capabilities

### `get_oracle(instance_id: str, task_id: str) → object`

Returns an oracle (expected answer, validation rule, or authoritative criterion) or `ORACLE_UNAVAILABLE`. MUST NOT return `None`, an empty string, or any falsy value to signal absence. Use `isinstance(result, OracleUnavailable)` to detect absence.

### `tool_provider() → object | None`

Returns a tool service for tool-mediated strategies, or `None` if not supported. The executor raises `CapabilityUnavailableError` if a tool-requiring strategy is selected and this returns `None`.

### `fixtures() → object`

Returns small provider-free fixtures for conformance validation. Recommended but not required.

### `evaluation_helpers() → object | None`

Reserved for future use. Return `None` in v0.

### `strategy_descriptors() → list[StrategyDescriptor] | None`

Reserved for future use. Return `None` in v0.

---

## Error Types

| Error | Module | Raiser |
|---|---|---|
| `AdapterUnavailableError(ValueError)` | `ctxbench.dataset.errors` | `AdapterRegistry.resolve()` |
| `CapabilityUnavailableError(ValueError)` | `ctxbench.dataset.errors` | `executor.py` (benchmark orchestrator) |
| `UnsupportedRepresentationError(ValueError)` | `ctxbench.dataset.errors` | Adapter implementation |

---

## Registration

```python
from ctxbench.dataset.registry import get_default_registry

registry = get_default_registry()
registry.register("my/dataset", lambda root: MyDatasetAdapter(root))
```

Registration is explicit and first-party. No dynamic loading, no entry points.

---

## Conformance Validation

Run conformance against the `FakeDatasetAdapter` fixture in `tests/test_fake_dataset_adapter.py`:

```bash
pytest -k fake_dataset -v
```

A conformant adapter:
- implements all six mandatory capabilities
- returns `ORACLE_UNAVAILABLE` (not `None`) from `get_oracle` when no oracle exists
- raises `UnsupportedRepresentationError` (not `KeyError`) for unsupported representations
- returns stable `list_instance_ids()` across calls within the same instance
