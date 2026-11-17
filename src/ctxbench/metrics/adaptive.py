"""Request-level outcomes and per-attempt diagnostics for adaptive artifacts."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from ctxbench.util.fs import load_json


REQUEST_FIELDS = [
    "requestId", "sequenceIndex", "taskId", "instanceId", "state", "terminalReason", "delivered",
    "privileged", "failureCategory", "policyId", "policyVersion",
    "candidateId", "executionId", "attemptId", "attemptCount",
    "requestDurationMs", "requestDurationProvenance",
    "generationDurationMs", "generationDurationProvenance",
    "generationInputTokens", "generationOutputTokens", "generationTotalTokens",
    "generationTotalTokensProvenance", "generationUsageCompleteness",
    "assessorDurationMs", "assessorDurationProvenance", "assessorTotalTokens",
    "assessorTokenProvenance", "knownAssessorTotalTokens",
    "nonDeliveredAttemptCount", "knownNonDeliveredInputTokens",
    "knownNonDeliveredOutputTokens", "knownNonDeliveredTotalTokens",
    "nonDeliveredUsageCompleteness",
    "deliveredInputTokens", "deliveredOutputTokens", "deliveredTotalTokens",
    "deliveredTokenProvenance",
    "evaluationInputTokens", "evaluationOutputTokens", "evaluationTotalTokens",
    "evaluationTokenProvenance",
    "evaluationDurationMs", "evaluationStatus", "evaluationMethod",
    "correctnessRating", "correctnessAgreement", "completenessRating", "completenessAgreement",
]
ATTEMPT_FIELDS = [
    "requestId", "candidateId", "executionId", "attemptId", "attemptIndex",
    "implementationDigest",
    "executionStatus", "startedAt", "finishedAt", "durationMs",
    "generationDurationMs", "generationDurationProvenance",
    "inputTokens", "outputTokens", "totalTokens", "tokenProvenance", "delivered",
    "failureCategory", "accepted", "injectedDelayMs", "injectedFailures",
    "assessorDurationMs", "assessorDurationProvenance", "assessorTotalTokens",
    "assessorTokenProvenance", "knownAssessorTotalTokens",
]


def build_adaptive_metrics(root: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifact_root = Path(root)
    from ctxbench.adaptive.projections import rebuild_adaptive_responses
    rebuild_adaptive_responses(artifact_root)
    request_records: list[dict[str, Any]] = []
    manifest = load_json(artifact_root / "manifest.json")
    plan = load_json(artifact_root / "adaptive-plan.json")
    policy = plan.get("policy") if isinstance(plan, dict) else {}
    policy_id = policy.get("id") if isinstance(policy, dict) else None
    policy_version = policy.get("version") if isinstance(policy, dict) else None
    declared_signal_ids = [str(row["id"]) for row in plan.get("signals", [])
                           if isinstance(row, dict) and row.get("id")]
    signal_ids = list(dict.fromkeys([
        "latency_ms", "total_tokens", "input_tokens", "output_tokens", "cached_input_tokens",
        "reasoning_tokens", "model_calls", "tool_calls", "failed", "accepted", *declared_signal_ids,
    ]))
    privileged = bool(manifest.get("privileged")) if isinstance(manifest, dict) else False
    by_request: dict[str, list[dict[str, Any]]] = {}
    records_root = artifact_root / "execution-records"
    if records_root.exists():
        for path in records_root.glob("*/*.json"):
            attempt = load_json(path)
            if not isinstance(attempt, dict) or attempt.get("executionRecordVersion") != 1:
                continue
            correlation = attempt.get("correlationId")
            if isinstance(correlation, str):
                by_request.setdefault(correlation, []).append(attempt)
    responses_path = artifact_root / "responses.jsonl"
    evals_path = artifact_root / "evals.jsonl"
    responses = _index_jsonl(responses_path, "requestId")
    evaluations = _index_jsonl(evals_path, "requestId", fallback="responseId")
    ledger = artifact_root / "adaptive-records"
    if ledger.exists():
        for path in sorted(ledger.glob("*.json")):
            record = load_json(path)
            if not isinstance(record, dict) or record.get("schemaVersion") != 3:
                raise ValueError(f"Unsupported adaptive request record: {path}")
            request_id = str(record.get("requestId") or "")
            if not request_id:
                raise ValueError(f"Missing requestId in {path}")
            delivery = record.get("delivery") if isinstance(record.get("delivery"), dict) else {}
            attempts = sorted(by_request.get(request_id, []), key=lambda row: row.get("attemptIndex", 0))
            response = responses.get(request_id, {})
            evaluation = evaluations.get(request_id, {})
            outcome = evaluation.get("outcome") if isinstance(evaluation.get("outcome"), dict) else {}
            correctness = outcome.get("correctness") if isinstance(outcome.get("correctness"), dict) else {}
            completeness = outcome.get("completeness") if isinstance(outcome.get("completeness"), dict) else {}
            generation_in, generation_out = _sum_usage(attempts)
            delivered_usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            delivered_metrics = response.get("metricsSummary") if isinstance(response.get("metricsSummary"), dict) else {}
            eval_in, eval_out = evaluation.get("evaluationInputTokens"), evaluation.get("evaluationOutputTokens")
            request_duration = record.get("requestDurationMs")
            if not isinstance(request_duration, (int, float)) or isinstance(request_duration, bool):
                request_duration = None
            all_attempt_totals_known = bool(attempts) and all(
                _attempt_total_tokens(row) is not None for row in attempts
            )
            ledger_attempts = record.get("attempts") if isinstance(record.get("attempts"), list) else []
            assessor_cost = _combine_assessor_costs(
                [item.get("assessorCost", []) for item in ledger_attempts if isinstance(item, dict)]
            )
            observation = (ledger_attempts[0].get("observation")
                           if ledger_attempts and isinstance(ledger_attempts[0], dict) else {})
            delivered_attempt_ids = {str(delivery.get("attemptId"))} if delivery.get("attemptId") else set()
            non_delivered = [row for row in attempts if row.get("attemptId") not in delivered_attempt_ids]
            non_delivered_in, non_delivered_out, non_delivered_complete = _sum_attempt_usage(non_delivered)
            request_records.append({
                "requestId": request_id,
                "sequenceIndex": record.get("sequenceIndex"),
                "taskId": record.get("taskId"),
                "instanceId": record.get("instanceId"),
                "state": record.get("state"),
                "terminalReason": record.get("terminalReason"),
                "delivered": record.get("state") == "delivered",
                "privileged": privileged,
                "failureCategory": observation.get("failureCategory") if isinstance(observation, dict) else None,
                "policyId": policy_id,
                "policyVersion": policy_version,
                **{f"labels.{key}": value for key, value in (record.get("labels") or {}).items()},
                "candidateId": delivery.get("candidateId"),
                "executionId": delivery.get("executionId"),
                "attemptId": delivery.get("attemptId"),
                "attemptCount": len(attempts),
                "requestDurationMs": request_duration,
                "requestDurationProvenance": record.get("requestDurationProvenance", "unavailable"),
                **_generation_duration(attempts),
                "generationInputTokens": generation_in,
                "generationOutputTokens": generation_out,
                "generationTotalTokens": _sum_known(generation_in, generation_out),
                "generationTotalTokensProvenance": "derived" if all_attempt_totals_known else "unavailable",
                "generationUsageCompleteness": _usage_completeness(attempts),
                **assessor_cost,
                "nonDeliveredAttemptCount": len(non_delivered),
                "knownNonDeliveredInputTokens": non_delivered_in,
                "knownNonDeliveredOutputTokens": non_delivered_out,
                "knownNonDeliveredTotalTokens": _sum_known(non_delivered_in, non_delivered_out),
                "nonDeliveredUsageCompleteness": non_delivered_complete,
                "deliveredInputTokens": delivered_usage.get("inputTokens"),
                "deliveredOutputTokens": delivered_usage.get("outputTokens"),
                "deliveredTotalTokens": delivered_usage.get("totalTokens"),
                "deliveredTokenProvenance": delivered_metrics.get("totalTokensProvenance", "unavailable"),
                "evaluationInputTokens": eval_in,
                "evaluationOutputTokens": eval_out,
                "evaluationTotalTokens": evaluation.get("evaluationTotalTokens"),
                "evaluationTokenProvenance": "reported" if eval_in is not None or eval_out is not None else "unavailable",
                "evaluationDurationMs": evaluation.get("evaluationDurationMs"),
                "evaluationStatus": evaluation.get("status"),
                "evaluationMethod": evaluation.get("evaluationMethod"),
                "correctnessRating": correctness.get("rating"),
                "correctnessAgreement": correctness.get("agreement"),
                "completenessRating": completeness.get("rating"),
                "completenessAgreement": completeness.get("agreement"),
            })
    attempt_rows = []
    deliveries = {
        str(row.get("delivery", {}).get("attemptId"))
        for path in ledger.glob("*.json") for row in [load_json(path)]
        if isinstance(row, dict) and isinstance(row.get("delivery"), dict)
    } if ledger.exists() else set()
    for request_id, attempts in by_request.items():
        for attempt in sorted(attempts, key=lambda row: row.get("attemptIndex", 0)):
            result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
            adaptive_signals = result.get("_adaptiveSignals") if isinstance(result.get("_adaptiveSignals"), dict) else {}
            assessor_cost = _combine_assessor_costs([adaptive_signals.get("assessorCost", [])])
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            started, finished = attempt.get("startedAt"), attempt.get("finishedAt")
            signal_values = adaptive_signals.get("signals") if isinstance(adaptive_signals.get("signals"), dict) else {}
            disturbance_rows = adaptive_signals.get("disturbances") if isinstance(adaptive_signals.get("disturbances"), list) else []
            attempt_rows.append({
                "requestId": request_id,
                "candidateId": attempt.get("candidateId"),
                "executionId": attempt.get("executionId"),
                "attemptId": attempt.get("attemptId"),
                "attemptIndex": attempt.get("attemptIndex"),
                "implementationDigest": adaptive_signals.get("implementationDigest"),
                "executionStatus": result.get("status", attempt.get("state")),
                "startedAt": started,
                "finishedAt": finished,
                # Attempt wall time, including online assessment; generationDurationMs excludes it.
                "durationMs": _duration_ms(started, finished),
                **_generation_duration([attempt]),
                "inputTokens": usage.get("inputTokens"),
                "outputTokens": usage.get("outputTokens"),
                "totalTokens": usage.get("totalTokens"),
                "tokenProvenance": (result.get("metricsSummary") or {}).get("totalTokensProvenance", "unavailable"),
                "delivered": attempt.get("attemptId") in deliveries,
                "failureCategory": adaptive_signals.get("failureCategory"),
                "accepted": adaptive_signals.get("accepted"),
                "injectedDelayMs": sum(
                    int(row.get("appliedDelayMs", 0)) for row in disturbance_rows
                    if isinstance(row, dict) and type(row.get("appliedDelayMs", 0)) in (int, float)
                ),
                "injectedFailures": sum(
                    int(row.get("injectedFailures", 0)) for row in disturbance_rows
                    if isinstance(row, dict) and type(row.get("injectedFailures", 0)) in (int, float)
                ),
                **{name: (signal_values.get(name) or {}).get("value") for name in signal_ids},
                **{f"{name}Provenance": (signal_values.get(name) or {}).get("provenance", "unavailable")
                   for name in signal_ids},
                **assessor_cost,
            })
    request_records.sort(key=lambda row: (row.get("sequenceIndex") or 0, row["requestId"]))
    attempt_rows.sort(key=lambda row: (row["requestId"], row.get("attemptIndex") or 0))
    return request_records, attempt_rows


GOAL_FIELDS = ["requestId", "sequenceIndex", "goalId", "signal", "statistic", "scope", "window",
               "status", "value", "provenance", "sampleCount", "missingCount", "boundType", "bound"]


def build_adaptive_goal_metrics(root: str | Path) -> list[dict[str, Any]]:
    from ctxbench.adaptive.artifacts import adaptive_plan_from_payload, load_adaptive_request_records
    artifact_root = Path(root)
    payload = load_json(artifact_root / "adaptive-plan.json")
    plan = adaptive_plan_from_payload(payload)
    records = list(load_adaptive_request_records(artifact_root).values())
    if not plan.goals:
        return []
    from ctxbench.adaptive.goals import evaluate_goals
    return evaluate_goals(
        records, plan.goals, candidates=[row.candidate_id for row in plan.candidates],
        signals=plan.signals, default_window=plan.window,
    )


def write_adaptive_metrics(output_dir: Path, requests: list[dict[str, Any]], attempts: list[dict[str, Any]],
                           goals: list[dict[str, Any]] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    request_fields = [*REQUEST_FIELDS, *_dynamic_fields(requests, "labels.")]
    attempt_fields = [*ATTEMPT_FIELDS, *_signal_fields(attempts)]
    _write_csv(output_dir / "adaptive_request_metrics.csv", request_fields, requests)
    _write_csv(output_dir / "adaptive_attempt_metrics.csv", attempt_fields, attempts)
    _write_csv(output_dir / "adaptive_goal_metrics.csv", GOAL_FIELDS, goals or [])


def _dynamic_fields(rows: list[dict[str, Any]], prefix: str) -> list[str]:
    return sorted({key for row in rows for key in row if key.startswith(prefix)})


def _signal_fields(rows: list[dict[str, Any]]) -> list[str]:
    excluded = {"assessorDurationProvenance", "assessorTokenProvenance", "generationDurationProvenance",
                "tokenProvenance"}
    return sorted({key for row in rows for key in row
                   if key not in ATTEMPT_FIELDS and key not in excluded
                   and (key.endswith("Provenance") or key in row)})


def _index_jsonl(path: Path, primary: str, fallback: str | None = None) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    import json
    result = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            key = row.get(primary) or (row.get(fallback) if fallback else None)
            if key:
                result[str(key)] = row
    return result


def _sum_usage(attempts: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    inputs: list[int] = []
    outputs: list[int] = []
    for attempt in attempts:
        result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        for target, key in ((inputs, "inputTokens"), (outputs, "outputTokens")):
            value = usage.get(key)
            if type(value) is int and value >= 0:
                target.append(value)
    return (sum(inputs) if inputs else None, sum(outputs) if outputs else None)


def _sum_attempt_usage(attempts: list[dict[str, Any]]) -> tuple[int | None, int | None, str]:
    input_total, output_total = _sum_usage(attempts)
    if not attempts:
        return 0, 0, "complete"
    complete = all(
        _attempt_total_tokens(row) is not None
        and isinstance((row.get("result") or {}).get("usage"), dict)
        and type((row.get("result") or {}).get("usage", {}).get("inputTokens")) is int
        and type((row.get("result") or {}).get("usage", {}).get("outputTokens")) is int
        for row in attempts
    )
    if complete:
        return input_total, output_total, "complete"
    if input_total is not None or output_total is not None:
        return input_total, output_total, "partial"
    return None, None, "unavailable"


def _usage_completeness(attempts: list[dict[str, Any]]) -> str:
    return _sum_attempt_usage(attempts)[2]


def _sum_known(first: int | None, second: int | None) -> int | None:
    return first + second if first is not None and second is not None else None


def _attempt_total_tokens(attempt: dict[str, Any]) -> int | None:
    result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
    metrics = result.get("metricsSummary") if isinstance(result.get("metricsSummary"), dict) else {}
    value = metrics.get("totalTokens")
    return value if type(value) is int and value >= 0 and metrics.get("totalTokensProvenance") != "unavailable" else None


def _request_duration_ms(attempts: list[dict[str, Any]]) -> int | None:
    from datetime import datetime
    starts = [row.get("startedAt") for row in attempts if isinstance(row.get("startedAt"), str)]
    finishes = [row.get("finishedAt") for row in attempts if isinstance(row.get("finishedAt"), str)]
    if not starts or not finishes:
        return None
    try:
        first = min(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in starts)
        last = max(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in finishes)
    except ValueError:
        return None
    return max(0, int((last - first).total_seconds() * 1000))


def _duration_ms(started: Any, finished: Any) -> int | None:
    if not isinstance(started, str) or not isinstance(finished, str):
        return None
    from datetime import datetime
    try:
        return max(0, int((datetime.fromisoformat(finished.replace("Z", "+00:00"))
                           - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds() * 1000))
    except ValueError:
        return None


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    import json
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                           if isinstance(value, (dict, list)) else value for key, value in row.items()}
                          for row in rows])


def _generation_duration(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Runtime-measured generation time of the attempts, without online assessment.

    One attempt gives its `measured` value; several give a `derived` sum. Any attempt without a
    measured duration makes the total unavailable.
    """
    values = []
    for attempt in attempts:
        result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
        timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
        value = timing.get("durationMs")
        values.append(value if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
    if not values or any(value is None for value in values):
        return {"generationDurationMs": None, "generationDurationProvenance": "unavailable"}
    return {"generationDurationMs": sum(values),
            "generationDurationProvenance": "measured" if len(values) == 1 else "derived"}


def _combine_assessor_costs(groups: list[Any]) -> dict[str, Any]:
    costs = [item for group in groups if isinstance(group, list)
             for item in group if isinstance(item, dict)]
    if not costs:
        return {
            "assessorDurationMs": None, "assessorDurationProvenance": "unavailable",
            "assessorTotalTokens": None, "assessorTokenProvenance": "unavailable",
            "knownAssessorTotalTokens": None,
        }
    durations = [item.get("durationMs") for item in costs]
    duration_provenances = [item.get("durationProvenance", "unavailable") for item in costs]
    duration_complete = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                            for value in durations)
    token_values = [item.get("totalTokens") for item in costs]
    known_tokens = [value for value in token_values if type(value) is int and value >= 0]
    tokens_complete = len(known_tokens) == len(costs)
    token_provenances = [item.get("tokenProvenance", "unavailable") for item in costs]
    token_provenance = (
        "unavailable" if not tokens_complete else
        token_provenances[0] if len(set(token_provenances)) == 1 else "derived"
    )
    return {
        "assessorDurationMs": sum(durations) if duration_complete else None,
        "assessorDurationProvenance": (
            duration_provenances[0] if duration_complete and len(set(duration_provenances)) == 1 else
            "derived" if duration_complete else "unavailable"
        ),
        "assessorTotalTokens": sum(known_tokens) if tokens_complete else None,
        "assessorTokenProvenance": token_provenance,
        "knownAssessorTotalTokens": sum(known_tokens) if known_tokens else None,
    }
