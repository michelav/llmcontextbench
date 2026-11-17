"""Best-static versus per-request oracle analysis for benchmark matrices."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ctxbench.analysis import run_root
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import read_jsonl


@dataclass(frozen=True, slots=True)
class HeadroomReport:
    signal: str
    objective: str
    best_static: float | None
    best_static_candidate: str | None
    oracle: float | None
    oracle_gain_over_best_static: float | None
    candidate_oracle_win_share: Mapping[str, float]
    coverage: Mapping[str, Mapping[str, int]]
    common_cells: int
    groups: tuple[Mapping[str, Any], ...] = ()
    provenance: str = "derived"
    interpretation: str = (
        "The oracle knows each request and is an upper bound on request-blind policies; "
        "a stationary matrix does not measure behaviour under disturbances."
    )


def headroom(run: str | Path, *, signal: str, objective: str = "min",
             by: str | None = None) -> HeadroomReport:
    """Compute headroom from successful benchmark trials and their recorded responses."""
    if objective not in {"min", "max"}:
        raise ValueError("objective must be 'min' or 'max'")
    root = run_root(run)
    manifest = load_json(root / "manifest.json")
    if not isinstance(manifest, Mapping) or manifest.get("workflowKind", "benchmark") != "benchmark":
        raise ValueError(f"headroom expects a benchmark run: {root}")
    trials = read_jsonl(root / "trials.jsonl")
    responses = read_jsonl(root / "responses.jsonl") if (root / "responses.jsonl").exists() else []
    response_by_id = {str(row.get("trialId")): row for row in responses if row.get("trialId")}
    cells: dict[str, dict[tuple[str, str], dict[str, list[float]]]] = {}
    all_cells: dict[str, set[tuple[str, str]]] = {}
    candidates = {_candidate_id(trial) for trial in trials}
    for trial in trials:
        cell = (str(trial.get("taskId", "")), str(trial.get("instanceId", "")))
        group = _group_value(trial, by) if by else "all"
        candidate = _candidate_id(trial)
        all_cells.setdefault(group, set()).add(cell)
        response = response_by_id.get(str(trial.get("trialId")), {})
        if response.get("status") != "success":
            continue
        value = _signal_value(response, signal)
        if value is None:
            continue
        cells.setdefault(group, {}).setdefault(cell, {}).setdefault(candidate, []).append(value)
    grouped_results = [_compute_group(group, cells.get(group, {}), all_cells[group], candidates, objective)
                       for group in sorted(all_cells)]
    if not grouped_results:
        grouped_results = [_compute_group("all", {}, set(), candidates, objective)]
    if by:
        pooled: dict[tuple[str, str], dict[str, list[float]]] = {}
        pooled_cells: set[tuple[str, str]] = set()
        for group, group_cells in all_cells.items():
            for cell in group_cells:
                composite = (group + "\x1f" + cell[0], cell[1])
                pooled_cells.add(composite)
                pooled[composite] = cells.get(group, {}).get(cell, {})
        overall = _compute_group("all", pooled, pooled_cells, candidates, objective)
    else:
        overall = grouped_results[0]
    return HeadroomReport(
        signal=signal, objective=objective,
        best_static=overall["bestStatic"], best_static_candidate=overall["bestStaticCandidate"],
        oracle=overall["oracle"], oracle_gain_over_best_static=overall["gain"],
        candidate_oracle_win_share=overall["winShare"], coverage=overall["coverage"],
        common_cells=overall["commonCells"],
        groups=tuple({"group": row["group"], "bestStatic": row["bestStatic"],
                      "bestStaticCandidate": row["bestStaticCandidate"], "oracle": row["oracle"],
                      "gain": row["gain"], "commonCells": row["commonCells"]}
                     for row in grouped_results) if by else (),
    )


def _compute_group(group: str, values: Mapping[tuple[str, str], Mapping[str, list[float]]],
                   all_cells: set[tuple[str, str]], candidates: set[str], objective: str) -> dict[str, Any]:
    candidates = sorted(candidates)
    cell_means = {cell: {candidate: sum(rows) / len(rows) for candidate, rows in row.items() if rows}
                  for cell, row in values.items()}
    complete = [cell for cell in all_cells if all(cell_means.get(cell, {}).get(candidate) is not None
                                                   for candidate in candidates)]
    totals = {candidate: sum(cell_means[cell][candidate] for cell in complete) for candidate in candidates}
    best_candidate = (min(totals, key=totals.get) if objective == "min" else max(totals, key=totals.get)) if totals and complete else None
    best_static = totals.get(best_candidate) if best_candidate else None
    oracle_total = 0.0
    wins = {candidate: 0 for candidate in candidates}
    for cell in complete:
        selected = (min(cell_means[cell], key=cell_means[cell].get) if objective == "min"
                    else max(cell_means[cell], key=cell_means[cell].get))
        oracle_total += cell_means[cell][selected]
        wins[selected] += 1
    gain = None if best_static is None or not best_static else (
        (best_static - oracle_total) if objective == "min" else (oracle_total - best_static)
    ) / abs(best_static)
    if best_static == 0 and oracle_total == 0:
        gain = 0.0
    coverage = {candidate: {"totalCells": len(all_cells),
                            "coveredCells": sum(candidate in cell_means.get(cell, {}) for cell in all_cells),
                            "missingCells": sum(candidate not in cell_means.get(cell, {}) for cell in all_cells)}
                for candidate in candidates}
    denominator = len(complete)
    return {"group": group, "bestStatic": best_static, "bestStaticCandidate": best_candidate,
            "oracle": oracle_total if denominator else None, "gain": gain,
            "winShare": {candidate: wins[candidate] / denominator if denominator else 0.0
                         for candidate in candidates}, "coverage": coverage,
            "commonCells": denominator}


def _candidate_id(trial: Mapping[str, Any]) -> str:
    return json.dumps([trial.get("modelId"), trial.get("configurationId")], ensure_ascii=False, separators=(",", ":"))


def _group_value(trial: Mapping[str, Any], by: str | None) -> str:
    if by is None:
        return "all"
    value = trial.get(by)
    if value is None:
        parameters = trial.get("parameters")
        if isinstance(parameters, Mapping):
            value = parameters.get(by)
    if value is None:
        tags = trial.get("taskTags")
        if isinstance(tags, list):
            value = next((tag.split("=", 1)[1] for tag in tags if isinstance(tag, str) and tag.startswith(by + "=")), None)
    return "<missing>" if value is None else str(value)


def _signal_value(response: Mapping[str, Any], signal: str) -> float | None:
    aliases = {
        "latency_ms": ("timing.durationMs", "metricsSummary.totalDurationMs"),
        "total_tokens": ("metricsSummary.totalTokens", "usage.totalTokens"),
        "input_tokens": ("usage.inputTokens",), "output_tokens": ("usage.outputTokens",),
        "cached_input_tokens": ("metricsSummary.cachedInputTokens",),
        "reasoning_tokens": ("metricsSummary.reasoningTokens",),
        "model_calls": ("metricsSummary.modelCalls",), "tool_calls": ("metricsSummary.toolCalls",),
    }
    candidates = aliases.get(signal, (signal,))
    for path in candidates:
        current: Any = response
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            return float(current)
    return None
