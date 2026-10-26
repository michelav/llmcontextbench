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


def execute_runspec(runspec: TrialSpec, engine: Engine, *, local_mcp_runtime_decorator=None) -> TrialResult:
    adapter = _resolve_adapter(runspec)
    bridge = TrialRuntimeAdapter()
    runtime = ProvisioningRuntime(engine, adapter, local_mcp_runtime_decorator=local_mcp_runtime_decorator)
    return bridge.to_trial_result(runspec, runtime.execute(bridge.to_runtime_request(runspec)))


def _resolve_adapter(runspec: TrialSpec) -> DatasetPackage:
    try:
        return get_default_registry().resolve(runspec.dataset)
    except AdapterUnavailableError as exc:
        materialized_path = runspec.dataset.materialized_path
        if materialized_path and Path(materialized_path).exists():
            return LocalDatasetPackage.from_dataset(runspec.dataset)
        raise AdapterUnavailableError(str(exc)) from exc



# Kept for existing analysis callers during migration.
_build_metrics_summary = build_metrics_summary
