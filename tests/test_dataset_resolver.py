from __future__ import annotations

from pathlib import Path
import json

import pytest

from ctxbench.benchmark.models import DatasetProvenance, ExperimentDataset
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.materialization import MaterializationManifest
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.resolver import (
    DatasetNotFoundError,
    DatasetResolver,
    MultiDatasetError,
    ResolvedDatasetPackage,
)


def _manifest() -> MaterializationManifest:
    return MaterializationManifest(
        datasetId="ctxbench/fake",
        requestedVersion="0.1.0",
        resolvedRevision="rev-a",
        origin="/tmp/source-a",
        materializedPath="/tmp/placeholder",
        contentHash="sha256:same",
        fetchedAt="2026-05-12T00:00:00Z",
        ctxbenchVersion="0.1.0",
        fetchMethod="archive-download",
        sourceType="archive-url",
        archiveUrl="https://example.invalid/fake.tar.gz",
        verifiedSha256="sha256:verified",
    )


def _write_source(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.txt").write_text("fixture", encoding="utf-8")
    return path


def _write_local_dataset(path: Path) -> Path:
    instance_dir = path / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (path / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "tasks": [
                    {
                        "id": "q_year",
                        "statement": "When?",
                        "tags": [],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (path / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "instances": [
                    {
                        "instanceId": "cv-demo",
                        "tasks": [{"id": "q_year"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "blocks.json").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
    return path


def test_resolver_local_path_returns_dataset_package_compatible_object(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    dataset_root = _write_local_dataset(tmp_path / "dataset")

    package = resolver.resolve(ExperimentDataset(root=str(dataset_root)), cache)

    assert isinstance(package, DatasetPackage)
    assert package.origin() == str(dataset_root)


def test_resolve_for_planning_preserves_local_root_adapter_ref(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    dataset_root = _write_local_dataset(tmp_path / "dataset")

    resolved = resolver.resolve_for_planning(
        ExperimentDataset(
            root=str(dataset_root),
            id="ctxbench/lattes",
            version="0.1.0",
            origin="local-origin",
        ),
        cache,
    )

    assert isinstance(resolved.package, LocalDatasetPackage)
    assert resolved.adapter_ref == ExperimentDataset(
        root=str(dataset_root),
        id="ctxbench/lattes",
        version="0.1.0",
        origin="local-origin",
    )


def test_resolver_cached_id_version_returns_single_materialization(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    cache.store(_manifest(), _write_source(tmp_path / "source-a"))

    package = resolver.resolve(ExperimentDataset(id="ctxbench/fake", version="0.1.0"), cache)

    assert isinstance(package, DatasetPackage)
    assert package.identity() == "ctxbench/fake"
    assert package.version() == "0.1.0"
    assert package.origin() == "/tmp/source-a"


def test_resolve_for_planning_preserves_cached_materialization_ref(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    cache.store(_manifest(), _write_source(tmp_path / "source-a"))
    manifest = cache.lookup("ctxbench/fake", "0.1.0")[0]

    resolved = resolver.resolve_for_planning(
        ExperimentDataset(id="ctxbench/fake", version="0.1.0"),
        cache,
    )

    assert isinstance(resolved.package, ResolvedDatasetPackage)
    assert resolved.adapter_ref == DatasetProvenance(
        id="ctxbench/fake",
        version="0.1.0",
        origin="/tmp/source-a",
        resolved_revision="rev-a",
        content_hash="sha256:same",
        materialized_path=manifest.materializedPath,
    )


def test_resolver_missing_dataset_suggests_fetch(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")

    with pytest.raises(DatasetNotFoundError) as excinfo:
        resolver.resolve(ExperimentDataset(id="ctxbench/missing", version="9.9.9"), cache)

    assert "llmctxbench dataset fetch" in str(excinfo.value)


def test_resolver_rejects_multi_dataset_reference(tmp_path: Path) -> None:
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")

    with pytest.raises(MultiDatasetError):
        resolver.resolve({"datasets": [{"id": "ctxbench/a", "version": "0.1.0"}]}, cache)
