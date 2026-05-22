from __future__ import annotations

import pytest

from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.package import DatasetMetadata, DatasetPackage, StrategyDescriptor
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    TaskPayload,
)


def _metadata() -> DatasetMetadata:
    return DatasetMetadata(
        name="Fake Dataset",
        description="Synthetic dataset for contract testing.",
        domain="testing",
        intended_uses="Protocol and capability checks.",
        limitations="Not a real benchmark dataset.",
        license_url=None,
        citation_url=None,
    )


def _capability_report(*, conformant: bool = True) -> DatasetCapabilityReport:
    return DatasetCapabilityReport(
        identity="ctxbench/fake",
        version="0.1.0",
        origin=None,
        resolved_revision=None,
        materialized_path=None,
        content_hash=None,
        metadata=_metadata(),
        mandatory_capabilities={"instances": True, "tasks": True},
        optional_capabilities={
            "get_oracle": True,
            "get_task_instance": True,
            "tool_provider": False,
            "fixtures": True,
        },
        contributed_tools=None,
        evaluation_helpers=None,
        strategy_descriptors=[],
        missing_mandatory=[] if conformant else ["get_evidence"],
        nonconformant_descriptors=[],
        conformant=conformant,
    )


class CompleteDatasetPackage:
    def metadata(self) -> DatasetMetadata:
        return _metadata()

    def identity(self) -> str:
        return "ctxbench/fake"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["inst-001"]

    def list_task_ids(self) -> list[str]:
        return ["task-001"]

    def get_task(self, task_id: str) -> TaskPayload:
        return TaskPayload(task_id=task_id, statement="What year?")

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload:
        return ContextPayload(
            role="context",
            representation=representation,
            content={"instance": instance_id, "task": task_id},
        )

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        return EvidencePayload(
            role="evidence",
            task={"task_id": task_id},
            evidence={"instance": instance_id},
        )

    def capability_report(self) -> DatasetCapabilityReport:
        return _capability_report()

    def tool_provider(self) -> object | None:
        return None

    def get_oracle(self, instance_id: str, task_id: str) -> object:
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        return None

    def fixtures(self) -> object:
        return {"fixture": "ok"}


class MissingMandatoryMethod:
    def metadata(self) -> DatasetMetadata:
        return _metadata()

    def identity(self) -> str:
        return "ctxbench/fake"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["inst-001"]

    def list_task_ids(self) -> list[str]:
        return ["task-001"]

    def get_task(self, task_id: str) -> TaskPayload:
        return TaskPayload(task_id=task_id, statement="What year?")

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload:
        return ContextPayload(
            role="context",
            representation=representation,
            content={"instance": instance_id, "task": task_id},
        )

    def capability_report(self) -> DatasetCapabilityReport:
        return _capability_report(conformant=False)

    def tool_provider(self) -> object | None:
        return None

    def get_oracle(self, instance_id: str, task_id: str) -> object:
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        return None

    def fixtures(self) -> object:
        return {"fixture": "ok"}


def test_dataset_package_protocol_accepts_complete_implementation() -> None:
    assert isinstance(CompleteDatasetPackage(), DatasetPackage)


def test_dataset_package_protocol_rejects_missing_mandatory_method() -> None:
    assert not isinstance(MissingMandatoryMethod(), DatasetPackage)


def test_strategy_descriptor_accepts_all_required_fields() -> None:
    descriptor = StrategyDescriptor(
        name="inline",
        classification="canonical",
        context_access_mode="inline-context",
        inline_vs_operation="inline",
        local_vs_remote="local",
        loop_ownership="benchmark",
        metric_provenance={"totalTokens": "reported"},
        observability_limitations="None",
        comparability_implications="Comparable with canonical inline runs.",
    )

    assert descriptor.name == "inline"
    assert descriptor.metric_provenance == {"totalTokens": "reported"}


def test_strategy_descriptor_missing_required_field_raises_type_error() -> None:
    with pytest.raises(TypeError):
        StrategyDescriptor(
            name="inline",
            classification="canonical",
            context_access_mode="inline-context",
            inline_vs_operation="inline",
            local_vs_remote="local",
            loop_ownership="benchmark",
            metric_provenance={"totalTokens": "reported"},
            observability_limitations="None",
        )


def test_dataset_capability_report_represents_nonconformant_package() -> None:
    report = _capability_report(conformant=False)

    assert report.conformant is False
    assert report.missing_mandatory == ["get_evidence"]
