from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from ctxbench.adapters.registry import get_default_registry
from ctxbench.ai.engine import Engine
from ctxbench.benchmark.models import TrialResult, TrialSpec
from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.runtime.runtime import ProvisioningRuntime
from ctxbench.runtime.models import RuntimeRequest


def execute_runtime_request(
    request: RuntimeRequest,
    engine: Engine,
    dataset: DatasetPackage,
    *,
    local_mcp_runtime_decorator=None,
    runtime_interceptors: Mapping[str, Callable] | None = None,
):
    """Invoke a workflow-neutral runtime request through the shared provisioning runtime."""
    runtime = ProvisioningRuntime(
        engine, dataset,
        local_mcp_runtime_decorator=local_mcp_runtime_decorator,
        runtime_interceptors=runtime_interceptors,
    )
    return runtime.execute(request)


def resolve_trial_dataset(runspec: TrialSpec) -> DatasetPackage:
    try:
        return get_default_registry().resolve(runspec.dataset)
    except AdapterUnavailableError as exc:
        materialized_path = runspec.dataset.materialized_path
        if materialized_path and Path(materialized_path).exists():
            return LocalDatasetPackage.from_dataset(runspec.dataset)
        raise AdapterUnavailableError(str(exc)) from exc
