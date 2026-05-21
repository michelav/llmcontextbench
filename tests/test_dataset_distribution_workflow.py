from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.cli import build_parser
from ctxbench.commands.plan import plan_command
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.materialization import MaterializationManifest
from ctxbench.util.jsonl import read_jsonl


def _write_local_dataset(root: Path) -> Path:
    instance_dir = root / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/local-fixture",
                "version": "0.1.0",
                "tasks": [
                    {
                        "id": "q_year",
                        "question": "In which year did {researcher_name} obtain their PhD?",
                        "tags": ["objective"],
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
                        "tasks": [{"id": "q_year", "parameters": {"researcher_name": "CV Demo"}}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "blocks.json").write_text(json.dumps({"summary": "Researcher in software engineering."}), encoding="utf-8")
    return root


def _write_experiment(path: Path, dataset_ref: object) -> Path:
    path.write_text(
        json.dumps(
            {
                "id": "exp-dataset-plan",
                "output": "outputs",
                "dataset": dataset_ref,
                "scope": {"instances": [], "tasks": []},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["inline"],
                    "format": ["json"],
                },
                "evaluation": {"enabled": False, "judges": []},
            }
        ),
        encoding="utf-8",
    )
    return path


def _manifest(*, origin: str, revision: str) -> MaterializationManifest:
    return MaterializationManifest(
        datasetId="ctxbench/local-fixture",
        requestedVersion="0.1.0",
        datasetVersion="0.1.0",
        resolvedRevision=revision,
        origin=origin,
        materializedPath="",
        contentHash="sha256:same",
        fetchedAt="2026-05-12T00:00:00Z",
        ctxbenchVersion="0.1.0",
        fetchMethod="file-copy",
        sourceType="local-path",
        archiveUrl=None,
        releaseTagUrl=None,
        assetName=None,
        verifiedSha256=None,
    )


def test_plan_with_local_dataset_writes_manifest_provenance_and_trials(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    experiment_path = _write_experiment(tmp_path / "experiment.json", {"root": str(dataset_root)})
    output_root = tmp_path / "planned"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=tmp_path / "cache") == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    trials = read_jsonl(output_root / "trials.jsonl")

    assert manifest["dataset"]["id"] == "ctxbench/local-fixture"
    assert manifest["dataset"]["version"] == "0.1.0"
    assert manifest["dataset"]["origin"] == str(dataset_root)
    assert manifest["dataset"]["resolvedRevision"] is None
    assert manifest["dataset"]["contentHash"] is None
    assert trials


def test_plan_with_missing_cached_dataset_suggests_fetch(tmp_path: Path) -> None:
    experiment_path = _write_experiment(
        tmp_path / "experiment.json",
        {"id": "ctxbench/missing", "version": "9.9.9"},
    )

    with pytest.raises(Exception) as excinfo:
        plan_command(str(experiment_path), output=str(tmp_path / "planned"), cache_dir=tmp_path / "cache")

    assert "ctxbench dataset fetch" in str(excinfo.value)


def test_plan_with_semantic_cached_dataset_uses_latest_materialization(tmp_path: Path) -> None:
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    dataset_a = _write_local_dataset(tmp_path / "dataset-a")
    dataset_b = _write_local_dataset(tmp_path / "dataset-b")
    cache.store(_manifest(origin=str(dataset_a), revision="rev-a"), dataset_a)
    cache.store(_manifest(origin=str(dataset_b), revision="rev-b"), dataset_b)
    experiment_path = _write_experiment(
        tmp_path / "experiment.json",
        {"id": "ctxbench/local-fixture", "version": "0.1.0"},
    )

    output_root = tmp_path / "planned"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=tmp_path / "cache") == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["origin"] == str(dataset_b)
    assert manifest["dataset"]["resolvedRevision"] is None


@pytest.mark.parametrize(
    "dataset_ref_factory",
    [
        lambda dataset_root: str(dataset_root),
        lambda dataset_root: {"root": str(dataset_root)},
    ],
)
def test_plan_string_and_root_dataset_forms_are_equivalent(
    tmp_path: Path,
    dataset_ref_factory,
) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    experiment_path = _write_experiment(
        tmp_path / f"experiment-{type(dataset_ref_factory(dataset_root)).__name__}.json",
        dataset_ref_factory(dataset_root),
    )
    output_root = tmp_path / f"planned-{type(dataset_ref_factory(dataset_root)).__name__}"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=tmp_path / "cache") == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    rows = read_jsonl(output_root / "trials.jsonl")

    assert manifest["dataset"]["id"] == "ctxbench/local-fixture"
    assert manifest["dataset"]["version"] == "0.1.0"
    assert len(rows) == 1
    assert rows[0]["question"] == "In which year did CV Demo obtain their PhD?"
    assert rows[0]["parameters"] == {"researcher_name": "CV Demo"}


def test_plan_with_cached_dataset_uses_explicit_cache_dir(tmp_path: Path) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    cache_root = tmp_path / "custom-cache"
    cache = DatasetCache(cache_dir=cache_root)
    cache.store(_manifest(origin=str(dataset_root), revision="rev-a"), dataset_root)
    experiment_path = _write_experiment(
        tmp_path / "experiment-cached.json",
        {"id": "ctxbench/local-fixture", "version": "0.1.0"},
    )
    output_root = tmp_path / "planned-cached"

    assert plan_command(str(experiment_path), output=str(output_root), cache_dir=cache_root) == 0

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"]["id"] == "ctxbench/local-fixture"
    assert manifest["dataset"]["materializedPath"]


def test_plan_help_includes_cache_dir(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["plan", "--help"])

    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "ctxbench plan" in captured.out
    assert "--cache-dir" in captured.out
