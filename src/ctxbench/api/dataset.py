"""Public helpers for inspecting a locally available dataset before planning."""
from pathlib import Path
from typing import Any

from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.resolver import DatasetResolver
from ctxbench.dataset.validation import validate_package
from ctxbench.workload.builder import DatasetHandle


def load_dataset(ref: str | Path | dict[str, Any], *, cache_dir: str | Path | None = None) -> DatasetHandle:
    """Resolve a local dataset and expose the metadata needed to build workloads.

    Resolution is local-only: this function does not fetch or materialize datasets.
    """
    from ctxbench.adapters.registry import get_default_registry
    from ctxbench.dataset.errors import AdapterUnavailableError

    reference = str(ref) if isinstance(ref, Path) else ref
    resolved = DatasetResolver().resolve_for_planning(reference, DatasetCache(cache_dir=cache_dir))
    try:
        package = get_default_registry().resolve(resolved.adapter_ref)
    except AdapterUnavailableError:
        package = resolved.package
    validate_package(package)
    report = package.capability_report()
    return DatasetHandle(
        package=package,
        feature_schema=report.request_feature_schema,
        task_ids=tuple(package.list_task_ids()),
        instance_ids=tuple(package.list_instance_ids()),
    )


__all__ = ["load_dataset"]
