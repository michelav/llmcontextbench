from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from ctxbench.benchmark.models import (
    EvaluationItemResult,
    EvaluationRunSummary,
    EvaluationTrialResult,
    TrialResult,
)


REPOQA_IMPORT_ERROR = (
    "RepoQA is required only for validation.type='repoqa-scorer', but "
    "'repoqa.compute_score' could not be imported and the isolated RepoQA scorer "
    "wrapper is unavailable. To create or check the isolated RepoQA tool environment, "
    "run: cd tools/repoqa && uv sync --locked. Verify it with: "
    "tools/repoqa/repoqa_python -c 'import repoqa.compute_score'. For custom "
    "environments, set REPOQA_PYTHON=/path/to/repoqa-env/bin/python."
)
REPOQA_SUBPROCESS_ERROR = (
    "RepoQA scorer subprocess failed. To create or check the isolated RepoQA tool "
    "environment, run: cd tools/repoqa && uv sync --locked. Verify it with: "
    "tools/repoqa/repoqa_python -c 'import repoqa.compute_score'. For custom "
    "environments, set REPOQA_PYTHON=/path/to/repoqa-env/bin/python."
)

RepoQAScorer = Callable[[str, dict[str, Any], dict[str, Any], bool], tuple[Any, str | None, float]]


def evaluate_response(
    result: TrialResult,
    *,
    threshold: float = 0.8,
    ignore_comments: bool = False,
) -> EvaluationTrialResult:
    if result.status != "success":
        return _build_result(
            result,
            status="skipped",
            outcome={
                "passed": False,
                "reason": f"Trial status is {result.status!r}; deterministic RepoQA scoring skipped.",
            },
            repoqa={
                "threshold": threshold,
                "ignoreComments": ignore_comments,
                "bestTarget": None,
                "bestSimilarScore": 0.0,
                "passed": False,
            },
        )

    response = (result.response or "").strip()
    if not response:
        return _build_result(
            result,
            outcome={"passed": False, "reason": "Response is empty."},
            repoqa={
                "threshold": threshold,
                "ignoreComments": ignore_comments,
                "bestTarget": None,
                "bestSimilarScore": 0.0,
                "passed": False,
            },
        )

    dataset_root = _dataset_root(result)
    native_task = _load_native_task(dataset_root, result.instanceId)
    repoqa_dataset = _load_raw_repoqa_dataset(dataset_root)
    repo_info = _repo_info(repoqa_dataset, native_task)
    scorer = _load_scorer()

    verdict, best_target, best_similarity = scorer(
        response,
        native_task,
        repo_info,
        bool(ignore_comments),
    )
    best_score = float(best_similarity or 0.0)
    is_best_match = str(getattr(verdict, "value", verdict)) == "best_match"
    passed = bool(is_best_match and best_score >= threshold)
    return _build_result(
        result,
        outcome={"passed": passed},
        repoqa={
            "threshold": threshold,
            "ignoreComments": ignore_comments,
            "language": native_task.get("language"),
            "repo": native_task.get("repo"),
            "target": native_task.get("name"),
            "bestTarget": best_target,
            "bestSimilarScore": best_score,
            "isBestMatch": is_best_match,
            "passed": passed,
        },
    )


def _dataset_root(result: TrialResult) -> Path:
    raw_root = result.dataset.materialized_path or result.dataset.origin
    if not raw_root:
        raise ValueError(
            f"RepoQA scorer needs dataset.materializedPath or dataset.origin for trial {result.trialId}."
        )
    root = Path(raw_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"RepoQA dataset root not found for trial {result.trialId}: {root}")
    return root


def _load_native_task(dataset_root: Path, instance_id: str) -> dict[str, Any]:
    path = dataset_root / "context" / instance_id / "native_task.json"
    if not path.exists():
        raise FileNotFoundError(f"RepoQA native task not found: {path}")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"RepoQA native task must be a JSON object: {path}")
    for key in ("language", "repo", "name"):
        if not str(payload.get(key) or "").strip():
            raise ValueError(f"RepoQA native task is missing required key {key!r}: {path}")
    return payload


def _load_raw_repoqa_dataset(dataset_root: Path) -> dict[str, Any]:
    raw_dir = dataset_root / "raw"
    matches = sorted(path for path in raw_dir.glob("*.json") if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Expected exactly one raw RepoQA JSON in {raw_dir}, found none.")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(f"Expected exactly one raw RepoQA JSON in {raw_dir}, found: {names}")
    payload = _read_json(matches[0])
    if not isinstance(payload, dict):
        raise ValueError(f"Raw RepoQA dataset must be a JSON object: {matches[0]}")
    return payload


def _repo_info(repoqa_dataset: dict[str, Any], native_task: dict[str, Any]) -> dict[str, Any]:
    language = str(native_task["language"])
    repo_name = str(native_task["repo"])
    repos = repoqa_dataset.get(language)
    if not isinstance(repos, list):
        raise ValueError(f"Raw RepoQA dataset has no language entry for {language!r}.")
    for repo in repos:
        if isinstance(repo, dict) and repo.get("repo") == repo_name:
            return repo
    raise ValueError(f"Raw RepoQA dataset has no repo {repo_name!r} for language {language!r}.")


def _load_scorer() -> RepoQAScorer:
    needle_evaluator = _load_direct_needle_evaluator()
    if needle_evaluator is not None:
        return _DirectRepoQAScorer(needle_evaluator)

    runner = _repoqa_runner_path()
    helper = _repoqa_helper_path()
    if runner.exists() and helper.exists():
        return _SubprocessRepoQAScorer(runner, helper)

    raise ImportError(REPOQA_IMPORT_ERROR)


def _load_direct_needle_evaluator() -> Callable[..., tuple[Any, str | None, float]] | None:
    try:
        from repoqa.compute_score import needle_evaluator
    except ImportError as exc:
        return None
    return needle_evaluator


class _DirectRepoQAScorer:
    def __init__(self, needle_evaluator: Callable[..., tuple[Any, str | None, float]]) -> None:
        self._needle_evaluator = needle_evaluator

    def __call__(
        self,
        response: str,
        native_task: dict[str, Any],
        repo_info: dict[str, Any],
        ignore_comments: bool,
    ) -> tuple[Any, str | None, float]:
        return self._needle_evaluator(
            response,
            str(native_task["name"]),
            repo_info,
            str(native_task["language"]),
            ignore_comments,
        )


class _SubprocessRepoQAScorer:
    def __init__(self, runner: Path, helper: Path) -> None:
        self._runner = runner
        self._helper = helper

    def __call__(
        self,
        response: str,
        native_task: dict[str, Any],
        repo_info: dict[str, Any],
        ignore_comments: bool,
    ) -> tuple[Any, str | None, float]:
        request = {
            "response": response,
            "native_task": native_task,
            "repo_info": repo_info,
            "ignore_comments": ignore_comments,
        }
        try:
            completed = subprocess.run(
                [str(self._runner), str(self._helper)],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"{REPOQA_SUBPROCESS_ERROR} {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            suffix = f" stderr: {stderr}" if stderr else ""
            raise RuntimeError(f"{REPOQA_SUBPROCESS_ERROR}{suffix}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("RepoQA scorer subprocess returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("RepoQA scorer subprocess returned a non-object JSON payload.")
        return (
            payload.get("verdict"),
            payload.get("bestTarget"),
            float(payload.get("bestSimilarScore") or 0.0),
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _repoqa_runner_path() -> Path:
    return _repo_root() / "tools" / "repoqa" / "repoqa_python"


def _repoqa_helper_path() -> Path:
    return _repo_root() / "tools" / "repoqa" / "score_response.py"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_result(
    result: TrialResult,
    *,
    outcome: dict[str, Any],
    repoqa: dict[str, Any],
    status: str = "evaluated",
) -> EvaluationTrialResult:
    summary = result.metricsSummary
    metrics = result.trace.aiTrace.get("metrics", {}) if result.trace.aiTrace else {}
    details = {
        "evaluationMethod": "repoqa-scorer",
        "outcome": outcome,
        "repoqa": repoqa,
    }
    item = EvaluationItemResult(
        experimentId=result.experimentId,
        trialId=result.trialId,
        dataset=result.dataset,
        taskId=result.taskId,
        instanceId=result.instanceId,
        taskStatement=result.taskStatement,
        evaluationMode="deterministic",
        status=status,
        evaluationMethod="repoqa-scorer",
        details=details,
        executionModel=result.modelName,
        executionStrategy=result.strategy,
        executionFormat=result.format,
        executionInputTokens=result.usage.get("inputTokens"),
        executionOutputTokens=result.usage.get("outputTokens"),
        executionDurationMs=result.timing.durationMs,
        executionToolCalls=summary.get("toolCalls", metrics.get("toolCalls")),
        executionFunctionCalls=summary.get("functionCalls", metrics.get("functionCalls")),
        executionLlmCalls=summary.get("modelCalls", metrics.get("modelCalls")),
        taskTags=list(result.taskTags),
        evaluationJudgeUsed=False,
    )
    return EvaluationTrialResult(
        experimentId=result.experimentId,
        trialId=result.trialId,
        dataset=result.dataset,
        taskId=result.taskId,
        items=[item],
        summary=EvaluationRunSummary(itemCount=1),
        metadata=result.metadata,
    )
