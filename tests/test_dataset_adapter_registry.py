from __future__ import annotations

import pytest

from ctxbench.benchmark.models import DatasetProvenance, ExperimentDataset
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import ContextPayload, EvidencePayload, TaskPayload
from ctxbench.dataset.registry import AdapterRegistry, ResolvedDatasetRef


class DummyDatasetPackage:
    def metadata(self) -> DatasetMetadata:
        return DatasetMetadata(
            name="Dummy",
            description="Dummy adapter for registry tests.",
            domain="testing",
            intended_uses="Unit tests",
            limitations="None",
            license_url=None,
            citation_url=None,
        )

    def identity(self) -> str:
        return "ctxbench/dummy"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["inst-001"]

    def list_task_ids(self) -> list[str]:
        return ["task-001"]

    def get_task(self, task_id: str) -> TaskPayload:
        return TaskPayload(task_id=task_id, statement="Dummy task")

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload:
        return ContextPayload(role="context", representation=representation, content={})

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        return EvidencePayload(role="evidence", task={}, evidence={})

    def capability_report(self) -> object:
        return object()


def test_resolved_dataset_ref_is_constructable_with_required_fields() -> None:
    ref = ResolvedDatasetRef(id="ctxbench/dummy", version="0.1.0")

    assert ref.id == "ctxbench/dummy"
    assert ref.version == "0.1.0"
    assert ref.root is None


def test_adapter_registry_resolve_raises_for_unknown_id() -> None:
    registry = AdapterRegistry()

    with pytest.raises(AdapterUnavailableError):
        registry.resolve(ExperimentDataset(id="ctxbench/unknown", version="0.1.0"))


def test_adapter_registry_resolve_raises_for_missing_id() -> None:
    registry = AdapterRegistry()

    with pytest.raises(AdapterUnavailableError):
        registry.resolve(ExperimentDataset(root="/tmp/dataset"))


def test_adapter_registry_register_accepts_factory_and_resolves_experiment_dataset() -> None:
    registry = AdapterRegistry()
    package = DummyDatasetPackage()
    captured: list[ResolvedDatasetRef] = []

    def factory(ref: ResolvedDatasetRef) -> DummyDatasetPackage:
        captured.append(ref)
        return package

    registry.register("ctxbench/dummy", factory)

    resolved = registry.resolve(
        ExperimentDataset(
            id="ctxbench/dummy",
            version="0.1.0",
            root="/datasets/dummy",
            origin="local",
        )
    )

    assert resolved is package
    assert captured == [
        ResolvedDatasetRef(
            id="ctxbench/dummy",
            version="0.1.0",
            root="/datasets/dummy",
            origin="local",
        )
    ]


def test_adapter_registry_resolves_dataset_provenance_materialization_fields() -> None:
    registry = AdapterRegistry()
    package = DummyDatasetPackage()
    captured: list[ResolvedDatasetRef] = []

    def factory(ref: ResolvedDatasetRef) -> DummyDatasetPackage:
        captured.append(ref)
        return package

    registry.register("ctxbench/dummy", factory)

    resolved = registry.resolve(
        DatasetProvenance(
            id="ctxbench/dummy",
            version="0.1.0",
            origin="cache",
            content_hash="sha256:abc",
            materialized_path="/cache/dummy",
        )
    )

    assert resolved is package
    assert captured == [
        ResolvedDatasetRef(
            id="ctxbench/dummy",
            version="0.1.0",
            root="/cache/dummy",
            origin="cache",
            content_hash="sha256:abc",
            materialized_path="/cache/dummy",
        )
    ]
