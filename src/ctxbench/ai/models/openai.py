from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse, ToolCall


class OpenAIModel(ModelAdapter):
    supports_tool_calling = True
    def generate(self, model_input: ModelInput, request: AIRequest, trace: Any | None = None) -> ModelResponse:
        client = self._create_client()
        payload = self._build_payload(model_input, request)
        started_at = perf_counter()
        response = client.responses.create(**payload)
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        input_tokens, output_tokens, total_tokens = self._extract_usage(response)
        cached_input_tokens = self._extract_cached_input_tokens(response)
        reasoning_tokens = self._extract_reasoning_tokens(response)
        return ModelResponse(
            text=self._extract_text(response),
            requested_tool_calls=self._extract_tool_calls(response),
            raw_response=self._normalize_raw_response(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_read_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
            metadata={
                "provider": "openai",
                "model": request.model_name,
                **self._extract_cache_metadata(response),
                **self._extract_native_mcp_metadata(response),
            },
            continuation_state=self._build_continuation_state(response),
        )

    def _create_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("OpenAI SDK is not installed.") from exc
        return OpenAI(api_key=self.params.get("api_key"))

    def _build_payload(self, model_input: ModelInput, request: AIRequest) -> dict[str, Any]:
        params = self._merged_params(request)
        payload: dict[str, Any] = {
            "model": request.model_name,
            "instructions": model_input.system_instruction,
            "input": self._build_input(model_input),
        }
        metadata = self._request_metadata(request)
        if metadata:
            payload["metadata"] = metadata
        if model_input.tools:
            payload["tools"] = [self._serialize_tool(tool) for tool in model_input.tools]
        if "temperature" in params:
            payload["temperature"] = params["temperature"]
        if "max_tokens" in params:
            payload["max_output_tokens"] = params["max_tokens"]
        if "max_output_tokens" in params:
            payload["max_output_tokens"] = params["max_output_tokens"]
        if "prompt_cache_key" in params:
            payload["prompt_cache_key"] = params["prompt_cache_key"]
        if "prompt_cache_retention" in params:
            payload["prompt_cache_retention"] = params["prompt_cache_retention"]
        if "reasoning" in params:
            payload["reasoning"] = params["reasoning"]
        structured_output = params.get("structured_output")
        if isinstance(structured_output, dict):
            schema = structured_output.get("schema")
            if isinstance(schema, dict):
                payload["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": str(structured_output.get("name") or "structured_output"),
                        "strict": bool(structured_output.get("strict", True)),
                        "schema": schema,
                    }
                }
        return payload

    def _build_input(self, model_input: ModelInput) -> str | list[dict[str, Any]]:
        if not model_input.continuation_state and not model_input.tool_results:
            return model_input.prompt

        items: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": model_input.prompt}],
            }
        ]
        items.extend(model_input.continuation_state.get("response_output", []))
        items.extend(self._serialize_tool_result(result) for result in model_input.tool_results)
        return items

    def _serialize_tool(self, tool: Any) -> dict[str, Any]:
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }

    def _serialize_tool_result(self, result: Any) -> dict[str, Any]:
        return {
            "type": "function_call_output",
            "call_id": result.tool_call_id,
            "output": json.dumps(result.content),
        }

    def _extract_text(self, response: Any) -> str:
        text = getattr(response, "output_text", None)
        if isinstance(text, str):
            return text
        output = getattr(response, "output", None)
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                content = getattr(item, "content", None)
                if not isinstance(content, list):
                    continue
                for block in content:
                    value = getattr(block, "text", None)
                    if isinstance(value, str):
                        parts.append(value)
            if parts:
                return "\n".join(parts).strip()
        return ""

    def _extract_tool_calls(self, response: Any) -> list[ToolCall]:
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return []
        tool_calls: list[ToolCall] = []
        for item in output:
            item_type = getattr(item, "type", None)
            if item_type != "function_call":
                continue
            raw_arguments = getattr(item, "arguments", "")
            arguments = self._parse_json_arguments(raw_arguments)
            tool_calls.append(
                ToolCall(
                    id=getattr(item, "call_id", None) or getattr(item, "id", None),
                    name=str(getattr(item, "name", "")),
                    arguments=arguments,
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

    def _extract_cached_input_tokens(self, response: Any) -> int | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        input_token_details = getattr(usage, "input_tokens_details", None)
        value = self._extract_cached_tokens_from_details(input_token_details)
        if value is not None:
            return value
        prompt_token_details = getattr(usage, "prompt_tokens_details", None)
        return self._extract_cached_tokens_from_details(prompt_token_details)

    def _extract_reasoning_tokens(self, response: Any) -> int | None:
        usage = getattr(response, "usage", None)
        details = getattr(usage, "output_tokens_details", None)
        if details is None:
            return None
        value = getattr(details, "reasoning_tokens", None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and item.get("type") == "reasoning_tokens":
                    v = item.get("token_count")
                    if isinstance(v, int) and not isinstance(v, bool):
                        return v
        return None

    def _extract_cached_tokens_from_details(self, details: Any) -> int | None:
        if details is None:
            return None
        cached_tokens = getattr(details, "cached_tokens", None)
        if isinstance(cached_tokens, int) and not isinstance(cached_tokens, bool):
            return cached_tokens
        if isinstance(details, dict):
            value = details.get("cached_tokens")
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and item.get("type") == "cached_tokens":
                    value = item.get("token_count")
                    if isinstance(value, int) and not isinstance(value, bool):
                        return value
        return None

    def _extract_cache_metadata(self, response: Any) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        cache_metadata: dict[str, Any] = {}
        for name in ("input_tokens_details", "prompt_tokens_details", "cache_tokens_details"):
            value = self._normalize_attr(getattr(usage, name, None))
            if value is not None:
                cache_metadata[name] = value
        cached_content_token_count = getattr(usage, "cached_content_token_count", None)
        if cached_content_token_count is not None:
            cache_metadata["cached_content_token_count"] = cached_content_token_count
        if not cache_metadata:
            return {}
        return {"cache": cache_metadata}

    def _normalize_raw_response(self, response: Any) -> Any:
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        if hasattr(response, "dict"):
            return response.dict()
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

    def _normalize_attr(self, value: Any) -> Any:
        if value is None:
            return None
        normalized = self._normalize_raw_response(value)
        return normalized

    def _build_continuation_state(self, response: Any) -> dict[str, Any]:
        output = getattr(response, "output", None)
        if isinstance(output, list):
            items = []
            for item in output:
                d = self._normalize_raw_response(item)
                if isinstance(d, dict):
                    d.pop("status", None)
                items.append(d)
            return {"response_output": items}
        return {}

    def _parse_json_arguments(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _merged_params(self, request: AIRequest) -> dict[str, Any]:
        params = dict(self.params)
        params.update(request.params)
        return params

    def _request_metadata(self, request: AIRequest) -> dict[str, str]:
        metadata: dict[str, str] = {}
        for source_key, target_key in (
            ("trialId", "trialId"),
            ("experimentId", "experimentId"),
            ("taskId", "taskId"),
            ("phase", "phase"),
        ):
            if source_key == "trialId":
                value = request.trial_id()
            elif source_key == "experimentId":
                value = request.experiment_id()
            elif source_key == "taskId":
                value = request.task_id()
            else:
                value = request.metadata.get(source_key)
            if value is not None and str(value):
                metadata[target_key] = str(value)
        return metadata

    def _build_native_mcp_tools(self, request: AIRequest) -> list[dict[str, Any]]:
        if request.strategy_name == "mcp":
            raise ValueError("unknown strategy: mcp")
        if request.strategy_name != "remote_mcp":
            return []
        config = request.params.get("mcp_server")
        if not isinstance(config, dict):
            raise RuntimeError("Native MCP strategy requires params['mcp_server'] for OpenAI models.")
        server_url = config.get("server_url") or config.get("url")
        server_label = config.get("server_label") or config.get("label") or "ctxbench-lattes"
        if not isinstance(server_url, str) or not server_url:
            raise RuntimeError("OpenAI MCP config requires a non-empty 'server_url' or 'url'.")
        tool: dict[str, Any] = {
            "type": "mcp",
            "server_label": str(server_label),
            "server_url": server_url,
            "require_approval": "never"
        }
        server_description = config.get("server_description") or config.get("description")
        if isinstance(server_description, str) and server_description:
            tool["server_description"] = server_description
        require_approval = config.get("require_approval")
        if require_approval in {"always", "never"} or isinstance(require_approval, dict):
            tool["require_approval"] = require_approval
        if isinstance(config.get("auth_token"), str) and config["auth_token"]:
            tool["authorization"] = config["auth_token"]
        headers = dict(config.get("headers") or {}) if isinstance(config.get("headers"), dict) else {}
        if "authorization" in tool:
            headers.pop("Authorization", None)
            headers.pop("authorization", None)
        if headers:
            tool["headers"] = headers
        if isinstance(config.get("allowed_tools"), list) and config["allowed_tools"]:
            tool["allowed_tools"] = list(config["allowed_tools"])
        return [tool]

    def _extract_native_mcp_metadata(self, response: Any) -> dict[str, Any]:
        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return {}
        calls: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        for item in output:
            item_type = getattr(item, "type", None)
            normalized = self._normalize_raw_response(item)
            if item_type == "mcp_call" and isinstance(normalized, dict):
                calls.append(normalized)
            elif item_type == "mcp_approval_request" and isinstance(normalized, dict):
                approvals.append(normalized)
        if not calls and not approvals:
            return {}
        return {
            "native_mcp": {
                "provider": "openai",
                "callCount": len(calls),
                "approvalRequestCount": len(approvals),
                "calls": calls,
                "approvalRequests": approvals,
            }
        }
