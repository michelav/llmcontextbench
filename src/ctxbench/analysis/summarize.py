"""One-row-per-run summaries for adaptive experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ctxbench.adaptive.artifacts import load_adaptive_request_records
from ctxbench.util.fs import load_json


def summarize(runs: Iterable[str | Path], *, signals: Iterable[str]) -> list[dict[str, Any]]:
    """Summarize adaptive runs without invoking providers or changing their records."""
    signals = tuple(signals)
    rows: list[dict[str, Any]] = []
    for run in runs:
        root = _run_root(run)
        manifest = load_json(root / "manifest.json")
        if not isinstance(manifest, Mapping) or manifest.get("workflowKind") != "adaptive":
            raise ValueError(f"summarize expects adaptive runs: {root}")
        plan = load_json(root / "adaptive-plan.json")
        requests = plan.get("requests") if isinstance(plan, Mapping) else None
        if not isinstance(requests, list):
            raise ValueError(f"Adaptive plan has no request list: {root}")
        digest = hashlib.sha256(json.dumps(
            requests, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        records = sorted(load_adaptive_request_records(root).values(), key=lambda item: item.get("sequenceIndex", 0))
        goal_metrics = _goal_rows(root)
        policy = plan.get("policy") or {}
        candidates = plan.get("candidates") or []
        rate_limits = {
            str(item.get("modelId")): (item.get("modelParams") or {}).get("rate_limit", "none")
            for item in candidates if isinstance(item, Mapping)
        }
        output: dict[str, Any] = {
            "runPath": str(root), "workflowId": manifest.get("workflowId"),
            "policyId": policy.get("id"), "policyVersion": policy.get("version"),
            "seed": plan.get("seed"), "privileged": bool(manifest.get("privileged")),
            "mixedModels": bool(manifest.get("mixedModels")), "rateLimitByModel": rate_limits,
            "workloadDigest": digest, "requests": len(requests),
        }
        output.update({f"labels.{key}": value for key, value in (manifest.get("labels") or {}).items()})
        terminal = [record for record in records if record.get("state") in {"delivered", "failed"}]
        output["delivered"] = sum(record.get("state") == "delivered" for record in terminal)
        output["failed"] = sum(record.get("state") == "failed" for record in terminal)
        failures: dict[str, int] = {}
        for record in terminal:
            attempt = (record.get("attempts") or [{}])[0]
            observation = attempt.get("observation") or {}
            category = observation.get("failureCategory")
            if category:
                failures[str(category)] = failures.get(str(category), 0) + 1
        output.update({f"failures.{category}": count for category, count in failures.items()})
        for signal in signals:
            all_values = [_request_signal(record, signal) for record in terminal]
            delivered_values = [_request_signal(record, signal) for record in terminal
                                if record.get("state") == "delivered"]
            for service_view, values in (("allAttempts", all_values), ("deliveredRequests", delivered_values)):
                summary = _signal_summary(values)
                output.update({f"signals.{signal}.{service_view}.{key}": value
                               for key, value in summary.items()})
        for goal in (plan.get("goals") or []):
            goal_id = str(goal.get("id"))
            output[f"goals.{goal_id}.violations"] = sum(
                row.get("goalId") == goal_id and row.get("status") == "violated" for row in goal_metrics
            )
        rows.append(output)
    return rows


def _request_signal(record: Mapping[str, Any], signal: str) -> tuple[float | None, str, float | None]:
    attempts = record.get("attempts") if isinstance(record.get("attempts"), list) else []
    attempt = attempts[0] if attempts and isinstance(attempts[0], Mapping) else {}
    observation = attempt.get("observation") if isinstance(attempt.get("observation"), Mapping) else {}
    if signal == "failed":
        return float(record.get("state") == "failed"), "derived", None
    if signal.startswith("failed."):
        return float(observation.get("failureCategory") == signal.partition(".")[2]), "derived", None
    signals = observation.get("signals") if isinstance(observation.get("signals"), Mapping) else {}
    value = signals.get(signal) if isinstance(signals.get(signal), Mapping) else {}
    known = observation.get("knownSubtotals")
    known = known.get(signal) if isinstance(known, Mapping) else None
    return value.get("value"), str(value.get("provenance", "unavailable")), known


def _signal_summary(values: list[tuple[Any, str, Any]]) -> dict[str, Any]:
    available = [float(value) for value, _, _ in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    missing = len(values) - len(available)
    known_subtotal = sum(float(value) for value in available)
    known_subtotal += sum(float(subtotal) for value, _, subtotal in values
                          if value is None and isinstance(subtotal, (int, float)) and not isinstance(subtotal, bool))
    all_known = bool(values) and missing == 0
    provenances = {provenance for value, provenance, _ in values if value is not None}
    provenance = "unavailable" if not available else ("estimated" if "estimated" in provenances else "derived")
    return {
        "sum": known_subtotal if all_known else (0 if not values else None),
        "sumProvenance": provenance if all_known else ("derived" if not values else "unavailable"),
        "knownSubtotal": known_subtotal if missing else None,
        "mean": sum(available) / len(available) if available else None,
        "meanProvenance": provenance, "sampleCount": len(available), "missingCount": missing,
    }


def _goal_rows(root: Path) -> list[dict[str, Any]]:
    from ctxbench.metrics.adaptive import build_adaptive_goal_metrics
    return build_adaptive_goal_metrics(root)


def _run_root(run: Any) -> Path:
    value = getattr(run, "root", run)
    return Path(value).expanduser().resolve()
