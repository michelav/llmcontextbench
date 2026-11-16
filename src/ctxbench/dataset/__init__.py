"""Dataset and provider helpers, lazily exported to keep shared contracts acyclic."""
from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "AmbiguousDatasetError": "conflicts",
    "DatasetCache": "cache",
    "DatasetConflictDetector": "conflicts",
    "DatasetConflictError": "cache",
    "DatasetCapabilityReport": "capabilities",
    "FeatureCapability": "capabilities",
    "FeaturePartitionCapability": "capabilities",
    "DatasetMetadata": "package",
    "DatasetNotFoundError": "resolver",
    "DatasetPackage": "package",
    "DatasetProvenance": "provenance",
    "DatasetResolver": "resolver",
    "LocalDatasetPackage": "provider",
    "MaterializationManifest": "materialization",
    "MultiDatasetError": "resolver",
    "RequestFeatureSchema": "capabilities",
    "SignalCapability": "capabilities",
    "SignalCost": "capabilities",
    "StrategyDescriptor": "package",
    "build_inspect_result": "inspect",
    "validate_package": "validation",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"ctxbench.dataset.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
