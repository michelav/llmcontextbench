from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ctxbench.adaptive.policy import CandidateRef, Decision, SystemState
from ctxbench.adaptive.state import WindowSpec


class MinSignalPolicy:
    id = "min_signal"
    version = "1"

    def __init__(self, *, signal: str, statistic: str, window: Mapping[str, Any] | None = None,
                 objective: str = "min", min_samples: int = 1):
        if not isinstance(signal, str) or not signal or not isinstance(statistic, str) or not statistic:
            raise ValueError("signal and statistic must be non-empty strings")
        if objective not in {"min", "max"}:
            raise ValueError("objective must be 'min' or 'max'")
        if type(min_samples) is not int or min_samples < 1:
            raise ValueError("min_samples must be a positive integer")
        if _is_percentile(statistic) and min_samples < 2:
            # A percentile needs two values (section 6.4); one observation would never rank.
            raise ValueError("min_signal with a percentile statistic requires min_samples >= 2")
        if window is not None:
            if not isinstance(window, Mapping):
                raise ValueError("window must be an object")
            if window.get("all") is True:
                if set(window) != {"all"}:
                    raise ValueError("all window cannot specify requests or mode")
            else:
                if set(window) - {"requests", "mode"}:
                    raise ValueError("window contains unsupported fields")
                WindowSpec(window.get("requests"), window.get("mode", "sliding"))
        self.signal = signal
        self.statistic = statistic
        self.window = dict(window) if window is not None else None
        self.objective = objective
        self.min_samples = min_samples

    def decide(self, candidates: Sequence[CandidateRef], state: SystemState) -> Decision:
        if not candidates:
            raise ValueError("min_signal requires a non-empty candidate catalogue")
        # Exploration counts observations, not available values: a candidate whose signal is
        # never available (for example one that always fails without reporting usage) has been
        # tried and must not be selected again for that reason alone.
        counts: dict[str, int] = {}
        for candidate in candidates:
            scope = f"candidate:{candidate.candidate_id}"
            observed = state.window(self.signal, "count", scope=scope, window=self.window)
            counts[candidate.candidate_id] = int(observed.value or 0)
            if counts[candidate.candidate_id] < self.min_samples:
                return Decision(candidate.candidate_id,
                                f"{self.signal}.{self.statistic} exploration: "
                                f"{counts[candidate.candidate_id]}/{self.min_samples} observations")
        available = []
        for candidate in candidates:
            reading = state.window(self.signal, self.statistic,
                                   scope=f"candidate:{candidate.candidate_id}", window=self.window)
            if reading.value is not None:
                available.append((candidate, reading))
        if not available:
            # Nothing can be ranked. Spread the load: fewest observations, then declared order.
            selected = min(candidates, key=lambda item: counts[item.candidate_id])
            return Decision(selected.candidate_id,
                            f"{self.signal}.{self.statistic}=unavailable for every candidate; "
                            f"fewest observations ({counts[selected.candidate_id]})")
        chooser = min if self.objective == "min" else max
        selected, reading = chooser(available, key=lambda item: item[1].value)
        skipped = len(candidates) - len(available)
        suffix = f" unavailable_candidates={skipped}" if skipped else ""
        return Decision(selected.candidate_id,
                        f"{self.signal}.{self.statistic}={reading.value:g} "
                        f"objective={self.objective}{suffix}")

    def signal_readings(self) -> tuple[tuple[str, str], ...]:
        return ((self.signal, "count"), (self.signal, self.statistic))


def _is_percentile(statistic: str) -> bool:
    return statistic.startswith("p") and statistic[1:].replace(".", "", 1).isdigit()


__all__ = ["MinSignalPolicy"]
