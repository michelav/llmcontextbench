from __future__ import annotations

import random
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse
from ctxbench.ai.trace import TraceCollector


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    base_delay_ms: int = 1000
    max_delay_ms: int = 20000
    jitter: bool = True
    honor_retry_after: bool = True


@dataclass
class RateLimitConfig:
    enabled: bool = False
    tpm: int | None = None
    rpm: int | None = None
    max_concurrency: int | None = None
    min_interval_ms: int | None = None
    estimated_output_tokens: int = 512
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass
class ProviderErrorInfo:
    kind: str
    message: str
    retry_after_ms: int | None = None


def extract_rate_limit_config(request: AIRequest, params: dict[str, Any] | None = None) -> RateLimitConfig:
    merged = dict(params or {})
    merged.update(request.params)
    raw = merged.get("rate_limit", {})
    if not isinstance(raw, dict):
        raw = {}
    retry_policy = RetryPolicy(
        max_attempts=max(1, int(raw.get("max_attempts", 1))),
        base_delay_ms=max(0, int(raw.get("base_delay_ms", 1000))),
        max_delay_ms=max(0, int(raw.get("max_delay_ms", 20000))),
        jitter=bool(raw.get("jitter", True)),
        honor_retry_after=bool(raw.get("honor_retry_after", True)),
    )
    tpm_value = raw.get("tpm")
    rpm_value = raw.get("rpm")
    max_concurrency = raw.get("max_concurrency")
    min_interval_ms_value = raw.get("min_interval_ms")
    return RateLimitConfig(
        enabled=bool(raw),
        tpm=int(tpm_value) if isinstance(tpm_value, (int, float)) and int(tpm_value) > 0 else None,
        rpm=int(rpm_value) if isinstance(rpm_value, (int, float)) and int(rpm_value) > 0 else None,
        max_concurrency=int(max_concurrency)
        if isinstance(max_concurrency, (int, float)) and int(max_concurrency) > 0
        else None,
        min_interval_ms=int(min_interval_ms_value)
        if isinstance(min_interval_ms_value, (int, float)) and int(min_interval_ms_value) > 0
        else None,
        estimated_output_tokens=max(1, int(raw.get("estimated_output_tokens", 512))),
        retry_policy=retry_policy,
    )


class TokenRateLimiter:
    def __init__(
        self,
        tpm: int,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.capacity = max(1, tpm)
        self.refill_rate_per_sec = self.capacity / 60.0
        self._available = float(self.capacity)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._last_refill = self._clock()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        if elapsed > 0:
            self._available = min(self.capacity, self._available + (elapsed * self.refill_rate_per_sec))
            self._last_refill = now

    def acquire(
        self,
        tokens: int,
        *,
        on_wait: Callable[[int], None] | None = None,
    ) -> int:
        required = max(1, tokens)
        total_wait_ms = 0
        while True:
            wait_seconds = 0.0
            with self._lock:
                now = self._clock()
                self._refill(now)
                if self._available >= required:
                    self._available -= required
                    return total_wait_ms
                deficit = required - self._available
                wait_seconds = deficit / self.refill_rate_per_sec if self.refill_rate_per_sec > 0 else 0.0
            if wait_seconds > 0:
                wait_ms = max(0, int(wait_seconds * 1000))
                if on_wait is not None:
                    on_wait(wait_ms)
                self._sleeper(wait_seconds)
                total_wait_ms += wait_ms

    def observe(self, *, reserved_tokens: int, actual_tokens: int | None, error: Exception | None = None) -> None:
        if actual_tokens is None:
            return
        refund = reserved_tokens - max(0, actual_tokens)
        if refund <= 0:
            return
        with self._lock:
            self._available = min(self.capacity, self._available + refund)


class RequestRateLimiter:
    """Token bucket that counts requests (not tokens) against an RPM limit."""

    def __init__(
        self,
        rpm: int,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.capacity = max(1, rpm)
        self.refill_rate_per_sec = self.capacity / 60.0
        self._available = float(self.capacity)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._last_refill = self._clock()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_refill)
        if elapsed > 0:
            self._available = min(self.capacity, self._available + (elapsed * self.refill_rate_per_sec))
            self._last_refill = now

    def acquire(self, *, on_wait: Callable[[int], None] | None = None) -> int:
        total_wait_ms = 0
        while True:
            wait_seconds = 0.0
            with self._lock:
                now = self._clock()
                self._refill(now)
                if self._available >= 1:
                    self._available -= 1
                    return total_wait_ms
                wait_seconds = (1 - self._available) / self.refill_rate_per_sec if self.refill_rate_per_sec > 0 else 0.0
            if wait_seconds > 0:
                wait_ms = max(0, int(wait_seconds * 1000))
                if on_wait is not None:
                    on_wait(wait_ms)
                self._sleeper(wait_seconds)
                total_wait_ms += wait_ms


class ConcurrencyLimiter:
    def __init__(self, max_in_flight: int) -> None:
        self.max_in_flight = max(1, max_in_flight)
        self._semaphore = threading.Semaphore(self.max_in_flight)

    @contextmanager
    def slot(self) -> Any:
        self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()


class ModelRateController:
    def __init__(
        self,
        *,
        rate_limiter: TokenRateLimiter | None = None,
        request_limiter: RequestRateLimiter | None = None,
        concurrency_limiter: ConcurrencyLimiter | None = None,
        min_interval_ms: int | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter
        self.request_limiter = request_limiter
        self.concurrency_limiter = concurrency_limiter
        self.min_interval_ms = min_interval_ms
        self._last_call_time: float = 0.0
        self._interval_lock = threading.Lock()


class RateLimitCapacityError(RuntimeError):
    pass


class RateControlRegistry:
    def __init__(self) -> None:
        self._controllers: dict[tuple[str, str], ModelRateController] = {}
        self._lock = threading.Lock()

    def get_controller(self, provider_name: str, model_name: str, config: RateLimitConfig) -> ModelRateController:
        key = (provider_name, model_name)
        with self._lock:
            controller = self._controllers.get(key)
            if controller is None:
                controller = ModelRateController(
                    rate_limiter=TokenRateLimiter(config.tpm) if config.tpm else None,
                    request_limiter=RequestRateLimiter(config.rpm) if config.rpm else None,
                    concurrency_limiter=ConcurrencyLimiter(config.max_concurrency) if config.max_concurrency else None,
                    min_interval_ms=config.min_interval_ms,
                )
                self._controllers[key] = controller
            return controller


def classify_provider_error(provider_name: str, exc: Exception) -> ProviderErrorInfo:
    message = str(exc)
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    retry_after = _extract_retry_after_ms(exc)
    lowered = message.lower()
    if status_code == 429 or "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
        return ProviderErrorInfo(kind="rate_limit", message=message, retry_after_ms=retry_after)
    if isinstance(exc, TimeoutError):
        return ProviderErrorInfo(kind="transient", message=message, retry_after_ms=retry_after)
    if any(token in lowered for token in ("temporar", "timeout", "timed out", "connection reset", "connection aborted")):
        return ProviderErrorInfo(kind="transient", message=message, retry_after_ms=retry_after)
    if "taskgroup" in lowered or "sub-exception" in lowered:
        return ProviderErrorInfo(kind="transient", message=message, retry_after_ms=retry_after)
    return ProviderErrorInfo(kind="fatal", message=message, retry_after_ms=retry_after)


def _extract_retry_after_ms(exc: Exception) -> int | None:
    value = getattr(exc, "retry_after", None) or getattr(exc, "retry_after_seconds", None)
    if isinstance(value, (int, float)):
        return max(0, int(float(value) * 1000))
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        header_value = headers.get("retry-after") or headers.get("Retry-After")
        if isinstance(header_value, str):
            try:
                return max(0, int(float(header_value) * 1000))
            except ValueError:
                return None
    return None


def estimate_tokens(model_input: ModelInput, request: AIRequest, config: RateLimitConfig) -> tuple[int, int, int]:
    # Estimate from the actual payload sent to the model wrapper. For inline
    # requests, the prompt already contains the question and context, so adding
    # request.question/request.context again would double-count large inputs.
    text_parts = [
        model_input.system_instruction,
        model_input.prompt,
    ]
    serialized_tools = sum(len(str(tool.model_dump(mode="json"))) for tool in model_input.tools)
    serialized_tool_results = sum(len(str(result.model_dump(mode="json"))) for result in model_input.tool_results)
    serialized_tool_calls = sum(len(str(call.model_dump(mode="json"))) for call in model_input.previous_tool_calls)
    continuation_size = len(str(model_input.continuation_state))
    total_chars = sum(len(part) for part in text_parts) + serialized_tools + serialized_tool_results + serialized_tool_calls + continuation_size
    estimated_input = max(1, total_chars // 4)
    params = dict(request.params)
    estimated_output = int(
        params.get("max_output_tokens")
        or params.get("max_tokens")
        or config.estimated_output_tokens
    )
    estimated_output = max(1, estimated_output)
    return estimated_input, estimated_output, estimated_input + estimated_output


class RateLimitedModelAdapter(ModelAdapter):
    def __init__(
        self,
        delegate: ModelAdapter,
        registry: RateControlRegistry,
        *,
        provider_name: str,
        model_name: str,
        event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
    ) -> None:
        super().__init__(params=dict(delegate.params))
        self.delegate = delegate
        self.registry = registry
        self.provider_name = provider_name
        self.model_name = model_name
        self.event_logger = event_logger

    def generate(
        self,
        model_input: ModelInput,
        request: AIRequest,
        trace: TraceCollector | None = None,
    ) -> ModelResponse:
        config = extract_rate_limit_config(request, self.delegate.params)
        if not config.enabled:
            return self.delegate.generate(model_input, request, trace=trace)
        controller = self.registry.get_controller(self.provider_name, self.model_name, config)
        estimated_input, estimated_output, reserved_tokens = estimate_tokens(model_input, request, config)
        if trace is not None:
            trace.record_rate_limit_reservation(
                provider_name=self.provider_name,
                model_name=self.model_name,
                estimated_input_tokens=estimated_input,
                estimated_output_tokens=estimated_output,
                reserved_tokens=reserved_tokens,
            )
        request_fields = self._request_fields(request)
        if controller.rate_limiter is not None:
            if reserved_tokens > controller.rate_limiter.capacity:
                message = (
                    "Single request exceeds configured TPM budget: "
                    f"provider={self.provider_name} model={self.model_name} "
                    f"reserved_tokens={reserved_tokens} tpm={controller.rate_limiter.capacity} "
                    f"phase={request_fields['phase']} strategy={request.strategy_name}"
                )
                if request_fields.get("taskId"):
                    message += f" task_id={request_fields['taskId']}"
                if request_fields.get("instanceId"):
                    message += f" instance_id={request_fields['instanceId']}"
                if request_fields.get("judgeRole"):
                    message += f" judge_role={request_fields['judgeRole']}"
                self._log_event(
                    "ERROR",
                    "rate_limit.capacity.exceeded",
                    "TPM budget lower than single request reservation",
                    {
                        "provider": self.provider_name,
                        "modelName": self.model_name,
                        "reservedTokens": reserved_tokens,
                        "tpm": controller.rate_limiter.capacity,
                        **request_fields,
                    },
                )
                raise RateLimitCapacityError(message)

            def on_wait(wait_ms: int) -> None:
                if trace is not None:
                    trace.record_rate_limit_wait(
                        provider_name=self.provider_name,
                        model_name=self.model_name,
                        wait_ms=wait_ms,
                        reason="tpm_budget",
                    )
                self._log_event(
                    "INFO",
                    "rate_limit.tpm.wait",
                    "Waiting for TPM budget",
                    {
                        "provider": self.provider_name,
                        "modelName": self.model_name,
                        "waitMs": wait_ms,
                        "reservedTokens": reserved_tokens,
                        **request_fields,
                    },
                )

            waited_ms = controller.rate_limiter.acquire(reserved_tokens, on_wait=on_wait)

        if controller.min_interval_ms is not None:
            with controller._interval_lock:
                gap_ms = controller.min_interval_ms - (time.monotonic() - controller._last_call_time) * 1000
            if gap_ms > 0:
                if trace is not None:
                    trace.record_rate_limit_wait(
                        provider_name=self.provider_name,
                        model_name=self.model_name,
                        wait_ms=int(gap_ms),
                        reason="min_interval",
                    )
                time.sleep(gap_ms / 1000.0)
            with controller._interval_lock:
                controller._last_call_time = time.monotonic()

        if controller.request_limiter is not None:
            def on_rpm_wait(wait_ms: int) -> None:
                if trace is not None:
                    trace.record_rate_limit_wait(
                        provider_name=self.provider_name,
                        model_name=self.model_name,
                        wait_ms=wait_ms,
                        reason="rpm_budget",
                    )
                self._log_event(
                    "INFO",
                    "rate_limit.rpm.wait",
                    "Waiting for RPM budget",
                    {
                        "provider": self.provider_name,
                        "modelName": self.model_name,
                        "waitMs": wait_ms,
                        **request_fields,
                    },
                )
            controller.request_limiter.acquire(on_wait=on_rpm_wait)

        retry_policy = config.retry_policy
        attempt = 0
        limiter = controller.concurrency_limiter.slot() if controller.concurrency_limiter is not None else _nullcontext()
        with limiter:
            while True:
                attempt += 1
                try:
                    response = self.delegate.generate(model_input, request, trace=trace)
                    actual_tokens = response.total_tokens
                    if actual_tokens is None and response.input_tokens is not None and response.output_tokens is not None:
                        actual_tokens = response.input_tokens + response.output_tokens
                    if controller.rate_limiter is not None:
                        controller.rate_limiter.observe(
                            reserved_tokens=reserved_tokens,
                            actual_tokens=actual_tokens,
                        )
                    if trace is not None:
                        trace.record_rate_limit_reconcile(
                            provider_name=self.provider_name,
                            model_name=self.model_name,
                            reserved_tokens=reserved_tokens,
                            actual_tokens=actual_tokens,
                        )
                    return response
                except Exception as exc:
                    if controller.rate_limiter is not None:
                        controller.rate_limiter.observe(
                            reserved_tokens=reserved_tokens,
                            actual_tokens=None,
                            error=exc,
                        )
                    error_info = classify_provider_error(self.provider_name, exc)
                    if error_info.kind == "fatal" or attempt >= retry_policy.max_attempts:
                        if trace is not None and error_info.kind != "fatal":
                            trace.record_retry_give_up(
                                provider_name=self.provider_name,
                                model_name=self.model_name,
                                attempt=attempt,
                                error_kind=error_info.kind,
                                error=error_info.message,
                            )
                        raise
                    if trace is not None:
                        trace.record_retry_attempt(
                            provider_name=self.provider_name,
                            model_name=self.model_name,
                            attempt=attempt,
                            error_kind=error_info.kind,
                            error=error_info.message,
                        )
                    self._log_event(
                        "WARN",
                        "model.retry.started",
                        "Retrying model call",
                        {
                            "provider": self.provider_name,
                            "modelName": self.model_name,
                            "attempt": attempt,
                            "errorKind": error_info.kind,
                            **request_fields,
                        },
                    )
                    sleep_ms = _retry_delay_ms(retry_policy, error_info.retry_after_ms, attempt)
                    if trace is not None:
                        trace.record_retry_sleep(
                            provider_name=self.provider_name,
                            model_name=self.model_name,
                            attempt=attempt,
                            sleep_ms=sleep_ms,
                        )
                    self._log_event(
                        "WARN",
                        "model.retry.sleeping",
                        "Sleeping before retry",
                        {
                            "provider": self.provider_name,
                            "modelName": self.model_name,
                            "attempt": attempt,
                            "sleepMs": sleep_ms,
                            **request_fields,
                        },
                    )
                    time.sleep(sleep_ms / 1000.0)

    def _log_event(self, level: str, event_name: str, message: str, fields: dict[str, object]) -> None:
        if self.event_logger is None:
            return
        self.event_logger(event_name, message, {**fields, "level": level})

    def _request_fields(self, request: AIRequest) -> dict[str, object]:
        fields: dict[str, object] = {
            "phase": request.metadata.get("phase", "EXECUTE"),
            "strategy": request.strategy_name,
        }
        for key in (
            "experimentId",
            "trialId",
            "taskId",
            "instanceId",
            "provider",
            "modelId",
            "modelName",
            "format",
            "repeatIndex",
            "validationType",
            "judgeId",
            "judgeModel",
            "judgeRole",
        ):
            value = request.metadata.get(key)
            if value is not None:
                fields[key] = value
        if "instanceId" not in fields and request.metadata.get("instance_id") is not None:
            fields["instanceId"] = request.metadata.get("instance_id")
        if "judgeRole" not in fields and request.metadata.get("judge_role") is not None:
            fields["judgeRole"] = request.metadata.get("judge_role")
        return fields


def _retry_delay_ms(policy: RetryPolicy, retry_after_ms: int | None, attempt: int) -> int:
    if policy.honor_retry_after and retry_after_ms is not None:
        return max(0, retry_after_ms)
    exponent = max(0, attempt - 1)
    delay = policy.base_delay_ms * (2 ** exponent)
    delay = min(delay, policy.max_delay_ms)
    if policy.jitter and delay > 0:
        delay = random.randint(0, delay)
    return max(0, delay)


@contextmanager
def _nullcontext() -> Any:
    yield
