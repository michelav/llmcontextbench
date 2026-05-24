from __future__ import annotations

from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput
from ctxbench.ai.strategies.base import StrategyAdapter
from ctxbench.ai.trace import TraceCollector

DEFAULT_OPERATION_SYSTEM_INSTRUCTION = (
    "You are an assistant that solves benchmark tasks using only the available operations.\n"
    "Tasks may include question answering, retrieval, extraction, analysis, or code-related tasks.\n"
    "Use the available functions or tools to gather the information needed to complete the task.\n"
    "Guidelines:\n"
    "- Use only information obtained from the available operations.\n"
    "- If the available information is insufficient, say so.\n"
    "- Be concise and precise.\n"
    "- Do not make assumptions or use external knowledge.\n"
)

class MCPStrategy(StrategyAdapter):
    def execute(self, model: ModelAdapter, request: AIRequest, trace: TraceCollector) -> AIResult:
        instance_id = _resolve_instance_id(request)
        dataset_instructions = request.metadata.get("dataset_instructions")
        instructions_block = (
            f"# Dataset Instructions\n{dataset_instructions}\n\n"
            if isinstance(dataset_instructions, str) and dataset_instructions.strip()
            else ""
        )

        with trace.span("strategy.remote_mcp.execute", "strategy.remote_mcp.execute"):
            trace.record_steps(1)
            prompt = (
                f"{instructions_block}"
                f"# Task:\n{request.question}\n\n"
                f"# Instance ID:\n{instance_id}\n\n"
            )
            trace.metrics.promptChars = len(prompt)
            model_input = ModelInput(
                system_instruction=request.system_instruction or DEFAULT_OPERATION_SYSTEM_INSTRUCTION,
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


def _resolve_instance_id(request: AIRequest) -> str:
    value = request.metadata.get("instance_id") or request.metadata.get("lattes_id")
    if not isinstance(value, str) or not value:
        raise ValueError("MCP strategy requires request.metadata['instance_id'] or 'lattes_id'.")
    return value
