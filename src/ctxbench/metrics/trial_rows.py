from __future__ import annotations

from typing import Any

from ctxbench.benchmark.selectors import RunSelector, matches_run_result
from ctxbench.metrics.io import ExperimentArtifacts, index_latest, index_votes, load_trace
from ctxbench.metrics.primary import normalize_primary
from ctxbench.util.logging import PhaseLogger


TRIAL_FIELDS = [
    "experimentId", "dataset_id", "dataset_version", "trialId", "instanceId", "taskId", "taskTags",
    "provider", "modelId", "modelName", "strategy", "format", "configuration", "repeatIndex",
    "response_present", "execution_status", "evaluation_present", "evaluation_status",
    "evaluation_method", "evaluation_method_consistent", "input_tokens", "output_tokens",
    "total_tokens", "cached_input_tokens", "cached_read_tokens", "reserved_tokens",
    "reasoning_tokens", "duration_ms", "duration_sec", "model_duration_ms", "tool_duration_ms",
    "model_calls", "tool_calls", "function_calls", "mcp_tool_calls", "steps",
    "primary_metric_name", "primary_success", "primary_score", "evaluation_input_tokens",
    "evaluation_output_tokens", "evaluation_duration_ms", "judge_count", "judge_error_count",
    "judge_agreement_mean", "judge_unanimous", "trace_available", "execution_trace_available",
    "eval_trace_available", "raw_response_available", "tool_calls_observable",
    "native_mcp_observable", "server_mcp_observable", "usage_observable", "error_observable",
    "error_message", "response_excerpt",
]

SUPPORTED_GROUP_FIELDS = {
    "experimentId", "dataset_id", "dataset_version", "provider", "modelId", "modelName",
    "strategy", "format", "configuration", "instanceId", "taskId", "taskTags", "repeatIndex",
    "evaluation_method", "primary_metric_name",
}
_warned_evaluation_statuses: set[str] = set()


def build_trial_rows(inputs: list[ExperimentArtifacts], logger: PhaseLogger) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifacts in inputs:
        responses = index_latest(artifacts.responses)
        evals = index_latest(artifacts.evals)
        votes = index_votes(artifacts.votes)
        for trial in artifacts.trials:
            rows.append(_build_row(artifacts, trial, responses, evals, votes, logger))
    return sorted(rows, key=lambda row: _sort_key(row, ["dataset_id", "experimentId", "trialId"]))


def apply_selectors(
    rows: list[dict[str, Any]],
    selector: RunSelector,
    *,
    evaluation_status: tuple[str, ...] = (),
    not_evaluation_status: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        selector_row = dict(row)
        selector_row["status"] = row.get("execution_status")
        if not matches_run_result(selector_row, selector):
            continue
        ev_status = row.get("evaluation_status")
        if evaluation_status and ev_status not in evaluation_status:
            continue
        if not_evaluation_status and ev_status in not_evaluation_status:
            continue
        selected.append(row)
    return selected


def parse_group_by(raw: str | None) -> list[str]:
    fields = [item.strip() for item in (raw or "dataset_id,configuration").split(",") if item.strip()]
    unknown = [field for field in fields if field not in SUPPORTED_GROUP_FIELDS]
    if unknown:
        raise ValueError(f"Unsupported --group-by field(s): {', '.join(unknown)}")
    return fields


def _build_row(
    artifacts: ExperimentArtifacts,
    trial: dict[str, Any],
    responses: dict[str, dict[str, Any]],
    evals: dict[str, dict[str, Any]],
    votes: dict[str, list[dict[str, Any]]],
    logger: PhaseLogger,
) -> dict[str, Any]:
    trial_id = str(trial.get("trialId") or "")
    response = responses.get(trial_id)
    evaluation = evals.get(trial_id)
    trial_votes = votes.get(trial_id, [])
    dataset = trial.get("dataset") if isinstance(trial.get("dataset"), dict) else {}
    metrics = response.get("metricsSummary") if isinstance(response, dict) and isinstance(response.get("metricsSummary"), dict) else {}
    usage = response.get("usage") if isinstance(response, dict) and isinstance(response.get("usage"), dict) else {}
    planned_method = trial.get("validationType")
    actual_method = evaluation.get("evaluationMethod") if isinstance(evaluation, dict) else None
    evaluation_method = actual_method
    _warn_unknown_evaluation_status(evaluation.get("status") if isinstance(evaluation, dict) else None, logger)
    method_consistent = _method_consistent(trial_id, planned_method, actual_method, logger)
    primary_name, primary_success, primary_score = normalize_primary(evaluation, logger)
    strategy = trial.get("strategy")
    configuration = _configuration(strategy, trial.get("format"), trial_id, logger)
    task_tags = trial.get("taskTags") if isinstance(trial.get("taskTags"), list) else []
    _validate_tags(task_tags, trial_id)
    duration_ms = _number(metrics.get("totalDurationMs"))
    exec_trace = load_trace(
        artifacts.root,
        response.get("traceRef") if isinstance(response, dict) else None,
        artifacts.root / "traces" / "executions" / f"{trial_id}.json",
    )
    eval_trace = load_trace(
        artifacts.root,
        evaluation.get("traceRef") if isinstance(evaluation, dict) else None,
        artifacts.root / "traces" / "evals" / f"{trial_id}.json",
    )
    execution_trace_available = exec_trace is not None or bool(response and response.get("traceRef"))
    eval_trace_available = eval_trace is not None or bool(evaluation and evaluation.get("traceRef"))
    return {
        "experimentId": trial.get("experimentId"),
        "dataset_id": dataset.get("id"),
        "dataset_version": dataset.get("version"),
        "trialId": trial_id,
        "instanceId": trial.get("instanceId"),
        "taskId": trial.get("taskId"),
        "taskTags": "|".join(str(tag) for tag in task_tags),
        "provider": trial.get("provider"),
        "modelId": trial.get("modelId"),
        "modelName": trial.get("modelName") or trial.get("model"),
        "strategy": strategy,
        "format": trial.get("format"),
        "configuration": configuration,
        "repeatIndex": trial.get("repeatIndex"),
        "response_present": response is not None,
        "execution_status": response.get("status") if response else None,
        "evaluation_present": evaluation is not None,
        "evaluation_status": evaluation.get("status") if evaluation else None,
        "evaluation_method": evaluation_method,
        "evaluation_method_consistent": method_consistent,
        "input_tokens": _number(metrics.get("inputTokens")),
        "output_tokens": _number(metrics.get("outputTokens")),
        "total_tokens": _number(metrics.get("totalTokens")),
        "cached_input_tokens": _number(metrics.get("cachedInputTokens")),
        "cached_read_tokens": _number(metrics.get("cacheReadInputTokens")),
        "reserved_tokens": _number(metrics.get("reservedTokens")),
        "reasoning_tokens": _number(usage.get("reasoningTokens")),
        "duration_ms": duration_ms,
        "duration_sec": duration_ms / 1000.0 if duration_ms is not None else None,
        "model_duration_ms": _number(metrics.get("modelDurationMs")),
        "tool_duration_ms": _number(metrics.get("toolDurationMs")),
        "model_calls": _number(metrics.get("modelCalls")),
        "tool_calls": _number(metrics.get("toolCalls")),
        "function_calls": _number(metrics.get("functionCalls")),
        "mcp_tool_calls": _number(metrics.get("mcpToolCalls")),
        "steps": _number(metrics.get("steps")),
        "primary_metric_name": primary_name,
        "primary_success": primary_success,
        "primary_score": primary_score,
        "evaluation_input_tokens": _number(evaluation.get("evaluationInputTokens")) if evaluation else None,
        "evaluation_output_tokens": _number(evaluation.get("evaluationOutputTokens")) if evaluation else None,
        "evaluation_duration_ms": _number(evaluation.get("evaluationDurationMs")) if evaluation else None,
        "judge_count": _judge_value(evaluation_method, evaluation, "judgeCount"),
        "judge_error_count": _judge_value(evaluation_method, evaluation, "judgeErrorCount"),
        "judge_agreement_mean": _judge_agreement_mean(evaluation_method, evaluation),
        "judge_unanimous": _judge_unanimous(evaluation_method, evaluation, trial_votes),
        "trace_available": execution_trace_available or eval_trace_available,
        "execution_trace_available": execution_trace_available,
        "eval_trace_available": eval_trace_available,
        "raw_response_available": bool(response and response.get("response")),
        "tool_calls_observable": _tool_calls_observable(metrics, exec_trace),
        "native_mcp_observable": _native_mcp_observable(strategy, metrics, exec_trace),
        "server_mcp_observable": _server_mcp_observable(exec_trace),
        "usage_observable": any(_number(metrics.get(key)) is not None for key in ("inputTokens", "outputTokens", "totalTokens")),
        "error_observable": bool(response and response.get("errorMessage")) or bool(exec_trace and exec_trace.get("error")),
        "error_message": response.get("errorMessage") if response else None,
        "response_excerpt": _excerpt(response.get("response") if response else None),
    }


def _configuration(strategy: Any, fmt: Any, trial_id: str, logger: PhaseLogger) -> str:
    if isinstance(strategy, str) and strategy:
        return f"{strategy}_{fmt}" if fmt else strategy
    logger.warn("METRICS", "metrics.configuration.unknown", "Missing trial strategy", trialId=trial_id)
    return "unknown"


def _validate_tags(tags: list[Any], trial_id: str) -> None:
    for tag in tags:
        if "|" in str(tag):
            raise ValueError(f"taskTags contains reserved pipe character for trialId {trial_id}: {tag}")


def _method_consistent(trial_id: str, planned: Any, actual: Any, logger: PhaseLogger) -> bool | None:
    if planned is None and actual is None:
        return None
    if planned is not None and actual is not None and planned != actual:
        logger.warn(
            "METRICS",
            "metrics.evaluation_method.mismatch",
            "Planned and actual evaluation methods differ",
            trialId=trial_id,
            plannedEvaluationMethod=planned,
            evaluationMethod=actual,
        )
        return False
    return True


def _warn_unknown_evaluation_status(status: Any, logger: PhaseLogger) -> None:
    if status is None or status in {"evaluated", "partial", "error", "skipped"}:
        return
    key = str(status)
    if key in _warned_evaluation_statuses:
        return
    _warned_evaluation_statuses.add(key)
    logger.warn("METRICS", "metrics.evaluation_status.unknown", "Unknown evaluation status", evaluationStatus=status)


def _judge_value(method: Any, evaluation: dict[str, Any] | None, key: str) -> float | None:
    if method != "judge" or not evaluation:
        return None
    return _number(evaluation.get(key))


def _judge_agreement_mean(method: Any, evaluation: dict[str, Any] | None) -> float | None:
    if method != "judge" or not evaluation:
        return None
    outcome = evaluation.get("outcome") if isinstance(evaluation.get("outcome"), dict) else {}
    values = []
    for key in ("correctness", "completeness"):
        item = outcome.get(key) if isinstance(outcome.get(key), dict) else {}
        normalized = _agreement_bool(item.get("agreement"))
        if normalized is None:
            return None
        values.append(1.0 if normalized else 0.0)
    return sum(values) / len(values)


def _judge_unanimous(method: Any, evaluation: dict[str, Any] | None, votes: list[dict[str, Any]]) -> bool | None:
    if method != "judge":
        return None
    valid_votes = [vote for vote in votes if vote.get("status") != "error" and not vote.get("error")]
    if len(valid_votes) >= 2:
        ratings: set[tuple[Any, Any]] = set()
        for vote in valid_votes:
            criterias = vote.get("criterias") if isinstance(vote.get("criterias"), dict) else {}
            correctness = criterias.get("correctness") if isinstance(criterias.get("correctness"), dict) else {}
            completeness = criterias.get("completeness") if isinstance(criterias.get("completeness"), dict) else {}
            ratings.add((correctness.get("rating"), completeness.get("rating")))
        return len(ratings) == 1
    if votes:
        return None
    if not evaluation:
        return None
    outcome = evaluation.get("outcome") if isinstance(evaluation.get("outcome"), dict) else {}
    correctness = outcome.get("correctness") if isinstance(outcome.get("correctness"), dict) else {}
    completeness = outcome.get("completeness") if isinstance(outcome.get("completeness"), dict) else {}
    c_agree = _agreement_bool(correctness.get("agreement"))
    k_agree = _agreement_bool(completeness.get("agreement"))
    if c_agree is None or k_agree is None:
        return None
    return c_agree and k_agree


def _agreement_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1, 0.0, 1.0):
        return bool(value)
    return None


def _tool_calls_observable(metrics: dict[str, Any], trace: dict[str, Any] | None) -> bool:
    if any(_number(metrics.get(key)) is not None for key in ("toolCalls", "functionCalls", "mcpToolCalls")):
        return True
    if not trace:
        return False
    if isinstance(trace.get("toolCalls"), list) and trace["toolCalls"]:
        return True
    events = ((trace.get("aiTrace") or {}).get("events") if isinstance(trace.get("aiTrace"), dict) else None)
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and (event.get("type") in {"mcp.tool_call", "mcp.tool_result"} or event.get("name") in {"mcp.tool_call", "mcp.tool_result"}):
                return True
    return False


def _native_mcp_observable(strategy: Any, metrics: dict[str, Any], trace: dict[str, Any] | None) -> bool:
    if strategy in {"local_mcp", "remote_mcp"} and (_number(metrics.get("mcpToolCalls")) or 0) > 0:
        return True
    return bool(trace and isinstance(trace.get("nativeMcp"), dict) and trace.get("nativeMcp"))


def _server_mcp_observable(trace: dict[str, Any] | None) -> bool | None:
    if trace is None:
        return None
    return bool(isinstance(trace.get("serverMcp"), list) and trace.get("serverMcp"))


def _excerpt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= 280 else text[:280] + "…"


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _sort_key(row: dict[str, Any], fields: list[str]) -> tuple[str, ...]:
    return tuple("" if row.get(field) is None else str(row.get(field)) for field in fields)
