from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ctxbench.benchmark.models import DatasetProvenance, ExperimentDataset
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.package import DatasetPackage


@dataclass(slots=True)
class ResolvedDatasetRef:
    id: str
    version: str
    root: str | None = None
    origin: str | None = None
    content_hash: str | None = None
    materialized_path: str | None = None


Factory = Callable[[ResolvedDatasetRef], DatasetPackage]


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Factory] = {}

    def register(self, dataset_id: str, factory: Factory) -> None:
        self._factories[dataset_id] = factory

    def resolve(self, dataset_ref: ExperimentDataset | DatasetProvenance) -> DatasetPackage:
        resolved = self._normalize(dataset_ref)
        factory = self._factories.get(resolved.id)
        if factory is None:
            raise AdapterUnavailableError(f"No adapter registered for dataset id {resolved.id!r}.")
        return factory(resolved)

    def _normalize(self, dataset_ref: ExperimentDataset | DatasetProvenance) -> ResolvedDatasetRef:
        if isinstance(dataset_ref, ExperimentDataset):
            if not dataset_ref.id:
                raise AdapterUnavailableError("Cannot resolve dataset adapter without dataset id.")
            return ResolvedDatasetRef(
                id=dataset_ref.id,
                version=dataset_ref.version or "",
                root=dataset_ref.root,
                origin=dataset_ref.origin,
            )

        if isinstance(dataset_ref, DatasetProvenance):
            if not dataset_ref.id:
                raise AdapterUnavailableError("Cannot resolve dataset adapter without dataset id.")
            return ResolvedDatasetRef(
                id=dataset_ref.id,
                version=dataset_ref.version,
                root=getattr(dataset_ref, "root", None),
                origin=dataset_ref.origin,
                content_hash=dataset_ref.content_hash,
                materialized_path=dataset_ref.materialized_path,
            )

        raise AdapterUnavailableError(
            f"Cannot resolve dataset adapter from {type(dataset_ref).__name__}."
        )
