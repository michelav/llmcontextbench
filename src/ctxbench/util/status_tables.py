"""Shared helpers for the status report: response, evaluation and judge tallies."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import read_jsonl


def trial_id(row: dict[str, object]) -> str:
    return str(row.get("responseId") or row.get("requestId") or row.get("trialId", ""))


def last_status_map(path: Path) -> dict[str, str]:
    """Returns {trialId: status}, last entry per trialId wins (handles duplicates)."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for item in read_jsonl(path):
        identifier = trial_id(item)
        if identifier:
            result[identifier] = str(item.get("status", "unknown"))
    return result


def tally(status_map: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in status_map.values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def judge_status(value: dict[str, object]) -> str:
    status = value.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "error" if value.get("error") else "evaluated"


def load_judge_votes(path: Path) -> dict[tuple[str, str], dict[str, object]]:
    """Returns {(trialId, judgeId): vote}, last entry wins."""
    if not path.exists():
        return {}
    result: dict[tuple[str, str], dict[str, object]] = {}
    for item in read_jsonl(path):
        identifier = trial_id(item)
        judge_id = str(item.get("judgeId", ""))
        if identifier and judge_id:
            result[(identifier, judge_id)] = dict(item)
    return result


def _judge_identifier(config: dict[str, Any]) -> str:
    """Same identity rule as ``benchmark.evaluation.judge_identifier``, over the manifest dict."""
    params: dict[str, Any] = {}
    raw_params = config.get("params")
    if isinstance(raw_params, dict):
        params.update(raw_params)
    for key, value in config.items():
        if key not in {"provider", "model", "temperature", "params"}:
            params[key] = value
    for key in ("id", "judgeId", "judge_id", "name"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{str(config.get('provider', ''))}:{str(config.get('model', ''))}"


def configured_judge_ids(root: Path) -> list[str]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = load_json(manifest_path)
    except Exception:
        return []
    if not isinstance(manifest, dict):
        return []
    evaluation = manifest.get("evaluation", {})
    if not isinstance(evaluation, dict):
        return []
    judges = evaluation.get("judges", [])
    if not isinstance(judges, list):
        return []
    return [_judge_identifier(item) for item in judges if isinstance(item, dict)]


def judge_breakdown(root: Path, answer_total: int) -> list[tuple[str, int, int, int, int]]:
    votes = load_judge_votes(root / "judge_votes.jsonl")
    configured = configured_judge_ids(root)
    observed = sorted({judge_id for _, judge_id in votes.keys() if judge_id})
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for judge_id in configured + observed:
        if judge_id and judge_id not in seen:
            ordered_ids.append(judge_id)
            seen.add(judge_id)

    counts: dict[str, dict[str, int]] = {judge_id: {"evaluated": 0, "error": 0} for judge_id in ordered_ids}
    for (_, judge_id), vote in votes.items():
        status = judge_status(vote)
        counts.setdefault(judge_id, {"evaluated": 0, "error": 0})
        if status == "error":
            counts[judge_id]["error"] += 1
        else:
            counts[judge_id]["evaluated"] += 1

    rows: list[tuple[str, int, int, int, int]] = []
    for judge_id in ordered_ids:
        evaluated = counts.get(judge_id, {}).get("evaluated", 0)
        failed = counts.get(judge_id, {}).get("error", 0)
        pending = max(0, answer_total - evaluated - failed)
        rows.append((judge_id, answer_total, evaluated, failed, pending))
    return rows


def judge_breakdown_lines(root: Path, answer_total: int) -> list[str]:
    lines = ["", f"{'Judge':<24} {'Total':>8} {'Success':>8} {'Failed':>8} {'Pending':>8}", "─" * 64]
    for judge_id, total, success, failed, pending in judge_breakdown(root, answer_total):
        lines.append(f"{judge_id:<24} {total:>8} {success:>8} {failed:>8} {pending:>8}")
    return lines
