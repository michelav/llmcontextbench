from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Any, Iterator

from ctxbench._compat import BaseModel, Field
from ctxbench.ai.models.usage import account_tokens


class TraceEvent(BaseModel):
    type: str
    name: str
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIMetrics(BaseModel):
    totalDurationMs: int | None = None
    strategyDurationMs: int | None = None
    modelDurationMs: int | None = None
    toolDurationMs: int | None = None
    benchmarkDurationMsEstimated: int | None = None
    loopControlDurationMsEstimated: int | None = None
    modelCalls: int = 0
    modelAttempts: int = 0
    failedModelAttempts: int = 0
    modelAttemptDurationMs: int | None = None
    toolCalls: int = 0
    mcpToolCalls: int = 0
    functionCalls: int = 0
    steps: int = 0
    retryCount: int = 0
    inputTokens: int | None = None
    outputTokens: int | None = None
    totalTokens: int | None = None
    knownTotalTokens: int | None = None
    totalTokensProvenance: str = "unavailable"
    usageCompleteness: str = "unavailable"
    totalTokensEstimated: int | None = None
    cachedInputTokens: int | None = None
    cacheReadInputTokens: int | None = None
    cacheCreationInputTokens: int | None = None
    reasoningTokens: int | None = None
    taskStatementTokensEstimated: int | None = None
    estimatedInputTokens: int | None = None
    estimatedOutputTokens: int | None = None
    reservedTokens: int | None = None
    contextChars: int | None = None
    contextBytes: int | None = None
    taskStatementChars: int | None = None
    promptChars: int | None = None
    rateLimitWaitMs: int | None = None
    retrySleepMs: int | None = None


class AITrace(BaseModel):
    events: list[TraceEvent] = Field(default_factory=list)
    metrics: AIMetrics = Field(default_factory=AIMetrics)


class TraceCollector:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.metrics = AIMetrics()
        self._known_total_tokens = 0
        self._unknown_usage_calls = 0
        self._total_token_provenance: set[str] = set()

    def record_model_attempt(self, *, duration_ms: int, failed: bool) -> None:
        self.metrics.modelAttempts += 1
        if failed:
            self.metrics.failedModelAttempts += 1
            self._unknown_usage_calls += 1
        self.metrics.modelAttemptDurationMs = self._sum_optional(
            self.metrics.modelAttemptDurationMs, duration_ms
        )
        self.events.append(TraceEvent(
            type="model.attempt", name="model.attempt", duration_ms=duration_ms,
            metadata={"failed": failed, "durationProvenance": "measured"},
        ))

    @contextmanager
    def span(
        self,
        event_type: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        started_at = perf_counter()
        try:
            yield
        finally:
            duration_ms = max(0, int((perf_counter() - started_at) * 1000))
            event = TraceEvent(
                type=event_type,
                name=name,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )
            self.events.append(event)
            self._apply_span_metrics(event)

    def record_model_call(
        self,
        *,
        duration_ms: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        cached_input_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        cache_creation_input_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        raw_response: Any | None = None,
        provider: str | None = None,
    ) -> None:
        self.events.append(
            TraceEvent(
                type="model.generate",
                name="model.generate",
                duration_ms=duration_ms,
                metadata=metadata or {},
            )
        )
        self.metrics.modelCalls += 1
        self.metrics.modelDurationMs = self._sum_optional(self.metrics.modelDurationMs, duration_ms)
        self.metrics.inputTokens = self._sum_optional(self.metrics.inputTokens, input_tokens)
        self.metrics.outputTokens = self._sum_optional(self.metrics.outputTokens, output_tokens)
        self.metrics.cachedInputTokens = self._sum_optional(self.metrics.cachedInputTokens, cached_input_tokens)
        self.metrics.cacheReadInputTokens = self._sum_optional(self.metrics.cacheReadInputTokens, cache_read_input_tokens)
        self.metrics.cacheCreationInputTokens = self._sum_optional(
            self.metrics.cacheCreationInputTokens,
            cache_creation_input_tokens,
        )
        self.metrics.reasoningTokens = self._sum_optional(self.metrics.reasoningTokens, reasoning_tokens)
        model_total = total_tokens
        if model_total is None and input_tokens is not None and output_tokens is not None:
            model_total = input_tokens + output_tokens
        known_total = model_total
        provenance = "unavailable"
        if known_total is None and (input_tokens is not None or output_tokens is not None):
            known_total = (input_tokens or 0) + (output_tokens or 0)
        if known_total is not None and provider:
            _, provenance, _ = account_tokens(
                provider, model_total, raw_response=raw_response,
                partial_total=known_total if model_total is None else None,
            )
        elif known_total is not None:
            provenance = "derived"
        if known_total is not None:
            self._known_total_tokens += known_total
            self._total_token_provenance.add(provenance)
        if known_total is None or provenance == "unavailable":
            self._unknown_usage_calls += 1

    def record_tool_call(self, *, name: str, arguments: dict[str, Any] | None = None) -> None:
        self.events.append(
            TraceEvent(
                type="mcp.tool_call",
                name="mcp.tool_call",
                metadata={"tool_name": name, "arguments": arguments or {}},
            )
        )
        self.metrics.toolCalls += 1
        self.metrics.mcpToolCalls += 1
        self.metrics.functionCalls += 1

    def record_tool_result(
        self,
        *,
        name: str,
        result: Any,
        is_error: bool = False,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event_metadata: dict[str, Any] = {
            "tool_name": name,
            "result": result,
            "is_error": is_error,
        }
        if metadata:
            event_metadata.update(metadata)
        self.events.append(
            TraceEvent(
                type="mcp.tool_result",
                name="mcp.tool_result",
                duration_ms=duration_ms,
                metadata=event_metadata,
            )
        )
        self.metrics.toolDurationMs = self._sum_optional(
            self.metrics.toolDurationMs,
            duration_ms,
        )

    def record_steps(self, steps: int) -> None:
        self.metrics.steps = max(self.metrics.steps, steps)

    def record_error(self, error: str, metadata: dict[str, Any] | None = None) -> None:
        event_metadata = {"error": error}
        if metadata:
            event_metadata.update(metadata)
        self.events.append(TraceEvent(type="error", name="error", metadata=event_metadata))

    def record_rate_limit_reservation(
        self,
        *,
        provider_name: str,
        model_name: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        reserved_tokens: int,
    ) -> None:
        self.metrics.estimatedInputTokens = estimated_input_tokens
        self.metrics.estimatedOutputTokens = estimated_output_tokens
        self.metrics.reservedTokens = reserved_tokens
        self.events.append(
            TraceEvent(
                type="rate_limit.reserve",
                name="rate_limit.reserve",
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "estimated_input_tokens": estimated_input_tokens,
                    "estimated_output_tokens": estimated_output_tokens,
                    "reserved_tokens": reserved_tokens,
                },
            )
        )

    def record_rate_limit_wait(
        self,
        *,
        provider_name: str,
        model_name: str,
        wait_ms: int,
        reason: str,
    ) -> None:
        self.metrics.rateLimitWaitMs = self._sum_optional(self.metrics.rateLimitWaitMs, wait_ms)
        self.events.append(
            TraceEvent(
                type="rate_limit.wait",
                name="rate_limit.wait",
                duration_ms=wait_ms,
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "reason": reason,
                },
            )
        )

    def record_rate_limit_reconcile(
        self,
        *,
        provider_name: str,
        model_name: str,
        reserved_tokens: int,
        actual_tokens: int | None,
    ) -> None:
        self.events.append(
            TraceEvent(
                type="rate_limit.reconcile",
                name="rate_limit.reconcile",
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "reserved_tokens": reserved_tokens,
                    "actual_tokens": actual_tokens,
                },
            )
        )

    def record_retry_attempt(
        self,
        *,
        provider_name: str,
        model_name: str,
        attempt: int,
        error_kind: str,
        error: str,
    ) -> None:
        self.metrics.retryCount += 1
        self.events.append(
            TraceEvent(
                type="retry.attempt",
                name="retry.attempt",
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "attempt": attempt,
                    "error_kind": error_kind,
                    "error": error,
                },
            )
        )

    def record_retry_sleep(
        self,
        *,
        provider_name: str,
        model_name: str,
        attempt: int,
        sleep_ms: int,
    ) -> None:
        self.metrics.retrySleepMs = self._sum_optional(self.metrics.retrySleepMs, sleep_ms)
        self.events.append(
            TraceEvent(
                type="retry.sleep",
                name="retry.sleep",
                duration_ms=sleep_ms,
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "attempt": attempt,
                },
            )
        )

    def record_retry_give_up(
        self,
        *,
        provider_name: str,
        model_name: str,
        attempt: int,
        error_kind: str,
        error: str,
    ) -> None:
        self.events.append(
            TraceEvent(
                type="retry.give_up",
                name="retry.give_up",
                metadata={
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "attempt": attempt,
                    "error_kind": error_kind,
                    "error": error,
                },
            )
        )

    def to_trace(self) -> AITrace:
        self._finalize_derived_metrics()
        return AITrace(events=list(self.events), metrics=self.metrics)

    def usage_summary(self) -> dict[str, Any]:
        self._finalize_derived_metrics()
        values = {
            "inputTokens": self.metrics.inputTokens,
            "outputTokens": self.metrics.outputTokens,
            "totalTokens": self.metrics.totalTokens,
            "knownTotalTokens": self.metrics.knownTotalTokens,
            "totalTokensProvenance": self.metrics.totalTokensProvenance,
            "usageCompleteness": self.metrics.usageCompleteness,
            "cachedInputTokens": self.metrics.cachedInputTokens,
            "cacheReadInputTokens": self.metrics.cacheReadInputTokens,
            "cacheCreationInputTokens": self.metrics.cacheCreationInputTokens,
            "reasoningTokens": self.metrics.reasoningTokens,
        }
        return {key: value for key, value in values.items() if value is not None}

    def _apply_span_metrics(self, event: TraceEvent) -> None:
        if event.name == "engine.execute":
            self.metrics.totalDurationMs = event.duration_ms
        elif event.name == "engine.execute_model_input":
            self.metrics.totalDurationMs = event.duration_ms
        elif event.name in {
            "strategy.inline.execute",
            "strategy.local_function.execute",
            "strategy.local_mcp.execute",
            "strategy.remote_mcp.execute",
        }:
            self.metrics.strategyDurationMs = event.duration_ms

    def _sum_optional(self, current: int | None, value: int | None) -> int | None:
        if value is None:
            return current
        if current is None:
            return value
        return current + value

    def _finalize_derived_metrics(self) -> None:
        self.metrics.knownTotalTokens = self._known_total_tokens or None
        if self.metrics.modelCalls and self._unknown_usage_calls == 0:
            self.metrics.totalTokens = self._known_total_tokens
            self.metrics.usageCompleteness = "complete"
            self.metrics.totalTokensProvenance = (
                next(iter(self._total_token_provenance))
                if len(self._total_token_provenance) == 1
                else "estimated" if "estimated" in self._total_token_provenance
                else "derived"
            )
        elif self._known_total_tokens:
            self.metrics.totalTokens = None
            self.metrics.usageCompleteness = "partial"
            self.metrics.totalTokensProvenance = "unavailable"
        else:
            self.metrics.totalTokens = None
            self.metrics.usageCompleteness = "unavailable"
            self.metrics.totalTokensProvenance = "unavailable"
        strategy = self.metrics.strategyDurationMs
        model = self.metrics.modelDurationMs or 0
        function = self.metrics.toolDurationMs or 0
        if strategy is None:
            self.metrics.benchmarkDurationMsEstimated = None
            self.metrics.loopControlDurationMsEstimated = None
        else:
            self.metrics.benchmarkDurationMsEstimated = max(0, strategy - model)
            self.metrics.loopControlDurationMsEstimated = max(0, strategy - model - function)
