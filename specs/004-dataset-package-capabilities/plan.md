# Plan: Dataset Package Capabilities and Core/Adapter Boundary

**Branch**: `feat/dataset-boundaries-capabilities` | **Date**: 2026-05-19 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/004-dataset-package-capabilities/spec.md`

## Summary

Introduce the Adapter Registry v0 to replace the ad-hoc `_specialized_local_dataset_package` branch in `provider.py`. Define error types and an oracle sentinel. Add `get_task` and `get_oracle` to the `DatasetPackage` protocol. Thread `executor.py` and `evaluation.py` through the adapter contract instead of calling Lattes-specific methods directly. Move `FORMAT_ARTIFACTS` out of the core and into the Lattes adapter. The Lattes adapter remains inside `ctxbench-cli` as a temporary in-repo adapter (FR-009); `runspec_generator.py`'s deep coupling to `LocalDatasetPackage` is within the permitted temporary-adapter scope and is deferred to Spec 006.

## Decisions

- Keep `DatasetPackage` protocol in `package.py`; add `get_task` and `get_oracle` to it.
- `OracleUnavailable` is a sentinel class (not `None`, not empty dict) in `errors.py`.
- Registry maps `dataset_id: str → factory: Callable[[str], DatasetPackage]`.
- Registry is wired at import time with one explicit registration for `"ctxbench/lattes"`. No lazy loading, no entry points.
- `FORMAT_ARTIFACTS` moves from `provider.py` to `lattes/package.py`.
- `_specialized_local_dataset_package` is removed; the registry replaces it.
- `executor.py` gets the adapter from the registry (once per run via a lazy-resolve helper) and calls `get_context_artifact` instead of `get_context` / `get_context_artifact_path` / `get_instance_dir`.
- `evaluation.py` gets the adapter from the registry and calls `get_evidence_artifact` instead of `get_question` / `get_context_blocks`.
- `commands/plan.py` still uses `DatasetResolver` for local-file resolution; registry is invoked after resolution to validate and report adapter conformance.
- `runspec_generator.py` still accepts `LocalDatasetPackage` (temp adapter scope); no changes there.
- Tool availability check uses `CapabilityUnavailableError` raised by the executor when `adapter.tool_provider()` returns `None` for a tool-requiring strategy.
- `lattes_id` label in `executor.py` is renamed to `instance_id`; strategies already fall back to `instance_id` in metadata.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: pyproject.toml, flake.nix  
**Storage**: local JSON/JSONL artifacts only  
**Testing**: pytest, provider-free fixtures/mocks  
**Target Platform**: CLI  
**Project Type**: single Python CLI project  
**Constraints**: provider-free validation; no full benchmark unless explicitly approved  
**Scale/Scope**: medium — touches 6 existing files, adds 2 new files, ~200 lines of net change

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| Phase separation | pass | Registry resolves once per run before any lifecycle phase |
| Cost/evaluation separation | pass | No cost-tracking changes |
| Metric provenance | pass | No metric changes |
| Artifact contracts | pass | No artifact format changes; `dataset` provenance fields unchanged |
| Strategy comparability | pass | No changes to strategy semantics |
| Dataset/domain isolation | **core purpose** | This spec enforces the boundary |
| Provider isolation | pass | No provider adapter changes |
| Provider-free validation | pass | FakeDatasetAdapter fixture validates contract without real data |
| Documentation impact | pass | CLAUDE.md active-plan pointer updated |
| Simplicity / research sufficiency | pass | Registry is a dict; no plugin machinery; no new abstraction layers |

## Files Likely Affected

New:
- `src/ctxbench/dataset/errors.py` — error types + `OracleUnavailable`
- `src/ctxbench/dataset/registry.py` — `AdapterRegistry` v0
- `tests/test_dataset_adapter_errors.py` — error type + sentinel tests
- `tests/test_dataset_adapter_registry.py` — registry tests

Modified:
- `src/ctxbench/dataset/package.py` — add `get_task`, `get_oracle` to protocol
- `src/ctxbench/dataset/provider.py` — remove `FORMAT_ARTIFACTS`, remove `_specialized_local_dataset_package`, add `get_task`/`get_oracle` to `LocalDatasetPackage`
- `src/ctxbench/datasets/lattes/package.py` — own `FORMAT_ARTIFACTS`, add `get_task`/`get_oracle`
- `src/ctxbench/benchmark/executor.py` — use registry + `get_context_artifact`; rename `lattes_id` to `instance_id`; use `CapabilityUnavailableError`
- `src/ctxbench/benchmark/evaluation.py` — use registry + `get_evidence_artifact`
- `src/ctxbench/commands/plan.py` — use registry after resolver for conformance logging
- `CLAUDE.md` — update active-plan pointer to this file

Not changing:
- `src/ctxbench/commands/export.py` — operates on artifacts (FR-048)
- `src/ctxbench/commands/status.py` — operates on artifacts (FR-049)
- `src/ctxbench/commands/eval.py` — orchestration unchanged; inner `evaluation.py` changes cover boundary
- `src/ctxbench/benchmark/runspec_generator.py` — temp-adapter coupling; deferred to Spec 006
- `src/ctxbench/dataset/resolver.py` — S3 materialization resolver; separate concern
- `src/ctxbench/ai/strategies/` — `lattes_id` vs `instance_id` fallback already in place; rename at metadata source in executor covers it

## Implementation Slices

| Slice | Goal | Likely files | Validation | Depends on |
|---|---|---|---|---|
| S1 | Error types + `OracleUnavailable` sentinel | `errors.py` (new), `package.py` | `pytest -k adapter_errors or dataset_package_contract` | — |
| S2 | Adapter Registry v0 | `registry.py` (new), `provider.py`, `lattes/package.py` | `pytest -k registry or dataset_local_package or lattes_dataset` | S1 |
| S3 | Executor boundary fix | `executor.py` | `pytest -k execute or lifecycle_no_network` | S2 |
| S4 | Evaluator boundary fix | `evaluation.py` | `pytest -k eval` | S2 |
| S5 | Plan command registry wiring | `commands/plan.py` | `pytest -k plan or cli` | S2 |
| S6 | Fake adapter conformance fixture + registry tests | `tests/test_dataset_adapter_registry.py`, `tests/test_fake_dataset_adapter.py` (update or new) | `pytest -k registry or fake_dataset` | S1, S2 |

Slice rules applied: S3 and S4 are independent once S2 is green and can be implemented in parallel.

### Slice detail: S1 — Error types

`src/ctxbench/dataset/errors.py`:
```
AdapterUnavailableError(ValueError)  # registry can't resolve dataset identity
CapabilityUnavailableError(ValueError)  # adapter lacks requested capability
UnsupportedRepresentationError(ValueError)  # adapter can't serve requested format

class OracleUnavailable:
    """Sentinel returned when no oracle is available for a task instance."""
    # singleton: ORACLE_UNAVAILABLE = OracleUnavailable()
```

`src/ctxbench/dataset/package.py` additions to `DatasetPackage` protocol:
```python
def get_task(self, task_id: str) -> object: ...
def get_oracle(self, instance_id: str, task_id: str) -> object: ...
```

### Slice detail: S2 — Adapter Registry v0

`src/ctxbench/dataset/registry.py`:
```python
class AdapterRegistry:
    def register(self, dataset_id: str, factory: Callable[[str], DatasetPackage]) -> None: ...
    def resolve(self, dataset_ref: ExperimentDataset) -> DatasetPackage: ...
        # raises AdapterUnavailableError if no adapter for dataset_ref.id

_default_registry = AdapterRegistry()
# wired at module import:
_default_registry.register("ctxbench/lattes", lambda root: LattesDatasetPackage(root))

def get_default_registry() -> AdapterRegistry: ...
```

`src/ctxbench/dataset/provider.py` changes:
- Remove `FORMAT_ARTIFACTS` dict
- Remove `_specialized_local_dataset_package` function
- Remove the `specialized` branch in `from_dataset`
- Add `get_task(task_id)` → delegates to `get_question(task_id)`
- Add `get_oracle(instance_id, task_id)` → returns `ORACLE_UNAVAILABLE`

`src/ctxbench/datasets/lattes/package.py` changes:
- Add `FORMAT_ARTIFACTS` dict (moved from provider)
- Override `get_context_artifact` to use own `FORMAT_ARTIFACTS`
- Add `get_task(task_id)` → delegates to inherited `get_question`
- Add `get_oracle(instance_id, task_id)` → returns `ORACLE_UNAVAILABLE` (no oracle in v0)

### Slice detail: S3 — Executor boundary fix

`src/ctxbench/benchmark/executor.py` before (boundary violations):
```python
provider = DatasetProvider.from_dataset(runspec.dataset)
context = provider.get_context(runspec.instanceId, runspec.format)
context_path = provider.get_context_artifact_path(runspec.instanceId, runspec.format)
instance_dir = provider.get_instance_dir(runspec.instanceId)
lattes_id = runspec.instanceId
...
metadata={"lattes_id": lattes_id, "instance_dir": ..., "context_path": ...}
```

After (through adapter):
```python
adapter = get_default_registry().resolve(runspec.dataset)
context = adapter.get_context_artifact(runspec.instanceId, runspec.questionId, runspec.strategy, runspec.format)
...
metadata={"instance_id": runspec.instanceId, ...}
# context_path and instance_dir removed from core metadata; Lattes-internal details
```

Tool capability check (existing `_build_tool_runtime_factories` function):
```python
# Replace:
raise ValueError(f"Strategy '{runspec.strategy}' requires a dataset tool provider.")
# With:
from ctxbench.dataset.errors import CapabilityUnavailableError
raise CapabilityUnavailableError(
    f"Strategy '{runspec.strategy}' requires tool capability; "
    f"adapter for '{runspec.dataset.id}' does not provide tools."
)
```

### Slice detail: S4 — Evaluator boundary fix

`src/ctxbench/benchmark/evaluation.py` before:
```python
provider = DatasetProvider.from_dataset(result.dataset)
question = provider.get_question(result.questionId)
all_blocks = provider.get_context_blocks(result.instanceId)
```

After:
```python
adapter = get_default_registry().resolve(result.dataset)
evidence = adapter.get_evidence_artifact(result.instanceId, result.questionId)
# evidence is a dict: {"question": ..., "questionInstance": ..., "contextBlocks": ...}
question_data = evidence["question"]
all_blocks = evidence["contextBlocks"]
```

This changes the type from a `Question` model to a plain dict. The downstream code (`question.contextBlock`, `question.validation.type`) needs updating to use `question_data["contextBlock"]` etc. This is acceptable: the adapter's evidence payload is opaque to the core; the evaluator unpacks it.

### Slice detail: S5 — Plan command registry wiring

`src/ctxbench/commands/plan.py`:
- Keep `DatasetResolver` for local file resolution (S3 concern)
- After resolving: call `registry.resolve(resolved_ref)` to get the adapter for conformance validation (instead of direct `isinstance(package, LocalDatasetPackage)` check)
- Log conformance through adapter's `capability_report()`

### Slice detail: S6 — Conformance fixture

`tests/test_dataset_adapter_registry.py`:
- Registry registers and resolves Lattes adapter
- Registry raises `AdapterUnavailableError` for unknown dataset identity
- Registry raises `AdapterUnavailableError` when no id given

`tests/test_fake_dataset_adapter.py` (update or create):
- `FakeDatasetAdapter` implementing full `DatasetPackage` protocol (v0 contract)
- Tests: all mandatory capabilities return correct types
- Tests: `get_oracle` returns `ORACLE_UNAVAILABLE` sentinel
- Tests: error types are `ValueError` subclasses

## Migration Impact

| Surface | Impact |
|---|---|
| Experiment definitions | None — `dataset.id`, `dataset.root`, `factors.format` unchanged |
| Artifact schemas | None — `trials.jsonl`, `responses.jsonl`, `evals.jsonl` unchanged |
| CLI behavior | None — same commands, same flags |
| Lattes adapter internal | `FORMAT_ARTIFACTS` moves to `lattes/package.py`; behavior identical |
| `context_path` metadata field | Removed from executor metadata; not consumed by any strategy (verified by grep) |
| `instance_dir` metadata field | Removed from executor metadata; not consumed by any strategy (verified by grep) |
| `lattes_id` metadata field | Renamed to `instance_id`; strategies already fall back to `instance_id` in `_resolve_lattes_id` |
| `DatasetProvider.from_dataset` | Still present for callers; internal behavior simplified (no `_specialized_local_dataset_package`) |
| Test: `test_dataset_package_contract.py` | `get_task` and `get_oracle` added to `CompleteDatasetPackage` test fixture |

## Architectural Impact

- **Core/adapter boundary**: The `FORMAT_ARTIFACTS` filename table moves fully inside the Lattes adapter. Generic code no longer maps format names to filenames.
- **Registry as single binding point**: After this change, `dataset.id == "ctxbench/lattes"` appears only inside `registry.py` (the registration call) and inside the `lattes/` package itself.
- **Executor thread**: `executor.py` no longer imports from `ctxbench.dataset.provider`. It imports from `ctxbench.dataset.registry` and calls `DatasetPackage` protocol methods.
- **Evaluator thread**: `evaluation.py` no longer calls `get_question` or `get_context_blocks`. It calls `get_evidence_artifact` and unpacks the returned dict.
- **Remaining coupling**: `runspec_generator.py` and `commands/plan.py`'s use of `LocalDatasetPackage.list_question_ids()`, `get_question()`, `get_question_instance()` is within the permitted temporary in-repo adapter scope (FR-009) and is the primary target of Spec 006.

## Documentation Impact

- CLAUDE.md: update active-plan pointer to `specs/004-dataset-package-capabilities/plan.md`
- No CLI help or README changes required

## Risks

- **Evaluation evidence dict shape**: After S4, `evaluation.py` unpacks `evidence["question"]` as a plain dict instead of a `Question` model. Field access like `.contextBlock` becomes `["contextBlock"]`. Risk of missing a field access — mitigated by running `pytest -k eval` after S4.
- **`context_path` removal from metadata**: Removing `context_path` and `instance_dir` from executor metadata could break tooling or scripts that read raw trace files. Mitigation: grep confirms no strategy code reads these fields; they're trace-only extras.
- **Registry import at module level**: Wiring `LattesDatasetPackage` at registry import time means the lattes module is always imported. Currently this is already the case via `_specialized_local_dataset_package`. No new risk.
- **`get_context_artifact` signature change**: `executor.py` currently calls `provider.get_context(instanceId, format)` (not the protocol method). After the fix it calls `adapter.get_context_artifact(instanceId, taskId, strategy, format)`. The Lattes adapter's inherited implementation ignores `task_id` and `strategy`; this is fine for v0 but should be noted in the trace.
- **`evaluation.py` provider cache**: The evaluation phase caches providers by `(id, version, path)` key. After the fix, the same key is used with `registry.resolve`. Registry should be stateless (no caching needed); the evaluation caching can be removed or kept as-is.

## Validation

Provider-free validation (no real provider calls required):

```bash
# After S1:
pytest -k "adapter_errors or dataset_package_contract" -v

# After S2:
pytest -k "registry or dataset_local_package or lattes_dataset_package" -v

# After S3:
pytest -k "execute or lifecycle_no_network" -v

# After S4:
pytest -k "eval" -v

# After S5:
pytest -k "plan or cli" -v

# After S6 (full):
pytest -k "adapter or dataset or fake or registry" -v
pytest tests/ -x --ignore=tests/fixtures
```

No real LLM provider call is required at any slice boundary.

## Process Logging

This is a Level 2 change (touches multiple lifecycle phases, introduces a new abstraction). Create:
- `specs/004-dataset-package-capabilities/worklog.md` — record slice completions and decisions
- Skip `usage.jsonl` unless token tracking becomes useful

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `runspec_generator.py` still uses `LocalDatasetPackage` | Temp adapter scope (FR-009) | Full domain-neutral runspec generation requires Spec 006 Lattes extraction |
| `evaluation.py` evidence dict unpack | Adapter boundary crossed; dict is opaque payload | Returning a typed model would leak Lattes schema into the core |
