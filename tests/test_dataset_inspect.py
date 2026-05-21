from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ctxbench.cli import build_parser
from ctxbench.commands.dataset import inspect_command
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.conflicts import AmbiguousDatasetError
from ctxbench.dataset.inspect import build_inspect_result
from ctxbench.dataset.materialization import MaterializationManifest
from ctxbench.dataset.package import DatasetMetadata, StrategyDescriptor
from ctxbench.dataset.payloads import ContextPayload, EvidencePayload, TaskPayload


def _metadata() -> DatasetMetadata:
    return DatasetMetadata(
        name="Fake Dataset",
        description="Synthetic dataset for inspect testing.",
        domain="testing",
        intended_uses="Inspect validation checks.",
        limitations="Not a real benchmark dataset.",
        license_url=None,
        citation_url=None,
    )


class ConformantPackage:
    def metadata(self) -> DatasetMetadata:
        return _metadata()

    def identity(self) -> str:
        return "ctxbench/fake"

    def version(self) -> str:
        return "0.1.0"

    def origin(self) -> str | None:
        return None

    def list_instance_ids(self) -> list[str]:
        return ["inst-001"]

    def list_task_ids(self) -> list[str]:
        return ["task-001"]

    def get_task(self, task_id: str) -> TaskPayload:
        return TaskPayload(task_id=task_id, statement="When?")

    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextPayload:
        return ContextPayload(
            role="context",
            representation=representation,
            content={"instance": instance_id, "task": task_id},
        )

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload:
        return EvidencePayload(
            role="evidence",
            task={"task_id": task_id},
            evidence={"instance": instance_id},
        )

    def capability_report(self) -> object:
        return None

    def tool_provider(self) -> object | None:
        return None

    def evaluation_helpers(self) -> object | None:
        return None

    def strategy_descriptors(self) -> list[StrategyDescriptor] | None:
        return [
            StrategyDescriptor(
                name="inline",
                classification="canonical",
                context_access_mode="inline-context",
                inline_vs_operation="inline",
                local_vs_remote="local",
                loop_ownership="benchmark",
                metric_provenance={"totalTokens": "reported"},
                observability_limitations="None",
                comparability_implications="Comparable with inline runs.",
            )
        ]


class MissingMandatoryPackage(ConformantPackage):
    get_context = None  # type: ignore[assignment]


class NonconformantDescriptorPackage(ConformantPackage):
    def strategy_descriptors(self) -> list[object] | None:
        return [
            SimpleNamespace(
                name="inline",
                classification="canonical",
                context_access_mode="inline-context",
                inline_vs_operation="inline",
                local_vs_remote="local",
                loop_ownership="benchmark",
                metric_provenance={"totalTokens": "reported"},
                observability_limitations="None",
            )
        ]


def _write_local_dataset(root: Path) -> Path:
    instance_dir = root / "context" / "cv-demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "ctxbench/fake",
                "version": "0.1.0",
                "tasks": [
                    {
                        "id": "q_year",
                        "question": "When?",
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
                "datasetId": "ctxbench/fake",
                "version": "0.1.0",
                "instances": [{"instanceId": "cv-demo", "tasks": [{"id": "q_year"}]}],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"answers": {"q_year": 2020}}), encoding="utf-8")
    (instance_dir / "blocks.json").write_text(json.dumps({"summary": "ok"}), encoding="utf-8")
    return root


def _manifest(*, origin: str, revision: str) -> MaterializationManifest:
    return MaterializationManifest(
        datasetId="ctxbench/fake",
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
        verifiedSha256=None,
    )


def test_build_inspect_result_reports_conformant_package() -> None:
    report = build_inspect_result(ConformantPackage(), None)

    assert report.conformant is True
    assert report.missing_mandatory == []


def test_build_inspect_result_reports_missing_mandatory_method() -> None:
    report = build_inspect_result(MissingMandatoryPackage(), None)

    assert report.conformant is False
    assert "get_context" in report.missing_mandatory


def test_build_inspect_result_reports_nonconformant_strategy_descriptor() -> None:
    report = build_inspect_result(NonconformantDescriptorPackage(), None)

    assert report.conformant is False
    assert report.nonconformant_descriptors
    assert "comparability_implications" in report.nonconformant_descriptors[0]


def test_inspect_command_rejects_ambiguous_reference_before_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    version_root = tmp_path / "cache" / "ctxbench" / "fake" / "0.1.0"
    rev_a = version_root / "rev-a"
    rev_b = version_root / "rev-b"
    rev_a.mkdir(parents=True, exist_ok=True)
    rev_b.mkdir(parents=True, exist_ok=True)
    cache._write_manifest(rev_a / "manifest.json", _manifest(origin=str(tmp_path / "dataset-a"), revision="rev-a"))  # type: ignore[attr-defined]
    cache._write_manifest(rev_b / "manifest.json", _manifest(origin=str(tmp_path / "dataset-b"), revision="rev-b"))  # type: ignore[attr-defined]
    calls: list[str] = []

    def _unexpected(*args: object, **kwargs: object) -> object:
        calls.append("called")
        raise AssertionError("build_inspect_result should not run for ambiguous refs")

    monkeypatch.setattr("ctxbench.commands.dataset.build_inspect_result", _unexpected)

    with pytest.raises(AmbiguousDatasetError):
        inspect_command("ctxbench/fake@0.1.0", cache_dir=tmp_path / "cache")

    assert calls == []


def test_inspect_command_uses_latest_semantic_materialization(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cache = DatasetCache(cache_dir=tmp_path / "cache")
    dataset_a = _write_local_dataset(tmp_path / "dataset-a")
    dataset_b = _write_local_dataset(tmp_path / "dataset-b")
    cache.store(_manifest(origin=str(dataset_a), revision="rev-a"), dataset_a)
    cache.store(_manifest(origin=str(dataset_b), revision="rev-b"), dataset_b)

    inspect_command("ctxbench/fake@0.1.0", cache_dir=tmp_path / "cache")

    output = capsys.readouterr().out
    assert "identity: ctxbench/fake" in output
    assert "version: 0.1.0" in output
    assert f"origin: {dataset_b}" in output


def test_inspect_command_json_output_is_valid_json(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")

    inspect_command(str(dataset_root), json_output=True, cache_dir=tmp_path / "cache")

    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"] == "ctxbench/fake"
    assert payload["version"] == "0.1.0"
    assert payload["conformant"] is True
    assert payload["missing_mandatory"] == []


def test_dataset_inspect_help_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["dataset", "inspect", "--help"])

    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "dataset inspect" in captured.out
    assert "--json" in captured.out
    assert "--cache-dir" in captured.out


def test_inspect_command_explicit_cache_dir_overrides_env_var(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dataset_root = _write_local_dataset(tmp_path / "dataset")
    explicit_cache = DatasetCache(cache_dir=tmp_path / "explicit-cache")
    explicit_cache.store(_manifest(origin=str(dataset_root), revision="rev-a"), dataset_root)
    monkeypatch.setenv("CTXBENCH_DATASET_CACHE", str(tmp_path / "env-cache"))

    inspect_command("ctxbench/fake@0.1.0", cache_dir=tmp_path / "explicit-cache")

    captured = capsys.readouterr()
    assert "identity: ctxbench/fake" in captured.out
    assert "version: 0.1.0" in captured.out
