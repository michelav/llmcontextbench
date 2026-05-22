from __future__ import annotations

import json
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
REAL_DATASET_ROOT = Path(__file__).resolve().parents[1] / "datasets" / "lattes"


def test_lattes_dataset_package_satisfies_dataset_package_protocol() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    assert isinstance(package, DatasetPackage)


def test_lattes_dataset_package_fixtures_path_contains_instance_and_task_files() -> None:
    package = LattesDatasetPackage(FIXTURE_ROOT)

    fixtures_root = Path(str(package.fixtures()))
    assert (fixtures_root / "tasks.json").exists()
    assert (fixtures_root / "tasks.instance.json").exists()
    assert any((fixtures_root / "context").iterdir())


def test_real_lattes_dataset_uses_canonical_task_payloads() -> None:
    package = LattesDatasetAdapter(REAL_DATASET_ROOT)

    assert (REAL_DATASET_ROOT / "tasks.json").exists()
    assert (REAL_DATASET_ROOT / "tasks.instance.json").exists()
    assert not (REAL_DATASET_ROOT / "questions.json").exists()
    assert not (REAL_DATASET_ROOT / "questions.instance.json").exists()

    task = package.get_task("q_phd")
    instance = package.get_instance("3457219624656691")
    raw_tasks = json.loads((REAL_DATASET_ROOT / "tasks.json").read_text(encoding="utf-8"))
    raw_instances = json.loads(
        (REAL_DATASET_ROOT / "tasks.instance.json").read_text(encoding="utf-8")
    )

    assert task.statement == "Where and how long ago did the researcher complete their PhD?"
    assert "tasks" in raw_tasks
    assert "questions" not in raw_tasks
    assert instance.tasks
    assert "tasks" in raw_instances["instances"][0]
    assert "questions" not in raw_instances["instances"][0]


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


def test_lattes_dataset_adapter_returns_task_instance_parameters() -> None:
    package = LattesDatasetAdapter(FIXTURE_ROOT)

    task_instance = package.get_task_instance("1234567890123456", "q_profile")

    assert task_instance == {"parameters": {}}


def test_lattes_dataset_adapter_evidence_includes_task_instance() -> None:
    package = LattesDatasetAdapter(FIXTURE_ROOT)

    evidence = package.get_evidence("1234567890123456", "q_profile")

    assert evidence.task_instance == {"parameters": {}}


def test_legacy_lattes_dataset_package_aliases_adapter() -> None:
    from ctxbench.datasets.lattes import LattesDatasetAdapter as LegacyAdapter
    from ctxbench.datasets.lattes import LattesDatasetPackage as LegacyPackage
    from ctxbench.datasets.lattes.package import LattesDatasetAdapter as LegacyPackageAdapter

    assert LegacyAdapter is LattesDatasetAdapter
    assert LegacyPackage is LattesDatasetAdapter
    assert LegacyPackageAdapter is LattesDatasetAdapter
    assert LattesDatasetPackage is LattesDatasetAdapter
