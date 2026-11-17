"""Pure goal evaluation over an adaptive run's durable request records."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ctxbench.adaptive.state import Observation, WindowSystemState, WindowSpec


def evaluate_goals(records: Sequence[Mapping[str, Any]], goals: Sequence[Mapping[str, Any]], *,
                   candidates: Sequence[str], signals: Sequence[Mapping[str, Any]],
                   default_window: WindowSpec) -> list[dict[str, Any]]:
    """Evaluate each declared goal at every terminal request, using only its causal prefix."""
    ordered = sorted((row for row in records if row.get("state") in {"delivered", "failed"}),
                     key=lambda row: int(row.get("sequenceIndex", 0)))
    observations: list[Observation] = []
    output: list[dict[str, Any]] = []
    for record in ordered:
        sequence = int(record["sequenceIndex"])
        observations.append(Observation.from_record(record))
        for goal in goals:
            window = goal.get("window") or default_window
            if isinstance(window, Mapping) and window.get("all") is True:
                # Definition normalization preserves mode on all-windows; it has no meaning here.
                window = {"all": True}
            state = WindowSystemState(
                decision_index=sequence, observations=observations, memo=None,
                seed=0, decision_id=f"goal:{goal['id']}:{sequence}",
                default_window=default_window, candidate_ids=candidates,
                declared_signals=signals, through_current=True,
            )
            reading = state.window(
                str(goal["signal"]), str(goal["statistic"]),
                scope=str(goal.get("scope", "system")), window=window,
            )
            upper = goal.get("upper")
            lower = goal.get("lower")
            if reading.value is None:
                status = "unknown"
                bound_type, bound = ("upper", upper) if upper is not None else ("lower", lower)
            elif upper is not None:
                bound_type, bound = "upper", upper
                status = "met" if reading.value <= float(upper) else "violated"
            else:
                bound_type, bound = "lower", lower
                status = "met" if reading.value >= float(lower) else "violated"
            output.append({
                "requestId": record["requestId"], "sequenceIndex": sequence,
                "goalId": goal["id"], "signal": goal["signal"],
                "statistic": goal["statistic"], "scope": goal.get("scope", "system"),
                "window": reading.to_dict()["window"], "status": status,
                "value": reading.value, "provenance": reading.provenance.value,
                "sampleCount": reading.sample_count, "missingCount": reading.missing_count,
                "boundType": bound_type, "bound": bound,
            })
    return output
