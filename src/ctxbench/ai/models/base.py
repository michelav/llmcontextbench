from __future__ import annotations

from typing import Any

from ctxbench._compat import BaseModel, Field
from ctxbench.ai.trace import TraceCollector


class ToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    content: Any
    tool_call_id: str | None = None
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIRequest(BaseModel):
    question: str
    context: str
    provider_name: str
    model_name: str
    strategy_name: str
    context_representation: str
    system_instruction: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def metadata_value(self, *keys: str) -> Any | None:
        for key in keys:
            value = self.metadata.get(key)
            if value is not None:
                return value
        return None

    def trial_id(self) -> str | None:
        value = self.metadata_value("trialId")
        return str(value) if value is not None and str(value) else None

    def task_id(self) -> str | None:
        value = self.metadata_value("taskId")
        return str(value) if value is not None and str(value) else None

    def experiment_id(self) -> str | None:
        value = self.metadata_value("experimentId")
        return str(value) if value is not None and str(value) else None


class ModelInput(BaseModel):
    system_instruction: str = ""
    prompt: str
    tools: list[ToolSpec] = Field(default_factory=list)
    previous_tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    continuation_state: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    text: str = ""
    requested_tool_calls: list[ToolCall] = Field(default_factory=list)
    raw_response: Any | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    continuation_state: dict[str, Any] = Field(default_factory=dict)


class AIResult(BaseModel):
    answer: str
    raw_response: Any | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ModelAdapter:
    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    def generate(
        self,
        model_input: ModelInput,
        request: AIRequest,
        trace: TraceCollector | None = None,
    ) -> ModelResponse:
        raise NotImplementedError
