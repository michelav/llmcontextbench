from __future__ import annotations

from pathlib import Path

from ctxbench.dataset.package import DatasetPackage
from ctxbench.datasets.lattes.package import LattesDatasetPackage
from ctxbench.adapters.lattes.package import LattesDatasetAdapter


FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "lattes_provider_free"
    / "dataset"
)


def test_lattes_dataset_package_satisfies_dataset_package_protocol() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    assert isinstance(package, DatasetPackage)


def test_lattes_dataset_package_fixtures_path_contains_instance_and_task_files() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    fixtures_root = Path(str(package.fixtures()))
    assert (fixtures_root / "questions.json").exists()
    assert (fixtures_root / "questions.instance.json").exists()
    assert any((fixtures_root / "context").iterdir())


def test_lattes_dataset_package_identity_and_version_are_non_empty() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    assert package.identity() == "ctxbench/lattes"
    assert package.version() == "2026-04-28"


def test_lattes_dataset_package_capability_report_is_conformant() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    report = package.capability_report()

    assert report.conformant is True
    assert report.missing_mandatory == []
    assert report.identity == "ctxbench/lattes"


def test_legacy_lattes_dataset_package_aliases_adapter() -> None:
    from ctxbench.datasets.lattes import LattesDatasetAdapter as LegacyAdapter
    from ctxbench.datasets.lattes import LattesDatasetPackage as LegacyPackage
    from ctxbench.datasets.lattes.package import LattesDatasetAdapter as LegacyPackageAdapter

    assert LegacyAdapter is LattesDatasetAdapter
    assert LegacyPackage is LattesDatasetAdapter
    assert LegacyPackageAdapter is LattesDatasetAdapter
    assert LattesDatasetPackage is LattesDatasetAdapter
