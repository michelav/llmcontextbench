"""Prefix-causal adaptive observations, windows, readings, and policy state."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
import hashlib
import math
import random
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from ctxbench.adaptive.signals import (
    BUILTIN_SIGNAL_UNITS, FAILURE_CATEGORIES, SignalValue, is_binary_scale, signal_from_dict,
)
from ctxbench.core.errors import PolicyContractError
from ctxbench.core.provenance import Provenance
from ctxbench.metrics.aggregate import mean, percentile


@dataclass(frozen=True, slots=True)
class WindowSpec:
    requests: int
    mode: str = "sliding"

    def __post_init__(self) -> None:
        if type(self.requests) is not int or self.requests < 1:
            raise ValueError("window.requests must be a positive integer")
        if self.mode not in {"sliding", "fixed"}:
            raise ValueError("window.mode must be 'sliding' or 'fixed'")


@dataclass(frozen=True, slots=True)
class CandidateState:
    candidate_id: str
    observation_count: int
    selections: int
    last_status: str | None


class SystemState(Protocol):
    decision_index: int
    completed_requests: int
    default_window: WindowSpec
    memo: Mapping[str, Any] | None

    def window(self, signal: str, statistic: str, *, scope: str = "system",
               window: WindowSpec | Mapping[str, Any] | None = None,
               capacity: float | None = None) -> "Reading": ...
    def candidate(self, candidate_id: str) -> CandidateState: ...
    def rng(self) -> random.Random: ...


@dataclass(frozen=True, slots=True)
class Observation:
    sequence_index: int
    candidate_id: str
    status: str
    failure_category: str | None
    signals: Mapping[str, SignalValue]
    known_subtotals: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.sequence_index) is not int or self.sequence_index < 1:
            raise ValueError("observation sequence_index must be a positive integer")
        if not self.candidate_id or self.status not in {"success", "error"}:
            raise ValueError("observation requires a candidate and terminal execution status")
        if self.failure_category is not None and self.failure_category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown failure category {self.failure_category!r}")

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Observation":
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            raise ValueError("terminal adaptive request has no attempt")
        attempt = attempts[0]
        decision = attempt.get("decision") or {}
        raw = attempt.get("observation") or {}
        signals_raw = raw.get("signals") if isinstance(raw, Mapping) else {}
        signals: dict[str, SignalValue] = {}
        if isinstance(signals_raw, Mapping):
            for name, value in signals_raw.items():
                default_unit = BUILTIN_SIGNAL_UNITS.get(str(name), "unit")
                signals[str(name)] = signal_from_dict(value, default_unit=default_unit)
        return cls(
            sequence_index=int(record["sequenceIndex"]),
            candidate_id=str(decision["candidateId"]), status=str(raw.get("status", "error")),
            failure_category=raw.get("failureCategory"), signals=signals,
            known_subtotals=_saved_subtotals(raw.get("knownSubtotals")),
        )


class ObservationLog:
    """Ordered terminal observations, rebuilt from the request ledger on resume."""

    __slots__ = ("_items",)

    def __init__(self, observations: Sequence[Observation] = ()) -> None:
        self._items: list[Observation] = []
        for observation in observations:
            self.append(observation)

    def append(self, observation: Observation) -> None:
        if self._items and observation.sequence_index <= self._items[-1].sequence_index:
            raise ValueError("observations must be appended in strictly increasing sequence order")
        self._items.append(observation)

    def prefix(self) -> tuple[Observation, ...]:
        return tuple(self._items)

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True, slots=True)
class Reading:
    signal: str
    statistic: str
    scope: str
    window: WindowSpec | None
    value: float | None
    provenance: Provenance
    sample_count: int
    missing_count: int
    known_subtotal: float | None
    capacity: float | None = None

    def __post_init__(self) -> None:
        if not self.signal or not self.statistic or not self.scope:
            raise ValueError("reading identity fields must be non-empty")
        if (self.value is None) != (self.provenance == Provenance.UNAVAILABLE):
            raise ValueError("unavailable readings require unavailable provenance")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("reading values must be finite")
        if self.capacity is not None and (not math.isfinite(self.capacity) or self.capacity <= 0):
            raise ValueError("reading capacity must be finite and positive")
        if self.sample_count < 0 or self.missing_count < 0:
            raise ValueError("reading sample counts must be nonnegative")

    @property
    def remaining(self) -> float | None:
        return self.capacity - self.value if self.capacity is not None and self.value is not None else None

    @property
    def utilisation(self) -> float | None:
        return self.value / self.capacity if self.capacity is not None and self.value is not None else None

    def to_dict(self) -> dict[str, Any]:
        """The audit entry of a decision record. `remaining` and `utilisation` follow from it."""
        return {
            "signal": self.signal, "statistic": self.statistic, "scope": self.scope,
            "window": _window_dict(self.window), "capacity": self.capacity, "value": self.value,
            "provenance": self.provenance.value, "sampleCount": self.sample_count,
            "missingCount": self.missing_count, "knownSubtotal": self.known_subtotal,
        }


class WindowSystemState:
    """Policy-readable view over terminal observations before the current request."""

    __slots__ = ("decision_index", "completed_requests", "default_window", "memo", "_log",
                 "_candidate_ids", "_declared_signals", "_audit", "_rng")

    def __init__(self, *, decision_index: int, observations: Sequence[Observation],
                 memo: Mapping[str, Any] | None, seed: int, decision_id: str,
                 default_window: WindowSpec, candidate_ids: Sequence[str],
                 declared_signals: Sequence[Mapping[str, Any]] = ()) -> None:
        self.decision_index = decision_index
        self._log = ObservationLog(observations)
        if self._log.prefix() and self._log.prefix()[-1].sequence_index >= decision_index:
            raise ValueError("system state cannot include the current or a later request")
        self.completed_requests = len(self._log)
        self.memo = MappingProxyType(dict(memo)) if memo is not None else None
        self.default_window = default_window
        self._candidate_ids = tuple(candidate_ids)
        # Keep the declaration rows: their value scale decides whether `rate` applies.
        self._declared_signals = tuple(row for row in declared_signals
                                       if isinstance(row, Mapping) and row.get("id"))
        self._audit: list[dict[str, Any]] = []
        # decision_id embeds the request ID: it seeds the generator and is not kept.
        derived_seed = int(hashlib.sha256(f"{seed}:{decision_id}".encode()).hexdigest()[:16], 16)
        self._rng = random.Random(derived_seed)

    def candidate(self, candidate_id: str) -> CandidateState:
        selected = [row for row in self._log.prefix() if row.candidate_id == candidate_id]
        return CandidateState(candidate_id, len(selected), len(selected), selected[-1].status if selected else None)

    def rng(self) -> random.Random:
        return self._rng

    def window(self, signal: str, statistic: str, *, scope: str = "system",
               window: WindowSpec | Mapping[str, Any] | None = None,
               capacity: float | None = None) -> Reading:
        try:
            validate_reading_request(signal, statistic, self._declared_signals)
        except ValueError as exc:
            raise PolicyContractError(str(exc)) from exc
        selected_window = _parse_window(window, self.default_window)
        if scope != "system":
            match = re.fullmatch(r"candidate:(.+)", scope)
            if match is None or match.group(1) not in self._candidate_ids:
                raise PolicyContractError(f"Invalid candidate scope {scope!r}")
        if capacity is not None and (
            isinstance(capacity, bool) or not isinstance(capacity, (int, float))
            or not math.isfinite(float(capacity)) or capacity <= 0
        ):
            raise PolicyContractError("capacity must be a finite positive number")
        rows = _select_window(self._log.prefix(), self.decision_index, selected_window)
        if scope.startswith("candidate:"):
            candidate_id = scope.split(":", 1)[1]
            rows = [row for row in rows if row.candidate_id == candidate_id]
        samples: list[float] = []
        missing_count = 0
        provenances: list[Provenance] = []
        known_values: list[float] = []
        for row in rows:
            value = _observation_signal(row, signal)
            if value is None or value.value is None:
                missing_count += 1
                if signal in row.known_subtotals:
                    known_values.append(row.known_subtotals[signal])
            else:
                samples.append(float(value.value))
                provenances.append(value.provenance)
        value, provenance, known_subtotal, sample_count = _aggregate(
            statistic, samples, missing_count, len(rows), known_values, provenances,
        )
        reading = Reading(signal, statistic, scope, selected_window, value, provenance,
                          sample_count, missing_count, known_subtotal, float(capacity) if capacity is not None else None)
        self._audit.append(reading.to_dict())
        return reading

    @property
    def reading_audit(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(deepcopy(item) for item in self._audit)


PrefixSystemState = WindowSystemState


def validate_reading_request(signal: Any, statistic: Any, declared_signals: Any = ()) -> None:
    """Check a (signal, statistic) pair. Used by `plan` and by every `window()` call.

    `declared_signals` is a collection of signal IDs or of declaration rows with an `id`. A row's
    `valueScale` gives a declared signal its unit: a binary scale is `bool`, so `rate` is checked
    by the same rule for built-in and declared signals. A bare ID has no known scale.
    """
    declared = {str(row.get("id")) if isinstance(row, Mapping) else str(row):
                row if isinstance(row, Mapping) else {} for row in declared_signals}
    unit = _signal_unit(signal)
    if unit is None and signal not in declared:
        raise ValueError(f"Unknown signal {signal!r}")
    if unit is None:
        scale = declared[signal].get("valueScale")
        unit = "bool" if is_binary_scale(scale) else (str(scale) if scale else None)
    if not isinstance(statistic, str) or (statistic not in _STATISTICS and _percentile_q(statistic) is None):
        raise ValueError(f"Unknown statistic {statistic!r}; percentiles are p<q> with 0 < q < 100")
    if statistic == "rate" and unit is not None and unit != "bool":
        raise ValueError(f"rate statistic requires a 0/1 signal; {signal!r} is measured in {unit}")


_STATISTICS = frozenset({"sum", "mean", "median", "min", "max", "last", "rate", "count"})


def _signal_unit(signal: Any) -> str | None:
    """Unit of a built-in signal, or None when the signal is not built in."""
    if not isinstance(signal, str):
        return None
    if signal.startswith("failed.") and signal.partition(".")[2] in FAILURE_CATEGORIES:
        return "bool"
    return BUILTIN_SIGNAL_UNITS.get(signal)


def _percentile_q(statistic: str) -> float | None:
    match = re.fullmatch(r"p(\d+(?:\.\d+)?)", statistic)
    if match is None:
        return None
    q = float(match.group(1))
    return q if 0 < q < 100 else None


def _saved_subtotals(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    for name, subtotal in value.items():
        if isinstance(subtotal, bool) or not isinstance(subtotal, (int, float)) or not math.isfinite(subtotal):
            raise ValueError(f"saved knownSubtotals[{name!r}] must be a finite number")
    return {str(name): float(subtotal) for name, subtotal in value.items()}


def _observation_signal(observation: Observation, signal: str) -> SignalValue | None:
    if signal.startswith("failed."):
        category = signal.partition(".")[2]
        return SignalValue(float(observation.failure_category == category), Provenance.DERIVED, "bool")
    if signal == "failed" and signal not in observation.signals:
        return SignalValue(float(observation.status != "success"), Provenance.DERIVED, "bool")
    return observation.signals.get(signal)


def _parse_window(value: WindowSpec | Mapping[str, Any] | None, default: WindowSpec) -> WindowSpec | None:
    if value is None:
        return default
    if isinstance(value, WindowSpec):
        return value
    if not isinstance(value, Mapping):
        raise PolicyContractError("window must be an object")
    if value.get("all") is True:
        if set(value) != {"all"}:
            raise PolicyContractError("all window cannot specify requests or mode")
        return None
    if set(value) - {"requests", "mode"}:
        raise PolicyContractError("window contains unsupported fields")
    try:
        return WindowSpec(value["requests"], value.get("mode", "sliding"))
    except (KeyError, TypeError, ValueError) as exc:
        raise PolicyContractError(f"Invalid window: {exc}") from exc


def _select_window(rows: Sequence[Observation], decision_index: int,
                   window: WindowSpec | None) -> list[Observation]:
    before = [row for row in rows if row.sequence_index < decision_index]
    if window is None:
        return before
    if window.mode == "sliding":
        return before[-window.requests:]
    block_start = ((decision_index - 1) // window.requests) * window.requests + 1
    return [row for row in before if row.sequence_index >= block_start]


def _aggregate(statistic: str, values: list[float], missing: int, observations: int,
               known_values: list[float], provenances: list[Provenance]):
    q = _percentile_q(statistic)
    percentile_stat = q is not None
    if statistic == "count":
        return float(observations), Provenance.DERIVED, None, observations
    if statistic == "sum":
        if missing:
            subtotal = sum(values) + sum(known_values)
            return None, Provenance.UNAVAILABLE, subtotal, len(values)
        return sum(values), _aggregate_provenance(provenances), None, len(values)
    if not values:
        return None, Provenance.UNAVAILABLE, None, 0
    if statistic == "rate" and any(value not in {0.0, 1.0} for value in values):
        raise PolicyContractError("rate statistic requires a 0/1 signal")
    if statistic == "mean" or statistic == "rate":
        result = mean(values)
    elif statistic == "median":
        ordered = sorted(values)
        middle = len(ordered) // 2
        result = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    elif statistic == "min":
        result = min(values)
    elif statistic == "max":
        result = max(values)
    elif statistic == "last":
        result = values[-1]
    elif percentile_stat:
        result = percentile(values, q)
    if result is None:
        return None, Provenance.UNAVAILABLE, None, len(values)
    return float(result), _aggregate_provenance(provenances), None, len(values)


def _aggregate_provenance(values: Sequence[Provenance]) -> Provenance:
    return Provenance.ESTIMATED if Provenance.ESTIMATED in values else Provenance.DERIVED


def _window_dict(window: WindowSpec | None) -> dict[str, Any]:
    return {"all": True} if window is None else {"requests": window.requests, "mode": window.mode}


__all__ = ["CandidateState", "Observation", "ObservationLog", "PrefixSystemState", "Reading",
           "SystemState", "WindowSpec", "WindowSystemState", "validate_reading_request"]
