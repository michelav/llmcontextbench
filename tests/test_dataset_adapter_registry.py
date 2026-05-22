from __future__ import annotations

import pytest

from ctxbench.adapters.lattes.package import LattesDatasetAdapter
from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.models import DatasetProvenance, ExperimentDataset
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetMetadata
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    OracleUnavailable,
    TaskPayload,
)
from ctxbench.dataset.registry import AdapterRegistry, ResolvedDatasetRef


LATTES_FIXTURE_ROOT = "tests/fixtures/lattes_provider_free/dataset"


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


def test_default_registry_resolves_lattes_adapter_from_experiment_dataset() -> None:
    adapter = get_default_registry().resolve(
        ExperimentDataset(
            id="ctxbench/lattes",
            version="2026-04-28",
            root=LATTES_FIXTURE_ROOT,
            origin="provider-free fixture",
        )
    )

    assert isinstance(adapter, LattesDatasetAdapter)


def test_default_registry_resolves_lattes_adapter_from_dataset_provenance() -> None:
    adapter = get_default_registry().resolve(
        DatasetProvenance(
            id="ctxbench/lattes",
            version="2026-04-28",
            origin="provider-free fixture",
            content_hash="sha256:test-fixture",
            materialized_path=LATTES_FIXTURE_ROOT,
        )
    )

    assert isinstance(adapter, LattesDatasetAdapter)


def test_default_registry_resolve_unknown_dataset_id_raises_adapter_unavailable() -> None:
    with pytest.raises(AdapterUnavailableError):
        get_default_registry().resolve(
            ExperimentDataset(
                id="ctxbench/unknown",
                version="0.1.0",
                root=LATTES_FIXTURE_ROOT,
            )
        )


def test_oracle_unavailable_singleton_is_oracle_unavailable() -> None:
    assert isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)
