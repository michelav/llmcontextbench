from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ctxbench.adaptive.policy import CandidateRef, Decision, PolicyContractError, SystemState
from ctxbench.adaptive.state import WindowSpec


class WindowThresholdPolicy:
    id = "window_threshold"
    version = "1"

    def __init__(self, *, signal: str, statistic: str, tiers: Sequence[Mapping[str, Any]],
                 otherwise: str, when_unavailable: str, scope: str = "system",
                 window: Mapping[str, Any] | None = None, capacity: float | None = None,
                 min_samples: int = 1):
        if not isinstance(signal, str) or not signal or not isinstance(statistic, str) or not statistic:
            raise ValueError("signal and statistic must be non-empty strings")
        if not isinstance(tiers, Sequence) or isinstance(tiers, (str, bytes)) or not tiers:
            raise ValueError("tiers must be a non-empty list")
        parsed = []
        previous = -math.inf
        for tier in tiers:
            if not isinstance(tier, Mapping) or set(tier) != {"upTo", "select"}:
                raise ValueError("each tier must contain exactly upTo and select")
            up_to = tier["upTo"]
            if isinstance(up_to, bool) or not isinstance(up_to, (int, float)) or not math.isfinite(float(up_to)):
                raise ValueError("tier upTo values must be finite numbers")
            if float(up_to) <= previous:
                raise ValueError("tier upTo values must be strictly ascending")
            if not isinstance(tier["select"], str) or not tier["select"]:
                raise ValueError("tier select must be a candidate ID")
            previous = float(up_to)
            parsed.append((float(up_to), tier["select"]))
        if any(not isinstance(item, str) or not item for item in (otherwise, when_unavailable)):
            raise ValueError("otherwise and when_unavailable must be candidate IDs")
        if not isinstance(scope, str) or (scope != "system" and not scope.startswith("candidate:")):
            raise ValueError("scope must be 'system' or 'candidate:<candidateId>'")
        if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, (int, float))
                                     or not math.isfinite(float(capacity)) or capacity <= 0):
            raise ValueError("capacity must be a finite positive number")
        if capacity is not None and any(not 0 <= up_to <= 1 for up_to, _ in parsed):
            raise ValueError("tier upTo values must be fractions from 0 to 1 when capacity is set")
        if type(min_samples) is not int or min_samples < 1:
            raise ValueError("min_samples must be a positive integer")
        if window is not None:
            _validate_window(window)
        self.signal = signal
        self.statistic = statistic
        self.tiers = tuple(parsed)
        self.otherwise = otherwise
        self.when_unavailable = when_unavailable
        self.scope = scope
        self.window = dict(window) if window is not None else None
        self.capacity = float(capacity) if capacity is not None else None
        self.min_samples = min_samples

    def decide(self, candidates: Sequence[CandidateRef], state: SystemState) -> Decision:
        if set(self.candidate_targets()) - {item.candidate_id for item in candidates}:
            raise PolicyContractError("window_threshold references candidate(s) outside the catalogue")
        reading = state.window(self.signal, self.statistic, scope=self.scope,
                               window=self.window, capacity=self.capacity)
        unavailable = reading.value is None
        if not unavailable and self.statistic not in {"sum", "count"} and reading.sample_count < self.min_samples:
            unavailable = True
        if unavailable:
            return Decision(self.when_unavailable,
                            f"{self.signal}.{self.statistic}=unavailable min_samples={self.min_samples}")
        measure = reading.utilisation if self.capacity is not None else reading.value
        assert measure is not None
        for tier_index, (up_to, candidate_id) in enumerate(self.tiers, start=1):
            if measure <= up_to:
                return Decision(candidate_id, _reason(self, reading, measure, f"tier={tier_index}"))
        return Decision(self.otherwise, _reason(self, reading, measure, "tier=otherwise"))

    def signal_readings(self) -> tuple[tuple[str, str], ...]:
        return ((self.signal, self.statistic),)

    def candidate_targets(self) -> tuple[str, ...]:
        targets = [self.otherwise, self.when_unavailable]
        targets.extend(candidate_id for _, candidate_id in self.tiers)
        if self.scope.startswith("candidate:"):
            targets.append(self.scope.split(":", 1)[1])
        return tuple(targets)


def _reason(policy: WindowThresholdPolicy, reading, measure: float, tier: str) -> str:
    parts = [f"{policy.signal}.{policy.statistic}={reading.value:g}"]
    if policy.capacity is not None:
        parts.extend((f"capacity={policy.capacity:g}", f"utilisation={measure:g}"))
    parts.append(tier)
    return " ".join(parts)


def _validate_window(window: Mapping[str, Any]) -> None:
    if not isinstance(window, Mapping):
        raise ValueError("window must be an object")
    if window.get("all") is True:
        if set(window) != {"all"}:
            raise ValueError("all window cannot specify requests or mode")
    else:
        if set(window) - {"requests", "mode"}:
            raise ValueError("window contains unsupported fields")
        WindowSpec(window.get("requests"), window.get("mode", "sliding"))


__all__ = ["WindowThresholdPolicy"]
