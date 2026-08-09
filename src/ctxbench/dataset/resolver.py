from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ctxbench.benchmark.models import DatasetProvenance, ExperimentDataset
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.capabilities import DatasetCapabilityReport
from ctxbench.dataset.conflicts import DatasetConflictDetector
from ctxbench.dataset.materialization import MaterializationManifest
from ctxbench.dataset.package import DatasetMetadata, DatasetPackage
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    OracleUnavailable,
    TaskPayload,
)
from ctxbench.dataset.provider import LocalDatasetPackage


class DatasetNotFoundError(FileNotFoundError):
    """Raised when a dataset reference cannot be resolved locally."""


class MultiDatasetError(ValueError):
    """Raised when a dataset reference attempts to use multiple datasets."""


@dataclass(slots=True)
class ResolvedDatasetPackage:
    reference: ExperimentDataset
    manifest: MaterializationManifest | None = None

    def metadata(self) -> DatasetMetadata:
        identity = self.identity()
        return DatasetMetadata(
            name=identity,
            description="Resolved dataset reference.",
            domain="unknown",
            intended_uses="Resolver-level reference handling.",
            limitations="Planning/runtime capabilities are not available until a concrete package adapter is used.",
            license_url=None,
            citation_url=None,
        )

    def identity(self) -> str:
        if self.reference.id:
            return self.reference.id
        if self.manifest is not None:
            return self.manifest.datasetId
        if self.reference.root:
            return Path(self.reference.root).name or self.reference.root
        return "unknown"

    def version(self) -> str:
        if self.reference.version:
            return self.reference.version
        if self.manifest is not None:
            return self.manifest.datasetVersion
        return "local"

    def origin(self) -> str | None:
        if self.reference.origin:
            return self.reference.origin
        if self.manifest is not None:
            return self.manifest.origin
        return self.reference.root

    def list_instance_ids(self) -> list[str]:
        return []

    def list_task_ids(self) -> list[str]:
        return []

    def get_task(self, task_id: str) -> TaskPayload:
        raise NotImplementedError("Dataset tasks are not available from the resolver package wrapper.")

    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextPayload:
        raise NotImplementedError("Dataset artifacts are not available from the S4 resolver package wrapper.")

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        raise NotImplementedError("Dataset artifacts are not available from the S4 resolver package wrapper.")

    def get_oracle(self, instance_id: str, task_id: str) -> OracleUnavailable:
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        return None

    def fixtures(self) -> object:
        return {}

    def capability_report(self) -> DatasetCapabilityReport:
        return DatasetCapabilityReport(
            identity=self.identity(),
            version=self.version(),
            origin=self.origin(),
            resolved_revision=self.manifest.resolvedRevision if self.manifest is not None else None,
            materialized_path=self.manifest.materializedPath if self.manifest is not None else self.reference.root,
            content_hash=self.manifest.contentHash if self.manifest is not None else None,
            metadata=self.metadata(),
            mandatory_capabilities={},
            optional_capabilities={},
            contributed_tools=None,
            evaluation_helpers=None,
            strategy_descriptors=[],
            missing_mandatory=[],
            nonconformant_descriptors=[],
            conformant=False,
        )

    def tool_provider(self) -> object | None:
        return None

    def evaluation_helpers(self) -> object | None:
        return None

    def strategy_descriptors(self) -> list[object] | None:
        return None


@dataclass(slots=True)
class ResolvedDatasetForPlanning:
    package: DatasetPackage
    adapter_ref: ExperimentDataset | DatasetProvenance


class DatasetResolver:
    """Local-only dataset resolver.

    This resolver only inspects explicit local roots or already-materialized cache entries.
    It does not fetch, download, clone, or otherwise acquire datasets. Lifecycle commands
    enforce the no-implicit-network rule by calling this resolver and failing immediately
    when the dataset is missing or ambiguous.
    """

    def resolve(self, ref: ExperimentDataset | dict[str, Any] | list[Any], cache: DatasetCache) -> DatasetPackage:
        return self._resolve_for_planning(ref, cache).package

    def resolve_for_planning(
        self,
        ref: ExperimentDataset | dict[str, Any] | list[Any],
        cache: DatasetCache,
    ) -> ResolvedDatasetForPlanning:
        return self._resolve_for_planning(ref, cache)

    def _resolve_for_planning(
        self,
        ref: ExperimentDataset | dict[str, Any] | list[Any],
        cache: DatasetCache,
    ) -> ResolvedDatasetForPlanning:
        if isinstance(ref, list):
            raise MultiDatasetError("Multiple datasets are not supported.")
        if isinstance(ref, dict) and "datasets" in ref:
            raise MultiDatasetError("Multiple datasets are not supported.")

        dataset_ref = ExperimentDataset.model_validate(ref)

        if dataset_ref.root:
            package = LocalDatasetPackage.from_dataset(dataset_ref)
            return ResolvedDatasetForPlanning(
                package=package,
                adapter_ref=ExperimentDataset(
                    root=package.dataset_paths.root,
                    id=dataset_ref.id or package.identity(),
                    version=dataset_ref.version or package.version(),
                    origin=dataset_ref.origin or package.origin(),
                ),
            )

        if dataset_ref.id and dataset_ref.version:
            DatasetConflictDetector.check(dataset_ref.id, dataset_ref.version, cache)
            matches = cache.lookup(dataset_ref.id, dataset_ref.version)
            if not matches:
                raise DatasetNotFoundError(
                    f"Dataset {dataset_ref.id}@{dataset_ref.version} was not found in the local cache. "
                    "Run llmctxbench dataset fetch to materialize it first."
                )
            manifest = matches[0]
            adapter_ref = DatasetProvenance(
                id=manifest.datasetId,
                version=manifest.datasetVersion,
                origin=manifest.origin,
                resolved_revision=manifest.resolvedRevision,
                content_hash=manifest.contentHash,
                materialized_path=manifest.materializedPath,
            )
            materialized_root = Path(manifest.materializedPath) if manifest.materializedPath else None
            if materialized_root is not None and (materialized_root / "tasks.json").exists():
                materialized_dataset = ExperimentDataset(
                    root=str(materialized_root),
                    id=manifest.datasetId,
                    version=manifest.datasetVersion,
                    origin=manifest.origin,
                )
                package = LocalDatasetPackage.from_dataset(materialized_dataset)
                return ResolvedDatasetForPlanning(package=package, adapter_ref=adapter_ref)
            return ResolvedDatasetForPlanning(
                package=ResolvedDatasetPackage(reference=dataset_ref, manifest=manifest),
                adapter_ref=adapter_ref,
            )

        raise DatasetNotFoundError(
            "Dataset reference is incomplete. Provide a local dataset root or an id/version pair."
        )
