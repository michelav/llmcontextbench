"""Built-in adaptive signal extraction and failure classification."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from ctxbench.core.provenance import Provenance


FAILURE_CATEGORIES = frozenset({
    "context_overflow", "rate_limited", "provider_error", "tool_error", "step_limit",
    "empty_response", "capability_unavailable", "unknown",
})


@dataclass(frozen=True, slots=True)
class SignalValue:
    value: float | None
    provenance: Provenance
    unit: str

    def __post_init__(self) -> None:
        if not self.unit:
            raise ValueError("signal unit must be non-empty")
        if (self.value is None) != (self.provenance == Provenance.UNAVAILABLE):
            raise ValueError("missing signal values require unavailable provenance")
        if self.value is not None and (isinstance(self.value, bool) or not isfinite(float(self.value))):
            raise ValueError("signal value must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance.value, "unit": self.unit}


BUILTIN_SIGNAL_UNITS = {
    "latency_ms": "ms", "total_tokens": "tokens", "input_tokens": "tokens",
    "output_tokens": "tokens", "cached_input_tokens": "tokens", "reasoning_tokens": "tokens",
    "model_calls": "count", "tool_calls": "count", "failed": "bool", "accepted": "bool",
}


def extract_signals(result: Mapping[str, Any], *, accepted: bool,
                    ) -> tuple[dict[str, SignalValue], dict[str, float], str | None]:
    """Extract named execution signals without treating unavailable usage as zero.

    Returns the signal map, the known partial subtotals of signals whose value is unavailable
    (kept apart: a subtotal is not a signal value), and the failure category.
    """
    metrics = _mapping(result.get("metricsSummary"))
    usage = _mapping(result.get("usage"))
    status = str(result.get("status") or "error")
    failed = status != "success"
    category = classify_failure(result) if failed else None
    timing = _mapping(result.get("timing"))
    latency = timing.get("durationMs")
    if not _number(latency):
        latency = metrics.get("totalDurationMs")
    token_field_provenance = (Provenance.ESTIMATED
                              if metrics.get("totalTokensProvenance") == Provenance.ESTIMATED.value
                              else Provenance.REPORTED)
    signals: dict[str, SignalValue] = {
        "latency_ms": _signal(latency, "ms", Provenance.MEASURED),
        "total_tokens": _signal(
            metrics.get("totalTokens"), "tokens",
            _provenance(metrics.get("totalTokensProvenance")),
        ),
        "input_tokens": _signal(usage.get("inputTokens"), "tokens", token_field_provenance),
        "output_tokens": _signal(usage.get("outputTokens"), "tokens", token_field_provenance),
        "cached_input_tokens": _signal(metrics.get("cachedInputTokens"), "tokens", Provenance.REPORTED),
        "reasoning_tokens": _signal(metrics.get("reasoningTokens"), "tokens", Provenance.REPORTED),
        "model_calls": _signal(metrics.get("modelCalls"), "count", Provenance.MEASURED),
        "tool_calls": _signal(metrics.get("toolCalls"), "count", Provenance.MEASURED),
        "failed": SignalValue(float(failed), Provenance.DERIVED, "bool"),
        "accepted": SignalValue(float(bool(accepted)), Provenance.DERIVED, "bool"),
    }
    known_subtotals: dict[str, float] = {}
    if signals["total_tokens"].value is None:
        for partial in (metrics.get("knownTotalTokens"), metrics.get("totalTokens")):
            if _number(partial):
                known_subtotals["total_tokens"] = float(partial)
                break
    return signals, known_subtotals, category


def classify_failure(result: Mapping[str, Any]) -> str:
    """Map recorded failure metadata to the stable adaptive failure category set.

    The category is assigned by the layer that knows the cause and written to the trace error
    event. This function reads it; it does not infer a category from error text.
    """
    recorded = _normalize_category(result.get("failureCategory"))
    if recorded:
        return recorded
    trace = _mapping(result.get("trace"))
    events = trace.get("events")
    if isinstance(events, list):
        for event in reversed(events):
            event = _mapping(event)
            if event.get("type") != "error":
                continue
            metadata = _mapping(event.get("metadata"))
            if "capabilityunavailable" in str(metadata.get("exceptionType") or "").lower():
                return "capability_unavailable"
            explicit = _normalize_category(metadata.get("category"))
            if explicit:
                return explicit
    if "capabilityunavailable" in str(result.get("errorType") or "").lower():
        return "capability_unavailable"
    error_text = str(result.get("errorMessage") or "").strip()
    if not error_text and not str(result.get("response") or "").strip():
        return "empty_response"
    return "empty_response" if "empty" in error_text.lower() else "unknown"


def signal_from_dict(value: Any, *, default_unit: str = "count") -> SignalValue:
    if not isinstance(value, Mapping):
        return SignalValue(None, Provenance.UNAVAILABLE, default_unit)
    raw = value.get("value")
    provenance = _provenance(value.get("provenance"))
    if raw is not None and not _number(raw):
        raise ValueError("saved signal value must be numeric or null")
    return SignalValue(float(raw) if raw is not None else None, provenance,
                       str(value.get("unit") or default_unit))


def _signal(value: Any, unit: str, provenance: Provenance) -> SignalValue:
    if not _number(value) or provenance == Provenance.UNAVAILABLE:
        return SignalValue(None, Provenance.UNAVAILABLE, unit)
    return SignalValue(float(value), provenance, unit)


def _provenance(value: Any) -> Provenance:
    try:
        return Provenance(value)
    except (ValueError, TypeError):
        return Provenance.UNAVAILABLE


def _normalize_category(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    aliases = {"rate_limit": "rate_limited", "context_length": "context_overflow"}
    category = aliases.get(value, value)
    return category if category in FAILURE_CATEGORIES else "unknown"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


__all__ = ["BUILTIN_SIGNAL_UNITS", "FAILURE_CATEGORIES", "SignalValue", "classify_failure",
           "extract_signals", "signal_from_dict"]
