from __future__ import annotations

from time import perf_counter

from ctxbench.ai.models.base import AIRequest, AIResult, ModelAdapter, ModelInput, ToolResult
from ctxbench.ai.runtime import ToolRuntime
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

class LocalFunctionStrategy(StrategyAdapter):
    def __init__(self, runtime: ToolRuntime) -> None:
        self.runtime = runtime

    def execute(self, model: ModelAdapter, request: AIRequest, trace: TraceCollector) -> AIResult:
        max_steps = int(request.params.get("max_steps", 8))
        instance_id = _resolve_instance_id(request)
        tool_results: list[ToolResult] = []
        previous_tool_calls = []
        continuation_state: dict[str, object] = {}
        tool_call_log: list[dict[str, object]] = []
        raw_responses: list[object] = []
        server_metrics: list[dict[str, object]] = []

        with trace.span("strategy.local_function.execute", "strategy.local_function.execute"):
            tools = self.runtime.list_tools()
            dataset_instructions = request.metadata.get("dataset_instructions")
            instructions_block = (
                f"# Dataset Instructions\n{dataset_instructions}\n\n"
                if isinstance(dataset_instructions, str) and dataset_instructions.strip()
                else ""
            )
            if not instructions_block and isinstance(request.metadata.get("lattes_id"), str):
                instructions_block = f"Researcher Lattes ID: {request.metadata['lattes_id']}\n\n"
            prompt = (
                f"{instructions_block}"
                f"# Task:\n{request.question}\n\n"
                f"# Instance ID:\n{instance_id}\n\n"
            )
            trace.metrics.promptChars = len(prompt)

            for step in range(max_steps):
                model_input = ModelInput(
                    system_instruction=request.system_instruction or DEFAULT_OPERATION_SYSTEM_INSTRUCTION,
                    prompt=prompt,
                    tools=tools,
                    previous_tool_calls=previous_tool_calls,
                    tool_results=tool_results,
                    continuation_state=continuation_state,
                )
                model_response = model.generate(model_input, request, trace=trace)
                raw_responses.append(model_response.raw_response)
                continuation_state = dict(model_response.continuation_state)
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
                if not model_response.requested_tool_calls:
                    trace.record_steps(step + 1)
                    usage = {
                        "inputTokens": trace.metrics.inputTokens,
                        "outputTokens": trace.metrics.outputTokens,
                        "totalTokens": trace.metrics.totalTokens,
                        "cachedInputTokens": trace.metrics.cachedInputTokens,
                        "cacheReadInputTokens": trace.metrics.cacheReadInputTokens,
                        "cacheCreationInputTokens": trace.metrics.cacheCreationInputTokens,
                        "reasoningTokens": trace.metrics.reasoningTokens,
                    }
                    usage = {key: value for key, value in usage.items() if value is not None}
                    return AIResult(
                        answer=model_response.text,
                        raw_response=raw_responses[-1] if len(raw_responses) == 1 else raw_responses,
                        metadata={
                            "steps": step + 1,
                            "server_mcp": server_metrics,
                            **dict(model_response.metadata),
                        },
                        usage=usage,
                        tool_calls=tool_call_log,
                    )

                current_results: list[ToolResult] = []
                for call_index, tool_call in enumerate(model_response.requested_tool_calls, start=1):
                    tool_call_id = tool_call.id or f"step-{step + 1}-tool-{call_index}"
                    trace.record_tool_call(name=tool_call.name, arguments=tool_call.arguments)
                    tool_started_at = perf_counter()
                    tool_result = self.runtime.call_tool(tool_call.name, tool_call.arguments)
                    tool_duration_ms = max(0, int((perf_counter() - tool_started_at) * 1000))
                    server_event = tool_result.metadata.get("server_event")
                    if isinstance(server_event, dict):
                        server_metrics.append(dict(server_event))
                    normalized_result = tool_result.model_copy(update={"tool_call_id": tool_call_id})
                    current_results.append(normalized_result)
                    tool_call_log.append(
                        {
                            "id": tool_call_id,
                            "name": tool_call.name,
                            "arguments": dict(tool_call.arguments),
                            "result": normalized_result.content,
                            "isError": normalized_result.is_error,
                        }
                    )
                    trace.record_tool_result(
                        name=normalized_result.name,
                        result=normalized_result.content,
                        is_error=normalized_result.is_error,
                        duration_ms=tool_duration_ms,
                        metadata=normalized_result.metadata,
                    )
                previous_tool_calls = list(model_response.requested_tool_calls)
                tool_results = current_results

        error = f"Local function strategy exceeded max_steps={max_steps}."
        trace.record_steps(max_steps)
        trace.record_error(error, metadata={"strategy_name": request.strategy_name, "max_steps": max_steps})
        return AIResult(
            answer="",
            error=error,
            metadata={"max_steps": max_steps, "server_mcp": server_metrics},
            tool_calls=tool_call_log,
        )


def _resolve_instance_id(request: AIRequest) -> str:
    value = request.metadata.get("instance_id") or request.metadata.get("lattes_id")
    if not isinstance(value, str) or not value:
        raise ValueError("Local function strategy requires request.metadata['instance_id'] or 'lattes_id'.")
    return value
