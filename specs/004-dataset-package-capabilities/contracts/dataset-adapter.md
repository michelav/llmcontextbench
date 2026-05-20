# Contract: Dataset Package Capabilities v0

**Protocol**: `ctxbench.dataset.package.DatasetPackage`  
**Payloads**: `ctxbench.dataset.payloads`  
**Errors**: `ctxbench.dataset.errors`  
**Registry**: `ctxbench.dataset.registry.AdapterRegistry`  
**Spec**: [spec.md](../spec.md) | **Plan**: [plan.md](../plan.md)

---

## Purpose

Every dataset adapter registered with the Adapter Registry v0 MUST conform to this contract. The contract is expressed as a Python `Protocol` (structural subtyping). No explicit inheritance is required.

---

## Mandatory Capabilities

All capabilities below MUST be implemented. A `DatasetCapabilityReport` with `conformant=False` signals a non-conformant adapter.

### `metadata() → DatasetMetadata`

Returns dataset identity, version, name, domain, description, and provenance. Never raises.

### `list_instance_ids() → list[str]`

Returns a stable list of `instanceId` strings. MUST be stable (same order and content) across calls within a single run. MAY return an empty list.

### `list_task_ids() → list[str]`

Returns a stable list of `taskId` strings. MAY return an empty list.

### `get_task(task_id: str) → TaskPayload`

Returns a `TaskPayload` containing:
- `task_id`: the task identifier
- `statement`: prompt-ready task statement (may contain `{placeholder}` template variables)
- `tags`: task classification tags
- `validation_type`: evaluation mode (`"judge"` or other)
- `context_blocks`: list of evidence block IDs relevant to this task

Raises `KeyError` (or equivalent) if `task_id` is unknown.

### `get_context(instance_id: str, task_id: str, representation: str) → ContextPayload`

Returns a `ContextPayload` for model-facing context:
- `role = "context"`
- `representation`: echoes the requested representation
- `content`: context payload (`str` in v0 for all inline-strategy representations)
- `content_type`: optional MIME hint
- `metadata`: adapter-internal extras (not consumed by the benchmark core)

Raises `UnsupportedRepresentationError` if `representation` is not supported. The benchmark core MUST NOT catch this error and substitute a different representation.

### `get_evidence(instance_id: str, task_id: str) → EvidencePayload`

Returns an `EvidencePayload` for the evaluator:
- `role = "evidence"`
- `task`: task description (adapter-defined structure)
- `evidence`: evaluator-facing evidence content (adapter-defined dict of named blocks)
- `task_instance`: optional instance-specific task data
- `metadata`: trace metadata

The payload structure is adapter-defined and opaque to the benchmark core.  
`contextBlocks` is NOT a generic contract key. Adapter-internal block keys may exist inside `evidence`.

### `fixtures() → object`

Returns small provider-free fixtures for conformance validation. Content is adapter-defined.

### `capability_report() → DatasetCapabilityReport`

Returns a conformance summary. A conformant adapter sets `conformant=True` and `missing_mandatory=[]`.

---

## Optional Capabilities

### `get_oracle(instance_id: str, task_id: str) → object`

Returns an oracle result or `ORACLE_UNAVAILABLE`.

**Rules**:
- MUST return `ORACLE_UNAVAILABLE` (not `None`, not empty string, not empty dict) when no oracle is available.
- MUST NOT fabricate an oracle.
- The evaluator checks `isinstance(result, OracleUnavailable)` to detect absence.
- Oracle is NEVER automatically sent to LLM judges. It is used only by oracle-configured evaluation modes (exact match, schema, heuristic, reference-aware).

Default protocol implementation returns `ORACLE_UNAVAILABLE`. Adapters that support oracles override this method.

### `get_task_instance(instance_id: str, task_id: str) → dict[str, object] | None`

Returns per-instance task data, or `None` if not applicable. At minimum, the returned dict may contain a `"parameters"` key for template variable substitution during planning.

Default protocol implementation returns `None`.

### `tool_provider() → object | None`

Returns a domain-specific tool service for tool-mediated strategies, or `None`. If a tool-requiring strategy is selected and this returns `None`, the benchmark raises `CapabilityUnavailableError`.

Default protocol implementation returns `None`.

### `evaluation_helpers() → object | None`

Reserved for future use. Return `None` in v0.

### `strategy_descriptors() → list[StrategyDescriptor] | None`

Reserved for future use. Return `None` in v0.

---

## Capability → Benchmark Phase Mapping

| Phase | Condition | Capability |
|---|---|---|
| `plan` | always | `metadata`, `list_instance_ids`, `list_task_ids`, `get_task`, `get_task_instance` |
| `execute` | inline strategy | `get_context` |
| `execute` | tool-mediated strategy | `tool_provider` |
| `eval` | all modes | `get_evidence` |
| `eval` | oracle-configured mode | `get_oracle` |
| `export` / `status` | always | *(none — artifact-only)* |

---

## Error Types

| Error | Raised by | When |
|---|---|---|
| `AdapterUnavailableError(ValueError)` | `AdapterRegistry.resolve()` | No adapter registered for dataset identity |
| `CapabilityUnavailableError(ValueError)` | Benchmark lifecycle orchestrator | `tool_provider()` returns `None` for tool-requiring strategy |
| `UnsupportedRepresentationError(ValueError)` | Adapter's `get_context()` | Requested `representation` not supported |

---

## Registration

```python
# src/ctxbench/adapters/registry.py (only module allowed to register concrete adapters)
from ctxbench.adapters.lattes.package import LattesDatasetAdapter
from ctxbench.dataset.registry import AdapterRegistry

_registry = AdapterRegistry()
_registry.register(
    "ctxbench/lattes",
    lambda ref: LattesDatasetAdapter(ref.materialized_path or ref.root),
)

def get_default_registry() -> AdapterRegistry:
    return _registry
```

Registration is explicit and first-party. No dynamic loading, entry points, or plugin discovery.

---

## Import Boundaries

- `ctxbench.dataset.*` MUST NOT import from `ctxbench.adapters.*`
- `ctxbench.benchmark.*` MUST NOT import from `ctxbench.adapters.lattes.*` directly
- Only `ctxbench.adapters.registry` imports concrete adapter classes for registration

Enforced by `tests/test_import_boundaries.py`.

---

## Conformance Validation

Implement a `FakeDatasetAdapter` in `tests/test_fake_dataset_adapter.py` that satisfies all mandatory capabilities without touching real data:

```bash
pytest -k "fake_dataset or registry" -v
```

A conformant adapter:
- Returns `ContextPayload` from `get_context` with non-empty string `content` for supported representations
- Raises `UnsupportedRepresentationError` for unknown representations (not `KeyError`, not `FileNotFoundError`)
- Returns `EvidencePayload` from `get_evidence` with generic structure (no Lattes-specific keys required)
- Returns `ORACLE_UNAVAILABLE` (not `None`) from `get_oracle` when no oracle exists
- Returns `TaskPayload` with non-empty `statement` from `get_task`
- Satisfies `isinstance(adapter, DatasetPackage)` via structural subtyping
