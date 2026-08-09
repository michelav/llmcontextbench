from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ctxbench.benchmark.selectors import RunSelector, matches_run_result
from ctxbench.util.jsonl import read_jsonl
from ctxbench.util.logging import PhaseLogger


_SUPPORTED_FORMATS = ("csv",)

# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _trial_id(row: dict[str, Any]) -> str:
    return str(row.get("trialId", ""))


def _ans(row: dict[str, Any], key: str, default: Any = None) -> Any:
    return row.get(key, default)


def _metrics(row: dict[str, Any], key: str) -> Any:
    return (row.get("metricsSummary") or {}).get(key)


def _usage(row: dict[str, Any], key: str) -> Any:
    return (row.get("usage") or {}).get(key)


def _params(row: dict[str, Any], key: str) -> Any:
    return (row.get("parameters") or {}).get(key)


def _first_vote(votes: list[dict[str, Any]]) -> dict[str, Any]:
    for v in votes:
        if isinstance(v, dict) and not v.get("error"):
            return v
    return votes[0] if votes and isinstance(votes[0], dict) else {}


def _merge_row(
    ans: dict[str, Any],
    ev: dict[str, Any] | None,
    votes: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    ev = ev or {}
    votes = votes or []
    vote = _first_vote(votes)
    criterias = vote.get("criterias") or {}
    completeness_crit = criterias.get("completeness") or {}
    correctness_crit = criterias.get("correctness") or {}
    outcome = ev.get("outcome")
    outcome = outcome if isinstance(outcome, dict) else {}
    correctness_outcome = outcome.get("correctness") or {}
    completeness_outcome = outcome.get("completeness") or {}
    context_blocks = ev.get("contextBlocks")
    return {
        # ── from responses ──────────────────────────────────────────────────
        "experimentId": _ans(ans, "experimentId"),
        "trialId": _ans(ans, "trialId"),
        "dataset_id": (ans.get("dataset") or {}).get("id"),
        "dataset_version": (ans.get("dataset") or {}).get("version"),
        "instanceId": _ans(ans, "instanceId"),
        "format": _ans(ans, "format"),
        "taskId": _ans(ans, "taskId"),
        "modelId": _ans(ans, "modelId"),
        "modelName": _ans(ans, "model") or _ans(ans, "modelName"),
        "tags": ",".join(_ans(ans, "taskTags") or []),
        "index": _ans(ans, "repeatIndex"),
        "strategy": _ans(ans, "strategy"),
        "temperature": _params(ans, "temperature"),
        "inputTokens": _usage(ans, "inputTokens"),
        "outputTokens": _usage(ans, "outputTokens"),
        "totalTokens": _usage(ans, "totalTokens"),
        "cachedInputTokens": _usage(ans, "cachedInputTokens"),
        "cachedReadTokens": _usage(ans, "cacheReadInputTokens"),
        "status": _ans(ans, "status"),
        "modelCalls": _metrics(ans, "modelCalls"),
        "toolCalls": _metrics(ans, "toolCalls"),
        "mcpToolCalls": _metrics(ans, "mcpToolCalls"),
        "response": _ans(ans, "response"),
        "errorMessage": _ans(ans, "errorMessage"),
        "modelDuration": _metrics(ans, "modelDurationMs"),
        "reservedTokens": _metrics(ans, "reservedTokens"),
        "toolDurationMs": _metrics(ans, "toolDurationMs"),
        "totalDurationMs": _metrics(ans, "totalDurationMs"),
        # ── from evals ──────────────────────────────────────────────────────
        "completeness": completeness_outcome.get("rating"),
        "completeness_agreement": completeness_outcome.get("agreement"),
        "correctness": correctness_outcome.get("rating"),
        "correctness_agreement": correctness_outcome.get("agreement"),
        "evaluationDurationMs": ev.get("evaluationDurationMs"),
        "evaluationInputTokens": ev.get("evaluationInputTokens"),
        "evaluationOutputTokens": ev.get("evaluationOutputTokens"),
        "evaluationMethod": ev.get("evaluationMethod"),
        "judgeCount": ev.get("judgeCount"),
        "evaluationStatus": ev.get("status"),
        "contextBlocks": (
            ",".join(context_blocks) if isinstance(context_blocks, list) else context_blocks
        ),
        # ── from judge_votes (first non-error judge) ─────────────────────────
        "judge": (
            f"{vote.get('provider')}/{vote.get('model')}"
            if vote.get("provider") or vote.get("model")
            else None
        ),
        "judgeId": vote.get("judgeId"),
        "judgeModel": vote.get("model"),
        "completeness_justification": completeness_crit.get("justification"),
        "correctness_justification": correctness_crit.get("justification"),
    }


_CSV_FIELDS = [
    "experimentId", "trialId", "dataset_id", "dataset_version", "instanceId", "format", "taskId",
    "modelId", "modelName", "tags", "index", "strategy", "temperature",
    "inputTokens", "outputTokens", "totalTokens", "cachedInputTokens", "cachedReadTokens",
    "status", "modelCalls", "toolCalls", "mcpToolCalls",
    "response", "errorMessage", "modelDuration", "reservedTokens", "toolDurationMs", "totalDurationMs",
    "completeness", "completeness_agreement", "correctness", "correctness_agreement",
    "completeness_justification", "correctness_justification",
    "judge", "judgeId", "judgeModel",
    "evaluationDurationMs", "evaluationInputTokens", "evaluationOutputTokens",
    "evaluationMethod", "judgeCount", "evaluationStatus", "contextBlocks",
]


# ---------------------------------------------------------------------------
# --by filter parsing
# ---------------------------------------------------------------------------

_BY_KEY_MAP = {
    "model": "model",
    "strategy": "strategy",
    "format": "format",
    "instance": "instance",
}


def _apply_by_filters(
    rows: list[dict[str, Any]],
    by: list[str],
) -> list[dict[str, Any]]:
    if not by:
        return rows
    filters: dict[str, set[str]] = {}
    for token in by:
        if "=" not in token:
            raise ValueError(
                f"Invalid --by value '{token}'. Expected format: key=value "
                f"(valid keys: {', '.join(_BY_KEY_MAP)})"
            )
        key, _, value = token.partition("=")
        key = key.strip().lower()
        if key not in _BY_KEY_MAP:
            raise ValueError(
                f"Unknown --by key '{key}'. Valid keys: {', '.join(_BY_KEY_MAP)}"
            )
        filters.setdefault(key, set()).add(value.strip())

    result = []
    for row in rows:
        if "model" in filters:
            model_id = row.get("modelId") or ""
            model_name = row.get("model") or row.get("modelName") or ""
            if not (filters["model"] & {model_id, model_name}):
                continue
        if "strategy" in filters and row.get("strategy") not in filters["strategy"]:
            continue
        if "format" in filters and row.get("format") not in filters["format"]:
            continue
        if "instance" in filters and row.get("instanceId") not in filters["instance"]:
            continue
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [dict(item) for item in read_jsonl(path)]


def _build_eval_index(evals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for ev in evals:
        trial_id = _trial_id(ev)
        if trial_id:
            index[trial_id] = ev
    return index


def _build_votes_index(votes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for v in votes:
        trial_id = _trial_id(v)
        if trial_id:
            index.setdefault(trial_id, []).append(v)
    return index


# ---------------------------------------------------------------------------
# Detail view (--id)
# ---------------------------------------------------------------------------

def _print_run_detail(
    run_id: str,
    responses: list[dict[str, Any]],
    evals_index: dict[str, dict[str, Any]],
    votes_index: dict[str, list[dict[str, Any]]],
) -> int:
    response = next((r for r in responses if _trial_id(r) == run_id), None)
    if response is None:
        print(f"Trial '{run_id}' not found in responses.")
        return 1

    ev = evals_index.get(run_id)
    votes = votes_index.get(run_id, [])
    merged = _merge_row(response, ev, votes)

    metadata = response.get("metadata") or {}
    parameters = response.get("parameters") or {}
    metrics = response.get("metricsSummary") or {}
    timing = response.get("timing") or {}

    detail: dict[str, Any] = {
        "trialId": merged["trialId"],
        "experimentId": merged["experimentId"],
        "taskId": merged["taskId"],
        "instanceId": merged["instanceId"],
        "model": {"id": merged["modelId"], "name": merged["modelName"]},
        "strategy": merged["strategy"],
        "format": merged["format"],
        "index": merged["index"],
        "tags": (response.get("taskTags") or []),
        "status": merged["status"],
        "errorMessage": merged["errorMessage"],
        "response": merged["response"],
        "timing": timing,
        "usage": response.get("usage") or {},
        "metrics": metrics,
        "parameters": parameters,
        "metadata": metadata,
        "evaluation": ev if ev is not None else None,
        "judgeVotes": votes if votes else None,
    }
    print(json.dumps(detail, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f) for f in _CSV_FIELDS})


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------

def export_command(
    evals: str | None = None,
    *,
    format: str = "csv",
    output: str | None = None,
    verbose: bool = False,
    selector: RunSelector | None = None,
    by: list[str] | None = None,
    run_id: str | None = None,
) -> int:
    if format not in _SUPPORTED_FORMATS:
        PhaseLogger().error(
            "EXPORT",
            "export.failed",
            f"Unsupported format '{format}'. Supported: {', '.join(_SUPPORTED_FORMATS)}",
            format=format,
        )
        return 1

    source = Path(evals).resolve() if evals else Path("evals.jsonl").resolve()
    source_root = source.parent
    logger = PhaseLogger(verbose=verbose)

    responses_path = source_root / "responses.jsonl"
    if not responses_path.exists():
        logger.error(
            "EXPORT",
            "export.failed",
            f"Responses file not found: {responses_path}. Run 'llmctxbench execute' first.",
            path=str(responses_path),
        )
        return 1

    responses = _load_jsonl(responses_path)

    evals_list = _load_jsonl(source) if source.exists() else []
    evals_index = _build_eval_index(evals_list)

    votes_path = source_root / "judge_votes.jsonl"
    votes_list = _load_jsonl(votes_path)
    votes_index = _build_votes_index(votes_list)

    logger.info(
        "EXPORT", "export.inputs.loaded", "Files loaded",
        responses=len(responses), evals=len(evals_list), votes=len(votes_list),
    )

    if run_id is not None:
        return _print_run_detail(run_id, responses, evals_index, votes_index)

    active_selector = selector or RunSelector()
    responses = [r for r in responses if matches_run_result(r, active_selector)]

    try:
        responses = _apply_by_filters(responses, by or [])
    except ValueError as exc:
        logger.error("EXPORT", "export.failed", str(exc))
        return 1

    run_id_key = _trial_id
    merged = [
        _merge_row(response, evals_index.get(run_id_key(response)), votes_index.get(run_id_key(response)))
        for response in responses
    ]

    if format == "csv":
        out_path = Path(output).resolve() if output else source_root / "results.csv"
        _write_csv(merged, out_path)
        logger.info("EXPORT", "export.completed", "Export completed", path=str(out_path), rows=len(merged), format=format)
        print(f"Exported {len(merged)} row(s) → {out_path}")

    return 0
