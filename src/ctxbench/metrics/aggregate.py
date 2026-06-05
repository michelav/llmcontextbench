from __future__ import annotations

import math
from statistics import median
from typing import Any


EFFECTIVENESS_FIELDS = [
    "n_trials", "n_evaluated", "primary_metric_name", "primary_success_count",
    "primary_success_rate", "primary_score_mean", "primary_score_median", "primary_score_stddev",
]
EFFICIENCY_FIELDS = [
    "n_trials", "n_responses", "primary_success_count", "total_tokens_mean", "total_tokens_median",
    "total_tokens_p95", "total_tokens_sum", "tokens_per_primary_success", "duration_sec_mean",
    "duration_sec_median", "duration_sec_p95", "duration_sec_sum", "duration_sec_per_primary_success",
    "model_calls_mean", "tool_calls_mean", "function_calls_mean", "mcp_tool_calls_mean",
    "steps_mean", "total_calls_sum", "calls_per_primary_success",
]
ROBUSTNESS_FIELDS = [
    "robustness_axis", "n_groups", "primary_success_rate_mean", "primary_success_rate_min",
    "primary_success_rate_max", "primary_success_rate_range", "primary_score_mean",
    "primary_score_stddev", "duration_sec_stddev", "total_tokens_stddev",
]
EVALUATION_RELIABILITY_FIELDS = [
    "evaluation_method", "n_trials", "n_evaluated", "evaluation_coverage_rate",
    "evaluation_success_rate", "evaluation_error_rate", "evaluation_skipped_rate",
    "n_evaluation_status_other", "judge_count_mean", "judge_error_rate", "judge_agreement_mean",
    "judge_unanimity_rate", "evaluation_tokens_mean", "evaluation_duration_sec_median",
]
OBSERVABILITY_FIELDS = [
    "n_trials", "trace_coverage_rate", "execution_trace_coverage_rate", "eval_trace_coverage_rate",
    "raw_response_coverage_rate", "tool_call_observability_rate", "native_mcp_observability_rate",
    "server_mcp_observability_rate", "usage_observability_rate", "error_observability_rate",
]
AGGREGATE_FIELDS = [
    "n_trials", "n_responses", "n_evaluated", "primary_metric_name", "primary_success_rate",
    "primary_score_mean", "primary_score_stddev", "total_tokens_mean", "total_tokens_median",
    "total_tokens_p95", "tokens_per_primary_success", "duration_sec_median", "duration_sec_p95",
    "duration_sec_per_primary_success", "model_calls_mean", "tool_calls_mean", "function_calls_mean",
    "mcp_tool_calls_mean", "calls_per_primary_success", "primary_success_rate_range_by_task",
    "primary_success_rate_range_by_instance", "primary_success_rate_range_by_repeat",
    "primary_success_rate_range_by_model", "primary_success_rate_range_by_format",
    "evaluation_coverage_rate", "evaluation_success_rate", "evaluation_error_rate",
    "judge_agreement_mean", "judge_unanimity_rate", "trace_coverage_rate",
    "tool_call_observability_rate", "usage_observability_rate",
]

ROBUSTNESS_AXES = {
    "task": ("taskId",),
    "instance": ("instanceId",),
    "repeat": ("taskId", "instanceId", "repeatIndex"),
    "model": ("modelId",),
    "format": ("format",),
}


def compute_all(rows: list[dict[str, Any]], group_fields: list[str]) -> dict[str, Any]:
    grouped = _group_rows(rows, group_fields)
    effectiveness = [_with_group(key, group_fields, _effectiveness(items)) for key, items in grouped]
    efficiency = [_with_group(key, group_fields, _efficiency(items)) for key, items in grouped]
    evaluation = [_with_group(key, group_fields, _evaluation_reliability(items)) for key, items in grouped]
    observability = [_with_group(key, group_fields, _observability(items)) for key, items in grouped]
    robustness = []
    robustness_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for key, items in grouped:
        ranges: dict[str, Any] = {}
        for axis, axis_fields in ROBUSTNESS_AXES.items():
            row = _with_group(key, group_fields, _robustness(items, axis, axis_fields))
            robustness.append(row)
            ranges[f"primary_success_rate_range_by_{axis}"] = row.get("primary_success_rate_range")
        robustness_by_key[key] = ranges
    aggregate = []
    for idx, (key, _) in enumerate(grouped):
        merged = {field: key[pos] for pos, field in enumerate(group_fields)}
        for source in (effectiveness[idx], efficiency[idx], evaluation[idx], observability[idx]):
            for item_key, value in source.items():
                if item_key not in group_fields:
                    merged[item_key] = value
        merged.update(robustness_by_key.get(key, {}))
        aggregate.append({field: merged.get(field) for field in [*group_fields, *AGGREGATE_FIELDS]})
    return {
        "effectiveness": effectiveness,
        "efficiency": efficiency,
        "robustness": sorted(robustness, key=lambda row: _sort_key(row, group_fields + ["robustness_axis"])),
        "evaluation_reliability": evaluation,
        "observability": observability,
        "aggregate": aggregate,
        "dimension_summary": _dimension_summary(group_fields, effectiveness, efficiency, robustness, evaluation, observability),
        "summary": _summary(rows, aggregate),
    }


def failure_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = [
        "dataset_id", "experimentId", "trialId", "taskId", "instanceId", "modelId", "configuration",
        "execution_status", "evaluation_status", "evaluation_method", "primary_metric_name",
        "primary_success", "primary_score", "error_message", "response_excerpt",
    ]
    failures = []
    for row in rows:
        include = (
            (row.get("response_present") is True and row.get("execution_status") != "success")
            or row.get("evaluation_status") in {"error", "skipped"}
            or row.get("primary_success") is False
            or (row.get("primary_success") is None and row.get("evaluation_present") is True)
        )
        if include:
            failures.append({field: row.get(field) for field in fields})
    return sorted(failures, key=lambda row: _sort_key(row, ["dataset_id", "experimentId", "trialId"]))


def _effectiveness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({row.get("primary_metric_name") for row in rows if row.get("primary_metric_name") is not None})
    mixed = len(names) > 1
    scores = _numbers(row.get("primary_score") for row in rows)
    successes = [row.get("primary_success") for row in rows if row.get("primary_success") is not None]
    success_count = sum(1 for item in successes if item is True)
    return {
        "n_trials": len(rows),
        "n_evaluated": sum(1 for row in rows if row.get("evaluation_present") is True),
        "primary_metric_name": "mixed" if mixed else (names[0] if names else None),
        "primary_success_count": success_count,
        "primary_success_rate": success_count / len(successes) if successes else None,
        "primary_score_mean": None if mixed else mean(scores),
        "primary_score_median": None if mixed else (median(scores) if scores else None),
        "primary_score_stddev": None if mixed else sample_stddev(scores),
    }


def _efficiency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_tokens = _numbers(row.get("total_tokens") for row in rows)
    duration = _numbers(row.get("duration_sec") for row in rows)
    success_count = sum(1 for row in rows if row.get("primary_success") is True)
    total_calls_values = [_total_calls(row) for row in rows]
    total_calls_values = [item for item in total_calls_values if item is not None]
    total_tokens_sum = sum(total_tokens) if total_tokens else None
    duration_sum = sum(duration) if duration else None
    total_calls_sum = sum(total_calls_values) if total_calls_values else None
    return {
        "n_trials": len(rows),
        "n_responses": sum(1 for row in rows if row.get("response_present") is True),
        "primary_success_count": success_count,
        "total_tokens_mean": mean(total_tokens),
        "total_tokens_median": median(total_tokens) if total_tokens else None,
        "total_tokens_p95": percentile(total_tokens, 95),
        "total_tokens_sum": total_tokens_sum,
        "tokens_per_primary_success": _per_success(total_tokens_sum, success_count),
        "duration_sec_mean": mean(duration),
        "duration_sec_median": median(duration) if duration else None,
        "duration_sec_p95": percentile(duration, 95),
        "duration_sec_sum": duration_sum,
        "duration_sec_per_primary_success": _per_success(duration_sum, success_count),
        "model_calls_mean": mean(_numbers(row.get("model_calls") for row in rows)),
        "tool_calls_mean": mean(_numbers(row.get("tool_calls") for row in rows)),
        "function_calls_mean": mean(_numbers(row.get("function_calls") for row in rows)),
        "mcp_tool_calls_mean": mean(_numbers(row.get("mcp_tool_calls") for row in rows)),
        "steps_mean": mean(_numbers(row.get("steps") for row in rows)),
        "total_calls_sum": total_calls_sum,
        "calls_per_primary_success": _per_success(total_calls_sum, success_count),
    }


def _robustness(rows: list[dict[str, Any]], axis: str, axis_fields: tuple[str, ...]) -> dict[str, Any]:
    grouped = _group_rows(rows, list(axis_fields))
    rates: list[float] = []
    scores: list[float] = []
    durations: list[float] = []
    tokens: list[float] = []
    for _, items in grouped:
        successes = [row.get("primary_success") for row in items if row.get("primary_success") is not None]
        if successes:
            rates.append(sum(1 for item in successes if item is True) / len(successes))
        scores.extend(_numbers(row.get("primary_score") for row in items))
        durations.extend(_numbers(row.get("duration_sec") for row in items))
        tokens.extend(_numbers(row.get("total_tokens") for row in items))
    enough = len(grouped) >= 2
    rate_min = min(rates) if enough and rates else None
    rate_max = max(rates) if enough and rates else None
    return {
        "robustness_axis": axis,
        "n_groups": len(grouped),
        "primary_success_rate_mean": mean(rates) if enough else None,
        "primary_success_rate_min": rate_min,
        "primary_success_rate_max": rate_max,
        "primary_success_rate_range": (rate_max - rate_min) if rate_min is not None and rate_max is not None else None,
        "primary_score_mean": mean(scores) if enough else None,
        "primary_score_stddev": sample_stddev(scores) if enough else None,
        "duration_sec_stddev": sample_stddev(durations) if enough else None,
        "total_tokens_stddev": sample_stddev(tokens) if enough else None,
    }


def _evaluation_reliability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [row.get("evaluation_status") for row in rows if row.get("evaluation_present") is True]
    methods = sorted({row.get("evaluation_method") for row in rows if row.get("evaluation_method") is not None})
    judge_counts = _numbers(row.get("judge_count") for row in rows)
    judge_errors = _numbers(row.get("judge_error_count") for row in rows)
    judge_total = sum(judge_counts) if judge_counts else None
    eval_tokens = []
    for row in rows:
        tokens = [row.get("evaluation_input_tokens"), row.get("evaluation_output_tokens")]
        nums = _numbers(tokens)
        if nums:
            eval_tokens.append(sum(nums))
    eval_duration_sec = [value / 1000.0 for value in _numbers(row.get("evaluation_duration_ms") for row in rows)]
    return {
        "evaluation_method": "mixed" if len(methods) > 1 else (methods[0] if methods else None),
        "n_trials": len(rows),
        "n_evaluated": sum(1 for row in rows if row.get("evaluation_present") is True),
        "evaluation_coverage_rate": _rate(sum(1 for row in rows if row.get("evaluation_present") is True), len(rows)),
        "evaluation_success_rate": _rate(sum(1 for status in statuses if status in {"evaluated", "partial"}), len(rows)),
        "evaluation_error_rate": _rate(sum(1 for status in statuses if status == "error"), len(rows)),
        "evaluation_skipped_rate": _rate(sum(1 for status in statuses if status == "skipped"), len(rows)),
        "n_evaluation_status_other": sum(1 for status in statuses if status not in {"evaluated", "partial", "error", "skipped"}),
        "judge_count_mean": mean(judge_counts),
        "judge_error_rate": (sum(judge_errors) / judge_total) if judge_errors and judge_total else None,
        "judge_agreement_mean": mean(_numbers(row.get("judge_agreement_mean") for row in rows)),
        "judge_unanimity_rate": _bool_rate(row.get("judge_unanimous") for row in rows),
        "evaluation_tokens_mean": mean(eval_tokens),
        "evaluation_duration_sec_median": median(eval_duration_sec) if eval_duration_sec else None,
    }


def _observability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n_trials": len(rows),
        "trace_coverage_rate": _flag_rate(rows, "trace_available"),
        "execution_trace_coverage_rate": _flag_rate(rows, "execution_trace_available"),
        "eval_trace_coverage_rate": _flag_rate(rows, "eval_trace_available"),
        "raw_response_coverage_rate": _flag_rate(rows, "raw_response_available"),
        "tool_call_observability_rate": _flag_rate(rows, "tool_calls_observable"),
        "native_mcp_observability_rate": _flag_rate(rows, "native_mcp_observable"),
        "server_mcp_observability_rate": _flag_rate(rows, "server_mcp_observable"),
        "usage_observability_rate": _flag_rate(rows, "usage_observable"),
        "error_observability_rate": _flag_rate(rows, "error_observable"),
    }


def _summary(rows: list[dict[str, Any]], aggregate: list[dict[str, Any]]) -> dict[str, Any]:
    names = sorted({row.get("primary_metric_name") for row in rows if row.get("primary_metric_name") is not None})
    total_tokens = _numbers(row.get("total_tokens") for row in rows)
    duration = _numbers(row.get("duration_sec") for row in rows)
    evaluation = _evaluation_reliability(rows)
    observability = _observability(rows)
    effectiveness = _effectiveness(rows)
    return {
        "schemaVersion": "1.0",
        "experiments": len({row.get("experimentId") for row in rows if row.get("experimentId") is not None}),
        "datasets": sorted({row.get("dataset_id") for row in rows if row.get("dataset_id") is not None}),
        "n_trials": len(rows),
        "n_responses": sum(1 for row in rows if row.get("response_present") is True),
        "n_evaluated": sum(1 for row in rows if row.get("evaluation_present") is True),
        "primary_metric_name": "mixed" if len(names) > 1 else (names[0] if names else None),
        "primary_success_rate": effectiveness.get("primary_success_rate"),
        "total_tokens_sum": sum(total_tokens) if total_tokens else None,
        "duration_sec_median": median(duration) if duration else None,
        "evaluation_success_rate": evaluation.get("evaluation_success_rate"),
        "trace_coverage_rate": observability.get("trace_coverage_rate"),
    }


def _dimension_summary(group_fields: list[str], effectiveness: list[dict[str, Any]], efficiency: list[dict[str, Any]], robustness: list[dict[str, Any]], evaluation: list[dict[str, Any]], observability: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [
        ("effectiveness", effectiveness, ["primary_success_rate"]),
        ("efficiency", efficiency, ["tokens_per_primary_success"]),
        ("evaluation_reliability", evaluation, ["evaluation_coverage_rate", "judge_unanimity_rate"]),
        ("observability", observability, ["trace_coverage_rate"]),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, source_rows, metrics in selected:
        for source in source_rows:
            for metric in metrics:
                rows.append(_summary_row(dimension, group_fields, source, metric, source.get(metric)))
    for source in robustness:
        metric = f"primary_success_rate_range_by_{source.get('robustness_axis')}"
        rows.append(_summary_row("robustness", group_fields, source, metric, source.get("primary_success_rate_range")))
    return sorted(rows, key=lambda row: _sort_key(row, ["dimension", "group_key", "metric"]))


def _summary_row(dimension: str, group_fields: list[str], source: dict[str, Any], metric: str, value: Any) -> dict[str, Any]:
    row = {"dimension": dimension, "group_key": "|".join("" if source.get(field) is None else str(source.get(field)) for field in group_fields)}
    row.update({field: source.get(field) for field in group_fields})
    row.update({"metric": metric, "value": value})
    return row


def _group_rows(rows: list[dict[str, Any]], fields: list[str]) -> list[tuple[tuple[Any, ...], list[dict[str, Any]]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        groups.setdefault(key, []).append(row)
    return sorted(groups.items(), key=lambda item: tuple("" if value is None else str(value) for value in item[0]))


def _with_group(key: tuple[Any, ...], fields: list[str], values: dict[str, Any]) -> dict[str, Any]:
    row = {field: key[index] for index, field in enumerate(fields)}
    row.update(values)
    return row


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def sample_stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def percentile(values: list[float], q: float) -> float | None:
    if len(values) < 2:
        return None
    data = sorted(values)
    pos = (len(data) - 1) * q / 100.0
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return data[int(pos)]
    return data[lower] + (data[upper] - data[lower]) * (pos - lower)


def _numbers(values: Any) -> list[float]:
    return [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def _per_success(value: float | None, success_count: int) -> float | None:
    return value / success_count if value is not None and success_count > 0 else None


def _total_calls(row: dict[str, Any]) -> float | None:
    values = [row.get(field) for field in ("model_calls", "tool_calls", "function_calls", "mcp_tool_calls")]
    if not any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    return sum(float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool))


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def _bool_rate(values: Any) -> float | None:
    observed = [value for value in values if isinstance(value, bool)]
    return sum(1 for value in observed if value) / len(observed) if observed else None


def _flag_rate(rows: list[dict[str, Any]], field: str) -> float | None:
    observed = [row.get(field) for row in rows if isinstance(row.get(field), bool)]
    return sum(1 for item in observed if item) / len(observed) if observed else None


def _sort_key(row: dict[str, Any], fields: list[str]) -> tuple[str, ...]:
    return tuple("" if row.get(field) is None else str(row.get(field)) for field in fields)

