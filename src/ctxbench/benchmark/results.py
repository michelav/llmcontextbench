from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ctxbench.benchmark.models import EvaluationTrialResult, EvaluationTrace, TrialResult, TrialTrace
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import append_jsonl, write_jsonl


def _has_trace_payload(trace: TrialTrace) -> bool:
    return bool(
        trace.aiTrace
        or trace.toolCalls
        or trace.nativeMcp
        or trace.serverMcp
        or trace.rawResponse is not None
        or trace.error is not None
    )


def _has_evaluation_trace_payload(trace: EvaluationTrace) -> bool:
    return bool(
        trace.aiTrace
        or trace.rawResponse is not None
        or trace.error is not None
    )


def _write_trace_payload(
    *,
    artifact_root: str | Path,
    task: str,
    run_id: str,
    payload: dict[str, Any],
) -> str:
    root = Path(artifact_root)
    relative_path = Path("traces") / task / f"{run_id}.json"
    write_json(root / relative_path, payload)
    return relative_path.as_posix()


def write_trace_file(result: TrialResult, artifact_root: str | Path) -> str | None:
    if not _has_trace_payload(result.trace):
        return None
    payload = {
        "experimentId": result.experimentId,
        "trialId": result.trialId,
        "taskId": result.taskId,
        "task": "responses",
        "trace": result.trace.model_dump(mode="json"),
    }
    return _write_trace_payload(
        artifact_root=artifact_root,
        task="executions",
        run_id=result.trialId,
        payload=payload,
    )


def write_evaluation_trace_file(result: EvaluationTrialResult, artifact_root: str | Path) -> str | None:
    item = result.items[0] if result.items else None
    if item is None or not _has_evaluation_trace_payload(item.evaluationTrace):
        return None
    root = Path(artifact_root)
    relative_path = Path("traces") / "evals" / f"{result.trialId}.json"
    existing_file = root / relative_path
    new_trace = item.evaluationTrace.model_dump(mode="json")
    if existing_file.exists():
        try:
            existing = load_json(existing_file)
            old_ai = existing.get("trace", {}).get("aiTrace", {})
            new_ai = new_trace.get("aiTrace", {})
            new_ai["judges"] = old_ai.get("judges", []) + new_ai.get("judges", [])
            new_trace["aiTrace"] = new_ai
            def _as_list(v: object) -> list:
                if v is None:
                    return []
                return v if isinstance(v, list) else [v]
            old_raw = existing.get("trace", {}).get("rawResponse")
            new_raw = new_trace.get("rawResponse")
            if old_raw is not None or new_raw is not None:
                new_trace["rawResponse"] = _as_list(old_raw) + _as_list(new_raw)
        except Exception:
            pass
    payload = {
        "experimentId": result.experimentId,
        "trialId": result.trialId,
        "taskId": result.taskId,
        "task": "evals",
        "trace": new_trace,
    }
    write_json(root / relative_path, payload)
    return relative_path.as_posix()


def serialize_run_result(
    result: TrialResult,
    *,
    artifact_root: str | Path,
    write_trace: bool = True,
) -> dict[str, Any]:
    trace_ref = write_trace_file(result, artifact_root) if write_trace else None
    result.traceRef = trace_ref
    return result.to_persisted_artifact(trace_ref=trace_ref)


def _resolve_eval_trace_ref(
    result: EvaluationTrialResult,
    *,
    artifact_root: str | Path | None,
    write_trace: bool,
) -> str | None:
    if artifact_root is None or not write_trace:
        return None
    return write_evaluation_trace_file(result, artifact_root)


def serialize_evaluation_result(
    result: EvaluationTrialResult,
    *,
    artifact_root: str | Path | None = None,
    write_trace: bool = True,
    trace_ref: str | None = None,
) -> dict[str, Any]:
    item = result.items[0] if result.items else None
    resolved_trace_ref = trace_ref if trace_ref is not None else _resolve_eval_trace_ref(
        result, artifact_root=artifact_root, write_trace=write_trace
    )
    if item is None:
        return {
            "trialId": result.trialId,
            "experimentId": result.experimentId,
            "dataset": result.dataset.model_dump(mode="json"),
            "instanceId": result.metadata.instanceId or None,
            "taskId": result.taskId,
            "strategy": result.metadata.strategy or None,
            "repeatIndex": result.metadata.repeatIndex,
            "status": "not_evaluated",
            "evaluationMethod": None,
            "judgeCount": 0,
            "outcome": None,
            "evaluationInputTokens": None,
            "evaluationOutputTokens": None,
            "evaluationTotalTokens": None,
            "evaluationDurationMs": None,
            "contextBlocks": None,
            "traceRef": resolved_trace_ref,
        }
    payload = item.to_persisted_artifact()
    payload["repeatIndex"] = result.metadata.repeatIndex
    payload["traceRef"] = resolved_trace_ref
    return payload


def serialize_judge_votes(
    result: EvaluationTrialResult,
    *,
    trace_ref: str | None = None,
) -> list[dict[str, Any]]:
    item = result.items[0] if result.items else None
    if item is None:
        return []
    return item.to_judge_votes(trace_ref=trace_ref)


def append_result_jsonl(
    result: TrialResult,
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    write_trace: bool = True,
) -> Path:
    target_path = Path(path)
    root = Path(artifact_root) if artifact_root is not None else target_path.parent
    append_jsonl(target_path, [serialize_run_result(result, artifact_root=root, write_trace=write_trace)])
    return target_path


def write_results_jsonl(
    results: Iterable[TrialResult],
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    write_trace: bool = True,
) -> Path:
    target_path = Path(path)
    root = Path(artifact_root) if artifact_root is not None else target_path.parent
    result_list = list(results)
    write_jsonl(target_path, [serialize_run_result(r, artifact_root=root, write_trace=write_trace) for r in result_list])
    return target_path


def append_evaluation_jsonl(
    evaluation: EvaluationTrialResult,
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    write_trace: bool = True,
) -> Path:
    target_path = Path(path)
    root = Path(artifact_root) if artifact_root is not None else target_path.parent
    append_jsonl(target_path, [serialize_evaluation_result(evaluation, artifact_root=root, write_trace=write_trace)])
    return target_path


def write_evaluation_jsonl(
    evaluations: Iterable[EvaluationTrialResult],
    path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    write_trace: bool = True,
) -> Path:
    target_path = Path(path)
    root = Path(artifact_root) if artifact_root is not None else target_path.parent
    evaluation_list = list(evaluations)
    write_jsonl(target_path, [serialize_evaluation_result(e, artifact_root=root, write_trace=write_trace) for e in evaluation_list])
    return Path(path)
