from __future__ import annotations

from typing import Callable

from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput
from ctxbench.ai.models.claude import ClaudeModel
from ctxbench.ai.models.gemini import GeminiModel
from ctxbench.ai.models.mock import MockModel
from ctxbench.ai.models.openai import OpenAIModel
from ctxbench.ai.failures import failure_category, provider_call, tag_failure
from ctxbench.ai.rate_control import RateControlRegistry, RateLimitedModelAdapter
from ctxbench.ai.runtime import ToolRuntime
from ctxbench.ai.strategies.local_function import LocalFunctionStrategy
from ctxbench.ai.strategies.local_mcp import LocalMCPStrategy
from ctxbench.ai.strategies.mcp import MCPStrategy
from ctxbench.ai.strategies.base import StrategyAdapter
from ctxbench.ai.strategies.inline import InlineStrategy
from ctxbench.ai.trace import TraceCollector


class Engine:
    def __init__(
        self,
        tool_runtime_factories: dict[str, Callable[[], ToolRuntime]] | None = None,
        event_logger: Callable[[str, str, dict[str, object]], None] | None = None,
    ) -> None:
        self._models: dict[str, ModelAdapter] = {
            "mock": MockModel(),
            "echo": MockModel(),
        }
        self._strategies: dict[str, StrategyAdapter] = {
            "inline": InlineStrategy(),
        }
        self._tool_runtime_factories = dict(tool_runtime_factories or {})
        self._rate_control_registry = RateControlRegistry()
        self._event_logger = event_logger

    def execute(self, request: AIRequest, *, model_interceptor: Callable | None = None) -> AIResult:
        trace = TraceCollector()
        trace.metrics.contextChars = len(request.context)
        trace.metrics.contextBytes = len(request.context.encode("utf-8"))
        trace.metrics.taskStatementChars = len(request.question)
        trace.metrics.taskStatementTokensEstimated = len(request.question.split()) or None
        owned_runtime: ToolRuntime | None = None
        try:
            with trace.span("engine.execute", "engine.execute"):
                model = self._resolve_model(request.provider_name, request.model_name, request.params)
                # Validate the resolved adapter, not a disturbance wrapper around it.
                self._validate_capabilities(model, request.strategy_name)
                if model_interceptor is not None:
                    model = model_interceptor(model)
                strategy, owned_runtime = self._resolve_strategy(request.strategy_name)
                result = strategy.execute(model, request, trace)
        except Exception as exc:
            trace.record_error(
                str(exc),
                metadata={
                    "provider_name": request.provider_name,
                    "model_name": request.model_name,
                    "strategy_name": request.strategy_name,
                    "exceptionModule": exc.__class__.__module__,
                    "exceptionType": exc.__class__.__name__,
                    "category": failure_category(exc),
                },
            )
            result = AIResult(answer="", error=str(exc))
        finally:
            if owned_runtime is not None:
                owned_runtime.close()
        result.trace = trace.to_trace().model_dump(mode="json")
        return result

    def execute_model_input(self, request: AIRequest, model_input: ModelInput, *,
                            model_interceptor: Callable | None = None) -> AIResult:
        trace = TraceCollector()
        trace.metrics.contextChars = len(request.context)
        trace.metrics.contextBytes = len(request.context.encode("utf-8"))
        trace.metrics.taskStatementChars = len(request.question)
        trace.metrics.taskStatementTokensEstimated = len(request.question.split()) or None
        trace.metrics.promptChars = len(model_input.prompt)
        try:
            with trace.span("engine.execute_model_input", "engine.execute_model_input"):
                model = self._resolve_model(request.provider_name, request.model_name, request.params)
                # Validate the resolved adapter, not a disturbance wrapper around it.
                self._validate_capabilities(model, request.strategy_name)
                if model_interceptor is not None:
                    model = model_interceptor(model)
                with provider_call(request.provider_name, model):
                    model_response = model.generate(model_input, request, trace=trace)
                trace.record_model_call(
                    duration_ms=model_response.duration_ms,
                    input_tokens=model_response.input_tokens,
                    output_tokens=model_response.output_tokens,
                    total_tokens=model_response.total_tokens,
                    cached_input_tokens=model_response.cached_input_tokens,
                    cache_read_input_tokens=model_response.cache_read_input_tokens,
                    cache_creation_input_tokens=model_response.cache_creation_input_tokens,
                    reasoning_tokens=model_response.reasoning_tokens,
                    metadata=model_response.metadata,
                    raw_response=model_response.raw_response,
                    provider=model_response.metadata.get("provider"),
                )
                usage = trace.usage_summary()
                result = AIResult(
                    answer=model_response.text,
                    raw_response=model_response.raw_response,
                    metadata=dict(model_response.metadata),
                    usage=usage,
                )
        except Exception as exc:
            trace.record_error(
                str(exc),
                metadata={
                    "provider_name": request.provider_name,
                    "model_name": request.model_name,
                    "execution_mode": "direct-model-input",
                    "exceptionModule": exc.__class__.__module__,
                    "exceptionType": exc.__class__.__name__,
                    "category": failure_category(exc),
                },
            )
            result = AIResult(answer="", error=str(exc))
        result.trace = trace.to_trace().model_dump(mode="json")
        return result

    def _resolve_model(self, name: str, model_name: str, params: dict[str, object] | None = None) -> ModelAdapter:
        if name in self._models:
            resolved = self._models[name]
            return RateLimitedModelAdapter(
                resolved,
                self._rate_control_registry,
                provider_name=name,
                model_name=model_name,
                event_logger=self._event_logger,
            )
        normalized = name.strip().lower()
        if normalized in {"openai", "gpt"}:
            resolved = OpenAIModel(params=params)
            return RateLimitedModelAdapter(
                resolved,
                self._rate_control_registry,
                provider_name=name,
                model_name=model_name,
                event_logger=self._event_logger,
            )
        if normalized in {"google", "gemini"}:
            resolved = GeminiModel(params=params)
            return RateLimitedModelAdapter(
                resolved,
                self._rate_control_registry,
                provider_name=name,
                model_name=model_name,
                event_logger=self._event_logger,
            )
        if normalized in {"anthropic", "claude"}:
            resolved = ClaudeModel(params=params)
            return RateLimitedModelAdapter(
                resolved,
                self._rate_control_registry,
                provider_name=name,
                model_name=model_name,
                event_logger=self._event_logger,
            )
        raise ValueError(f"Unknown provider: {name}")

    @staticmethod
    def _validate_capabilities(model: ModelAdapter, strategy_name: str) -> None:
        if strategy_name in {"local_function", "local_mcp", "remote_mcp"} and not getattr(
            model, "supports_tool_calling", True
        ):
            error = ValueError(
                f"Provider {model.__class__.__name__} does not support tool calling required by {strategy_name}."
            )
            tag_failure(error, "capability_unavailable")
            raise error

    def _resolve_strategy(self, name: str) -> tuple[StrategyAdapter, ToolRuntime | None]:
        strategy = self._strategies.get(name)
        if strategy is not None:
            return strategy, None
        runtime_factory = self._tool_runtime_factories.get(name)
        if runtime_factory is None:
            raise ValueError(f"Unknown strategy: {name}")
        runtime = runtime_factory()
        client_strategies = {
            "local_function": LocalFunctionStrategy,
            "local_mcp": LocalMCPStrategy,
            "remote_mcp": MCPStrategy,
        }
        if name in client_strategies:
            return client_strategies[name](runtime), runtime
        runtime.close()
        raise ValueError(f"Unknown strategy: {name}")

    def close(self) -> None:
        return None

    def copy_with_tool_runtime_factories(self, tool_runtime_factories: dict[str, Callable[[], ToolRuntime]]) -> "Engine":
        engine = Engine(tool_runtime_factories=tool_runtime_factories)
        engine._models = self._models
        engine._strategies = self._strategies
        engine._rate_control_registry = self._rate_control_registry
        engine._event_logger = self._event_logger
        return engine
