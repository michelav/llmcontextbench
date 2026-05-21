from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.package import DatasetMetadata, DatasetPackage, StrategyDescriptor


_MANDATORY_METHODS = (
    "metadata",
    "identity",
    "version",
    "origin",
    "list_instance_ids",
    "list_task_ids",
    "get_task",
    "get_context",
    "get_evidence",
    "capability_report",
)

_OPTIONAL_METHODS = (
    "get_oracle",
    "get_task_instance",
    "tool_provider",
    "fixtures",
)

_DESCRIPTOR_FIELDS = (
    "name",
    "classification",
    "context_access_mode",
    "inline_vs_operation",
    "local_vs_remote",
    "loop_ownership",
    "metric_provenance",
    "observability_limitations",
    "comparability_implications",
)


def _is_callable_method(package: object, name: str) -> bool:
    return callable(getattr(package, name, None))


def _safe_call(package: object, name: str, default: Any = None) -> Any:
    method = getattr(package, name, None)
    if not callable(method):
        return default
    return method()


def _descriptor_payload(descriptor: object) -> dict[str, Any]:
    if isinstance(descriptor, StrategyDescriptor):
        return asdict(descriptor)
    if is_dataclass(descriptor):
        return asdict(descriptor)
    if isinstance(descriptor, dict):
        return dict(descriptor)
    return {field: getattr(descriptor, field) for field in _DESCRIPTOR_FIELDS if hasattr(descriptor, field)}


def validate_package(package: DatasetPackage) -> DatasetCapabilityReport:
    mandatory = {name: _is_callable_method(package, name) for name in _MANDATORY_METHODS}
    optional = {name: _is_callable_method(package, name) for name in _OPTIONAL_METHODS}
    missing_mandatory = [name for name, available in mandatory.items() if not available]

    identity = _safe_call(package, "identity", "unknown")
    version = _safe_call(package, "version", "unknown")
    origin = _safe_call(package, "origin", None)
    metadata = _safe_call(
        package,
        "metadata",
        DatasetMetadata(
            name=str(identity),
            description="Dataset package metadata unavailable.",
            domain="unknown",
            intended_uses="Unknown",
            limitations="Metadata method unavailable.",
            license_url=None,
            citation_url=None,
        ),
    )
    contributed_tools = _safe_call(package, "tool_provider", None)
    evaluation_helpers = _safe_call(package, "evaluation_helpers", None)
    raw_descriptors = _safe_call(package, "strategy_descriptors", None) or []

    strategy_descriptors: list[StrategyDescriptor] = []
    nonconformant_descriptors: list[str] = []
    for raw_descriptor in raw_descriptors:
        payload = _descriptor_payload(raw_descriptor)
        missing_fields = [field for field in _DESCRIPTOR_FIELDS if field not in payload]
        if missing_fields:
            descriptor_name = payload.get("name", "<unknown>")
            nonconformant_descriptors.append(
                f"{descriptor_name}: missing {', '.join(missing_fields)}"
            )
            continue
        strategy_descriptors.append(StrategyDescriptor(**payload))

    return DatasetCapabilityReport(
        identity=str(identity),
        version=str(version),
        origin=str(origin) if origin is not None else None,
        resolved_revision=None,
        materialized_path=None,
        content_hash=None,
        metadata=metadata,
        mandatory_capabilities=mandatory,
        optional_capabilities=optional,
        contributed_tools=contributed_tools,
        evaluation_helpers=evaluation_helpers,
        strategy_descriptors=strategy_descriptors,
        missing_mandatory=missing_mandatory,
        nonconformant_descriptors=nonconformant_descriptors,
        conformant=not missing_mandatory and not nonconformant_descriptors,
    )
