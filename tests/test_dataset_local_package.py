from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.package import DatasetPackage
from ctxbench.dataset.provider import LocalDatasetPackage
from ctxbench.dataset.resolver import DatasetResolver
from ctxbench.dataset.tasks import Task, TaskDataset, TaskInstanceDataset


def _write_local_dataset(root: Path) -> Path:
    instance_dir = root / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "domain": "testing",
                "description": "Local package fixture.",
                "tasks": [
                    {
                        "id": "q_year",
                        "statement": "In which year did {researcher_name} obtain their PhD?",
                        "tags": ["objective", "simple"],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "instances": [
                    {
                        "instanceId": "cv-demo",
                        "contextBlocks": "context/cv-demo/blocks.json",
                        "tasks": [
                            {"id": "q_year", "parameters": {"researcher_name": "CV Demo"}}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "clean.html").write_text("ANSWER[q_year]: 2020\n", encoding="utf-8")
    (instance_dir / "blocks.json").write_text(
        json.dumps({"summary": "Researcher in software engineering."}),
        encoding="utf-8",
    )
    return root


def test_local_dataset_package_resolves_as_dataset_package(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")

    package = resolver.resolve(ExperimentDataset(root=str(dataset_root)), cache)

    assert isinstance(package, DatasetPackage)
    assert isinstance(package, LocalDatasetPackage)
    assert package.identity() == "ctxbench/local-fixture"
    assert package.version() == "0.1.0"


def test_local_dataset_package_preserves_question_template_and_instance_parameters(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    package = LocalDatasetPackage.from_dataset(ExperimentDataset(root=str(dataset_root)))

    task = package.get_task("q_year")
    task_instance = package.get_task_instance("cv-demo", "q_year")

    assert task.statement == "In which year did {researcher_name} obtain their PhD?"
    assert task.tags == ["objective", "simple"]
    assert task.validation_type == "judge"
    assert task.context_blocks == ["summary"]
    assert task_instance is not None
    assert task_instance["parameters"] == {"researcher_name": "CV Demo"}
    assert package.get_context_blocks("cv-demo") == {"summary": "Researcher in software engineering."}
    assert package.get_context_artifact("cv-demo", "q_year", "inline", "json") == {"answers": {"q_year": 2020}}
    assert package.get_evidence_artifact("cv-demo", "q_year") == {
        "task": {
            "id": "q_year",
            "statement": "In which year did {researcher_name} obtain their PhD?",
            "tags": ["objective", "simple"],
            "validation": {"type": "judge"},
            "contextBlocks": ["summary"],
        },
        "taskInstance": {"id": "q_year", "parameters": {"researcher_name": "CV Demo"}},
        "contextBlocks": {"summary": "Researcher in software engineering."},
    }


def test_local_dataset_package_accepts_string_and_root_forms_equivalently(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    resolver = DatasetResolver()
    cache = DatasetCache(cache_dir=tmp_path / "cache")

    from_string = resolver.resolve(str(dataset_root), cache)
    from_root = resolver.resolve({"root": str(dataset_root)}, cache)

    assert isinstance(from_string, LocalDatasetPackage)
    assert isinstance(from_root, LocalDatasetPackage)
    assert from_string.identity() == from_root.identity()
    assert from_string.version() == from_root.version()
    assert from_string.origin() == from_root.origin()


def test_task_dataset_reads_tasks_and_legacy_questions_keys() -> None:
    canonical = TaskDataset.model_validate(
        {
            "datasetId": "dataset",
            "tasks": [
                {
                    "id": "q_year",
                    "question": "Question?",
                    "validation": {"type": "judge"},
                    "contextBlocks": ["summary"],
                }
            ],
        }
    )
    legacy = TaskDataset.model_validate(
        {
            "datasetId": "dataset",
            "questions": [
                {
                    "id": "q_year",
                    "question": "Question?",
                    "validation": {"type": "judge"},
                    "contextBlocks": ["summary"],
                }
            ],
        }
    )

    assert [task.id for task in canonical.tasks] == ["q_year"]
    assert [task.id for task in legacy.tasks] == ["q_year"]


def test_task_instance_dataset_reads_tasks_and_legacy_questions_keys() -> None:
    canonical = TaskInstanceDataset.model_validate(
        {"instances": [{"instanceId": "cv-demo", "tasks": [{"id": "q_year"}]}]}
    )
    legacy = TaskInstanceDataset.model_validate(
        {"instances": [{"instanceId": "cv-demo", "questions": [{"id": "q_year"}]}]}
    )

    assert canonical.instances[0].tasks[0].id == "q_year"
    assert legacy.instances[0].tasks[0].id == "q_year"


def test_task_reads_legacy_context_block_key() -> None:
    task = Task.model_validate(
        {
            "id": "q_year",
            "question": "Question?",
            "validation": {"type": "judge"},
            "contextBlock": ["summary"],
        }
    )

    assert task.contextBlocks == ["summary"]


def test_local_dataset_package_warns_for_legacy_questions_file(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    (dataset_root / "questions.json").write_text((dataset_root / "tasks.json").read_text(encoding="utf-8"), encoding="utf-8")
    (dataset_root / "tasks.json").unlink()

    with pytest.warns(DeprecationWarning, match="questions.json is deprecated"):
        package = LocalDatasetPackage.from_dataset(ExperimentDataset(root=str(dataset_root)))

    assert package.list_task_ids() == ["q_year"]
