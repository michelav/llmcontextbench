from __future__ import annotations

from ctxbench.ai.failures import provider_call
from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput
from ctxbench.ai.strategies.base import StrategyAdapter
from ctxbench.ai.trace import TraceCollector

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are an assistant that solves benchmark tasks using only the provided context.\n"
    "Tasks may include question answering, retrieval, extraction, analysis, or code-related tasks.\n"
    "Your goal is to produce accurate, concise, and context-grounded responses.\n"
    "Guidelines:\n"
    "- Base your response strictly on the provided context.\n"
    "- If the provided context is insufficient, say so.\n"
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
            with provider_call(request.provider_name):
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
            return AIResult(
                answer=model_response.text,
                raw_response=model_response.raw_response,
                metadata=dict(model_response.metadata),
                usage=usage,
            )
