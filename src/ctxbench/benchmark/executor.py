from __future__ import annotations

from pathlib import Path

from ctxbench.adapters.registry import get_default_registry
from ctxbench.ai.engine import Engine
from ctxbench.benchmark.models import TrialResult, TrialSpec
from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter, build_metrics_summary
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.runtime.runtime import ProvisioningRuntime
from ctxbench.runtime.models import RuntimeRequest


def execute_runspec(runspec: TrialSpec, engine: Engine, *, local_mcp_runtime_decorator=None) -> TrialResult:
    adapter = resolve_trial_dataset(runspec)
    bridge = TrialRuntimeAdapter()
    execution = execute_runtime_request(
        bridge.to_runtime_request(runspec), engine, adapter,
        local_mcp_runtime_decorator=local_mcp_runtime_decorator,
    )
    return bridge.to_trial_result(runspec, execution)


def execute_runtime_request(
    request: RuntimeRequest,
    engine: Engine,
    dataset: DatasetPackage,
    *,
    local_mcp_runtime_decorator=None,
):
    """Invoke a workflow-neutral runtime request through the shared provisioning runtime."""
    runtime = ProvisioningRuntime(engine, dataset, local_mcp_runtime_decorator=local_mcp_runtime_decorator)
    return runtime.execute(request)


def _resolve_adapter(runspec: TrialSpec) -> DatasetPackage:
    try:
        return get_default_registry().resolve(runspec.dataset)
    except AdapterUnavailableError as exc:
        materialized_path = runspec.dataset.materialized_path
        if materialized_path and Path(materialized_path).exists():
            return LocalDatasetPackage.from_dataset(runspec.dataset)
        raise AdapterUnavailableError(str(exc)) from exc


def resolve_trial_dataset(runspec: TrialSpec) -> DatasetPackage:
    """Resolve the dataset dependency at the benchmark-to-runtime boundary."""
    return _resolve_adapter(runspec)



# Kept for existing analysis callers during migration.
_build_metrics_summary = build_metrics_summary
