from __future__ import annotations

import pytest

from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.errors import UnsupportedRepresentationError
from ctxbench.dataset.package import DatasetMetadata, DatasetPackage
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    TaskPayload,
)


class FakeDatasetAdapter:
    def __init__(self) -> None:
        self._task = TaskPayload(
            task_id="task-001",
            statement="Summarize the profile.",
            tags=["fixture"],
            validation_type="judge",
            context_blocks=["profile"],
        )

    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name="Fake Dataset",
            description="Provider-free in-memory adapter fixture.",
            domain="testing",
            intended_uses="Adapter conformance tests",
            limitations="Not a real benchmark dataset",
            license_url=None,
            citation_url=None,
        )

    def identity(self) -> str:
        return "ctxbench/fake"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["inst-001"]

    def list_task_ids(self) -> list[str]:
        return [self._task.task_id]

    def get_task(self, task_id: str) -> TaskPayload:
        if task_id != self._task.task_id:
            raise KeyError(task_id)
        return self._task

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload:
        if instance_id != "inst-001":
            raise KeyError(instance_id)
        self.get_task(task_id)
        if representation != "text":
            raise UnsupportedRepresentationError(
                f"Unsupported fake representation: {representation}"
            )
        return ContextPayload(
            role="context",
            representation=representation,
            content="Profile context for the fake adapter.",
            content_type="text/plain",
        )

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        if instance_id != "inst-001":
            raise KeyError(instance_id)
        task = self.get_task(task_id)
        return EvidencePayload(
            role="evidence",
            task={"task_id": task.task_id, "statement": task.statement},
            evidence={"profile": "Evidence text for the fake adapter."},
        )

    def capability_report(self) -> DatasetCapabilityReport:
        return DatasetCapabilityReport(
            identity=self.identity(),
            version=self.version(),
            origin=self.origin(),
            resolved_revision=None,
            materialized_path=None,
            content_hash=None,
            metadata=self.metadata(),
            mandatory_capabilities={
                "metadata": True,
                "list_instances": True,
                "list_tasks": True,
                "get_task": True,
                "get_context": True,
                "get_evidence": True,
            },
            optional_capabilities={
                "get_oracle": True,
                "get_task_instance": True,
                "tool_provider": True,
                "fixtures": True,
            },
            contributed_tools=None,
            evaluation_helpers=None,
            strategy_descriptors=[],
            missing_mandatory=[],
            nonconformant_descriptors=[],
            conformant=True,
        )

    def get_oracle(self, instance_id: str, task_id: str) -> object:
        if instance_id != "inst-001":
            raise KeyError(instance_id)
        self.get_task(task_id)
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        if instance_id != "inst-001":
            raise KeyError(instance_id)
        self.get_task(task_id)
        return {"parameters": {}}

    def tool_provider(self) -> object | None:
        return None

    def fixtures(self) -> object | None:
        return {"instances": self.list_instance_ids(), "tasks": self.list_task_ids()}


def test_fake_dataset_adapter_satisfies_dataset_package_protocol() -> None:
    assert isinstance(FakeDatasetAdapter(), DatasetPackage)


def test_fake_dataset_adapter_get_context_unsupported_representation_raises() -> None:
    adapter = FakeDatasetAdapter()

    with pytest.raises(UnsupportedRepresentationError):
        adapter.get_context("inst-001", "task-001", "html")


def test_fake_dataset_adapter_get_oracle_returns_unavailable_sentinel() -> None:
    oracle = FakeDatasetAdapter().get_oracle("inst-001", "task-001")

    assert oracle is ORACLE_UNAVAILABLE
    assert oracle is not None


def test_fake_dataset_adapter_get_task_returns_non_empty_statement() -> None:
    task = FakeDatasetAdapter().get_task("task-001")

    assert isinstance(task, TaskPayload)
    assert task.statement


def test_fake_dataset_adapter_get_evidence_returns_evidence_payload() -> None:
    evidence = FakeDatasetAdapter().get_evidence("inst-001", "task-001")

    assert isinstance(evidence, EvidencePayload)
    assert evidence.role == "evidence"
