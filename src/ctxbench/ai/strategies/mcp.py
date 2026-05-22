from __future__ import annotations

from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput
from ctxbench.ai.strategies.base import StrategyAdapter
from ctxbench.ai.trace import TraceCollector

DEFAULT_MCP_SYSTEM_INSTRUCTION = (
    "You are an assistant that handles tasks about a researcher.\n"
    "You have access to tools to gather information about the researcher's lattes curriculum.\n"
    "Your goal is to produce accurate, concise and information-grounded responses.\n"
    "Guidelines:\n"
    "- Use only the available information from the tools to address the task.\n"
    "- Inform if the provided information isn't enough to address the task.\n"
    "- Be concise and precise.\n"
    "- Do not make assumptions or use external knowledge.\n"
)


class MCPStrategy(StrategyAdapter):
    def execute(self, model: ModelAdapter, request: AIRequest, trace: TraceCollector) -> AIResult:
        lattes_id = _resolve_lattes_id(request)

        with trace.span("strategy.remote_mcp.execute", "strategy.remote_mcp.execute"):
            trace.record_steps(1)
            prompt = (
                f"# Task:\n{request.question}\n\n"
                f"# Researcher Lattes ID:\n{lattes_id}\n\n"
            )
            trace.metrics.promptChars = len(prompt)
            model_input = ModelInput(
                system_instruction=request.system_instruction or DEFAULT_MCP_SYSTEM_INSTRUCTION,
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
                metadata=model_response.metadata,
            )
            usage = {
                "inputTokens": model_response.input_tokens,
                "outputTokens": model_response.output_tokens,
                "totalTokens": model_response.total_tokens,
                "cachedInputTokens": model_response.cached_input_tokens,
                "cacheReadInputTokens": model_response.cache_read_input_tokens,
                "cacheCreationInputTokens": model_response.cache_creation_input_tokens,
            }
            usage = {key: value for key, value in usage.items() if value is not None}
            return AIResult(
                answer=model_response.text,
                raw_response=model_response.raw_response,
                metadata=dict(model_response.metadata),
                usage=usage,
            )


def _resolve_lattes_id(request: AIRequest) -> str:
    value = request.metadata.get("lattes_id") or request.metadata.get("instance_id")
    if not isinstance(value, str) or not value:
        raise ValueError("MCP strategy requires request.metadata['lattes_id'].")
    return value
