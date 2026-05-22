from __future__ import annotations

from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput
from ctxbench.ai.strategies.base import StrategyAdapter
from ctxbench.ai.trace import TraceCollector

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are an assistant that handles tasks about a researcher using his / her Lattes curriculum as context.\n"
    "Your goal is to produce  accurate, concise and context-grounded responses.\n"
    "Guidelines:\n"
    "- Base your respond strictly on the provided data.\n"
    "- Inform if the provided context isn't enough to address the task\n"
    "- Be concise and precise.\n"
    "- Do not make assumptions or use external knowledge.\n"
)


class InlineStrategy(StrategyAdapter):
    def execute(self, model: ModelAdapter, request: AIRequest, trace: TraceCollector) -> AIResult:
        with trace.span("strategy.inline.execute", "strategy.inline.execute"):
            trace.record_steps(1)
            prompt = (
                f"# Context:\n{request.context}\n\n"
                f"# Task:\n{request.question}\n"
            )
            trace.metrics.promptChars = len(prompt)
            model_input = ModelInput(
                system_instruction=request.system_instruction or DEFAULT_SYSTEM_INSTRUCTION,
                prompt=prompt,
            )
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
            )
            usage = {
                "inputTokens": model_response.input_tokens,
                "outputTokens": model_response.output_tokens,
                "totalTokens": model_response.total_tokens,
                "cachedInputTokens": model_response.cached_input_tokens,
                "cacheReadInputTokens": model_response.cache_read_input_tokens,
                "cacheCreationInputTokens": model_response.cache_creation_input_tokens,
                "reasoningTokens": model_response.reasoning_tokens,
            }
            usage = {key: value for key, value in usage.items() if value is not None}
            return AIResult(
                answer=model_response.text,
                raw_response=model_response.raw_response,
                metadata=dict(model_response.metadata),
                usage=usage,
            )
