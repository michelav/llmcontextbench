from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse, ToolCall


class ClaudeModel(ModelAdapter):
    supports_tool_calling = True
    def generate(self, model_input: ModelInput, request: AIRequest, trace: Any | None = None) -> ModelResponse:
        client = self._create_client()
        payload = self._build_payload(model_input, request)
        started_at = perf_counter()
        response = client.beta.messages.create(**payload)
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        input_tokens, output_tokens, total_tokens = self._extract_usage(response)
        cache_read_input_tokens, cache_creation_input_tokens = self._extract_cache_usage(response)
        reasoning_tokens = self._extract_reasoning_tokens(response)
        return ModelResponse(
            text=self._extract_text(response),
            requested_tool_calls=self._extract_tool_calls(response),
            raw_response=self._normalize_raw_response(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cache_read_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
            metadata={
                "provider": "anthropic",
                "model": request.model_name,
                **self._extract_native_mcp_metadata(response),
            },
            continuation_state=self._build_continuation_state(response),
        )

    def _create_client(self) -> Any:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Anthropic SDK is not installed.") from exc
        return Anthropic(api_key=self.params.get("api_key"))

    def _build_payload(self, model_input: ModelInput, request: AIRequest) -> dict[str, Any]:
        params = self._merged_params(request)
        payload: dict[str, Any] = {
            "model": request.model_name,
            "system": [
                {
                    "type": "text",
                    "text": model_input.system_instruction,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": self._build_messages(model_input, params),
            "max_tokens": params.get("max_tokens", 1024),
        }
        metadata = self._request_metadata(request)
        if metadata:
            payload["metadata"] = metadata
        if model_input.tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in model_input.tools
            ]
        if "temperature" in params:
            payload["temperature"] = params["temperature"]
        structured_output = params.get("structured_output")
        if isinstance(structured_output, dict):
            schema = structured_output.get("schema")
            if isinstance(schema, dict):
                payload["output_config"] = {
                    "format": {
                        "type": "json_schema",
                        "schema": schema,
                    }
                }
        return payload

    def _build_messages(self, model_input: ModelInput, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        prefix = (params or {}).get("prompt_cache_prefix")
        if prefix:
            user_content: str | list[dict[str, Any]] = [
                {"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": model_input.prompt},
            ]
        else:
            user_content = model_input.prompt
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]
        assistant_content = model_input.continuation_state.get("assistant_content")
        if isinstance(assistant_content, list) and assistant_content:
            messages.append({"role": "assistant", "content": assistant_content})
        elif model_input.previous_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "input": tool_call.arguments,
                        }
                        for tool_call in model_input.previous_tool_calls
                    ],
                }
            )
        if model_input.tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": json.dumps(result.content),
                            "is_error": result.is_error,
                        }
                        for result in model_input.tool_results
                    ],
                }
            )
        return messages

    def _extract_text(self, response: Any) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                block_type = getattr(block, "type", None)
                if block_type and block_type != "text":
                    continue
                value = getattr(block, "text", None)
                if isinstance(value, str):
                    parts.append(value)
            if parts:
                return "\n".join(parts).strip()
        return ""

    def _extract_tool_calls(self, response: Any) -> list[ToolCall]:
        content = getattr(response, "content", None)
        if not isinstance(content, list):
            return []
        tool_calls: list[ToolCall] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tool_calls.append(
                ToolCall(
                    id=getattr(block, "id", None),
                    name=str(getattr(block, "name", "")),
                    arguments=getattr(block, "input", {}) or {},
                )
            )
        return tool_calls

    def _extract_usage(self, response: Any) -> tuple[int | None, int | None, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None, None
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return input_tokens, output_tokens, total_tokens

    def _extract_reasoning_tokens(self, response: Any) -> int | None:
        usage = getattr(response, "usage", None)
        for field in ("thinking_input_tokens", "thinking_tokens", "reasoning_tokens"):
            value = getattr(usage, field, None)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    def _extract_cache_usage(self, response: Any) -> tuple[int | None, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None
        cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", None)
        cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", None)
        return cache_read_input_tokens, cache_creation_input_tokens

    def _normalize_raw_response(self, response: Any) -> Any:
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        if hasattr(response, "to_dict"):
            return response.to_dict()
        if isinstance(response, list):
            return [self._normalize_raw_response(item) for item in response]
        if isinstance(response, dict):
            return {key: self._normalize_raw_response(value) for key, value in response.items()}
        if hasattr(response, "__dict__"):
            return {
                key: self._normalize_raw_response(value)
                for key, value in vars(response).items()
                if not key.startswith("_")
            }
        return response

    def _build_continuation_state(self, response: Any) -> dict[str, Any]:
        content = getattr(response, "content", None)
        normalized = self._normalize_raw_response(content)
        if isinstance(normalized, list):
            return {"assistant_content": normalized}
        return {}

    def _merged_params(self, request: AIRequest) -> dict[str, Any]:
        params = dict(self.params)
        params.update(request.params)
        return params

    def _request_metadata(self, request: AIRequest) -> dict[str, str]:
        trial_id = request.trial_id()
        experiment_id = request.experiment_id()
        task_id = request.task_id()
        phase = request.metadata.get("phase")
        parts = []
        if trial_id is not None and str(trial_id):
            parts.append(f"trialId={trial_id}")
        if experiment_id is not None and str(experiment_id):
            parts.append(f"experimentId={experiment_id}")
        if task_id is not None and str(task_id):
            parts.append(f"taskId={task_id}")
        if phase is not None and str(phase):
            parts.append(f"phase={phase}")
        if not parts:
            return {}
        return {"user_id": ";".join(parts)}

    def _build_native_mcp_servers(self, request: AIRequest) -> list[dict[str, Any]]:
        if request.strategy_name == "mcp":
            raise ValueError("unknown strategy: mcp")
        if request.strategy_name != "remote_mcp":
            return []
        config = request.params.get("mcp_server")
        if not isinstance(config, dict):
            raise RuntimeError("Native MCP strategy requires params['mcp_server'] for Claude models.")
        server_url = config.get("server_url") or config.get("url")
        server_label = config.get("server_label") or config.get("label") or "ctxbench-lattes"
        if not isinstance(server_url, str) or not server_url:
            raise RuntimeError("Claude MCP config requires a non-empty 'server_url' or 'url'.")
        server: dict[str, Any] = {
            "type": "url",
            "url": server_url,
            "name": str(server_label),
        }
        server_description = config.get("server_description") or config.get("description")
        if isinstance(server_description, str) and server_description:
            server["description"] = server_description
        tool_configuration: dict[str, Any] = {"enabled": True}
        require_approval = config.get("require_approval")
        if require_approval in {"always", "never"} or isinstance(require_approval, dict):
            tool_configuration["require_approval"] = require_approval
        if isinstance(config.get("allowed_tools"), list) and config["allowed_tools"]:
            tool_configuration["allowed_tools"] = list(config["allowed_tools"])
        if tool_configuration:
            server["tool_configuration"] = tool_configuration
        if isinstance(config.get("auth_token"), str) and config["auth_token"]:
            server["authorization_token"] = config["auth_token"]
        return [server]

    def _extract_native_mcp_metadata(self, response: Any) -> dict[str, Any]:
        content = getattr(response, "content", None)
        if not isinstance(content, list):
            return {}
        blocks: list[dict[str, Any]] = []
        for block in content:
            block_type = getattr(block, "type", None)
            if isinstance(block_type, str) and block_type.startswith("mcp"):
                normalized = self._normalize_raw_response(block)
                if isinstance(normalized, dict):
                    blocks.append(normalized)
        if not blocks:
            return {}
        return {
            "native_mcp": {
                "provider": "anthropic",
                "blockCount": len(blocks),
                "blocks": blocks,
            }
        }
