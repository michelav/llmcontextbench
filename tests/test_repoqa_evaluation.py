from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

import ctxbench.adapters.repoqa.evaluation as repoqa_eval
from ctxbench.adapters.repoqa.evaluation import REPOQA_IMPORT_ERROR, evaluate_response
from ctxbench.benchmark.models import TrialResult


def _write_repoqa_dataset(root: Path) -> None:
    instance_dir = root / "context" / "inst-1"
    instance_dir.mkdir(parents=True)
    (root / "raw").mkdir()
    (instance_dir / "native_task.json").write_text(
        json.dumps({"language": "python", "repo": "owner/repo", "name": "target_func"}),
        encoding="utf-8",
    )
    (root / "raw" / "repoqa.json").write_text(
        json.dumps({"python": [{"repo": "owner/repo", "content": {}, "needles": []}]}),
        encoding="utf-8",
    )


def _trial(dataset_root: Path, *, response: str = "def target_func(): pass", status: str = "success") -> TrialResult:
    return TrialResult.model_validate(
        {
            "trialId": "trial-1",
            "experimentId": "exp-1",
            "dataset": {
                "id": "ctxbench/repoqa",
                "version": "local",
                "origin": str(dataset_root),
                "materializedPath": str(dataset_root),
            },
            "taskId": "q_repoqa",
            "taskStatement": "Find the target function.",
            "instanceId": "inst-1",
            "provider": "mock",
            "modelId": "mock",
            "model": "mock",
            "strategy": "inline",
            "format": "code",
            "repeatIndex": 1,
            "status": status,
            "response": response,
            "timing": {
                "startedAt": "2026-01-01T00:00:00Z",
                "finishedAt": "2026-01-01T00:00:01Z",
                "durationMs": 1000,
            },
            "usage": {"inputTokens": 10, "outputTokens": 5},
            "metricsSummary": {"toolCalls": 0, "functionCalls": 0, "modelCalls": 1},
            "validationType": "repoqa-scorer",
            "validationConfig": {"threshold": 0.8, "ignoreComments": True},
            "metadata": {
                "canonicalId": "trial-1",
                "taskId": "q_repoqa",
                "instanceId": "inst-1",
                "provider": "mock",
                "modelId": "mock",
                "modelName": "mock",
                "strategy": "inline",
                "format": "code",
                "repeatIndex": 1,
                "validationType": "repoqa-scorer",
                "validationConfig": {"threshold": 0.8, "ignoreComments": True},
            },
        }
    )


def _install_fake_repoqa(monkeypatch: pytest.MonkeyPatch, *, best_target: str | None = "target_func", score: float = 0.91) -> None:
    package = types.ModuleType("repoqa")
    compute_score = types.ModuleType("repoqa.compute_score")

    class Result:
        value = "best_match"

    def needle_evaluator(model_output, ground_truth, repo_info, lang, ignore_comments):
        assert model_output
        assert ground_truth == "target_func"
        assert repo_info["repo"] == "owner/repo"
        assert lang == "python"
        assert ignore_comments is True
        return Result(), best_target, score

    compute_score.needle_evaluator = needle_evaluator
    monkeypatch.setitem(sys.modules, "repoqa", package)
    monkeypatch.setitem(sys.modules, "repoqa.compute_score", compute_score)


def test_repoqa_evaluator_scores_successful_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_repoqa_dataset(tmp_path)
    _install_fake_repoqa(monkeypatch)

    evaluated = evaluate_response(_trial(tmp_path), threshold=0.8, ignore_comments=True)
    item = evaluated.items[0]

    assert item.evaluationMode == "deterministic"
    assert item.evaluationMethod == "repoqa-scorer"
    assert item.evaluationJudgeUsed is False
    assert item.details["outcome"] == {"passed": True}
    assert item.details["repoqa"]["bestTarget"] == "target_func"
    assert item.details["repoqa"]["bestSimilarScore"] == 0.91
    assert item.details["repoqa"]["passed"] is True


def test_repoqa_evaluator_falls_back_to_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_repoqa_dataset(tmp_path)
    runner = tmp_path / "repoqa_python"
    helper = tmp_path / "score_response.py"
    runner.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.write_text("# helper\n", encoding="utf-8")

    def fake_run(args, *, input, text, capture_output, check):
        assert args == [str(runner), str(helper)]
        assert text is True
        assert capture_output is True
        assert check is False
        request = json.loads(input)
        assert request["response"] == "def target_func(): pass"
        assert request["native_task"]["name"] == "target_func"
        assert request["repo_info"]["repo"] == "owner/repo"
        assert request["ignore_comments"] is True
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "verdict": "best_match",
                    "bestTarget": "target_func",
                    "bestSimilarScore": 0.88,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(repoqa_eval, "_load_direct_needle_evaluator", lambda: None)
    monkeypatch.setattr(repoqa_eval, "_repoqa_runner_path", lambda: runner)
    monkeypatch.setattr(repoqa_eval, "_repoqa_helper_path", lambda: helper)
    monkeypatch.setattr(repoqa_eval.subprocess, "run", fake_run)

    evaluated = evaluate_response(_trial(tmp_path), threshold=0.8, ignore_comments=True)

    repoqa = evaluated.items[0].details["repoqa"]
    assert evaluated.items[0].details["outcome"] == {"passed": True}
    assert repoqa["bestTarget"] == "target_func"
    assert repoqa["bestSimilarScore"] == 0.88
    assert repoqa["isBestMatch"] is True
    assert repoqa["passed"] is True


def test_repoqa_evaluator_subprocess_failure_reports_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_repoqa_dataset(tmp_path)
    runner = tmp_path / "repoqa_python"
    helper = tmp_path / "score_response.py"
    runner.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.write_text("# helper\n", encoding="utf-8")

    def fake_run(args, *, input, text, capture_output, check):
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="missing dependency")

    monkeypatch.setattr(repoqa_eval, "_load_direct_needle_evaluator", lambda: None)
    monkeypatch.setattr(repoqa_eval, "_repoqa_runner_path", lambda: runner)
    monkeypatch.setattr(repoqa_eval, "_repoqa_helper_path", lambda: helper)
    monkeypatch.setattr(repoqa_eval.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="missing dependency"):
        evaluate_response(_trial(tmp_path), threshold=0.8, ignore_comments=True)


def test_repoqa_evaluator_empty_response_fails_without_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_repoqa_dataset(tmp_path)
    monkeypatch.delitem(sys.modules, "repoqa.compute_score", raising=False)

    evaluated = evaluate_response(_trial(tmp_path, response="   "), threshold=0.8)

    repoqa = evaluated.items[0].details["repoqa"]
    assert repoqa["bestTarget"] is None
    assert repoqa["bestSimilarScore"] == 0.0
    assert repoqa["passed"] is False


def test_repoqa_evaluator_non_success_is_skipped(tmp_path: Path) -> None:
    _write_repoqa_dataset(tmp_path)

    evaluated = evaluate_response(_trial(tmp_path, status="error"), threshold=0.8)

    assert evaluated.items[0].status == "skipped"
    assert "skipped" in evaluated.items[0].details["outcome"]["reason"]


def test_repoqa_evaluator_rejects_missing_native_task(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "repoqa.json").write_text(json.dumps({"python": []}), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="native task not found"):
        evaluate_response(_trial(tmp_path))


def test_repoqa_evaluator_rejects_ambiguous_raw_json(tmp_path: Path) -> None:
    _write_repoqa_dataset(tmp_path)
    (tmp_path / "raw" / "other.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected exactly one raw RepoQA JSON"):
        evaluate_response(_trial(tmp_path))


def test_repoqa_evaluator_rejects_missing_repo(tmp_path: Path) -> None:
    _write_repoqa_dataset(tmp_path)
    (tmp_path / "raw" / "repoqa.json").write_text(json.dumps({"python": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="no repo"):
        evaluate_response(_trial(tmp_path))


def test_repoqa_evaluator_import_failure_guidance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_repoqa_dataset(tmp_path)
    monkeypatch.setattr(repoqa_eval, "_load_direct_needle_evaluator", lambda: None)
    monkeypatch.setattr(repoqa_eval, "_repoqa_runner_path", lambda: tmp_path / "missing-runner")

    with pytest.raises(ImportError, match="RepoQA is required only"):
        evaluate_response(_trial(tmp_path))
    assert "uv sync --locked" in REPOQA_IMPORT_ERROR
    assert "REPOQA_PYTHON" in REPOQA_IMPORT_ERROR
