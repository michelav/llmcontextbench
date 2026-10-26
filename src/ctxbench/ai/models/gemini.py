from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import Any

from ctxbench.ai.models.base import AIRequest, ModelAdapter, ModelInput, ModelResponse, ToolCall


class GeminiModel(ModelAdapter):
    supports_tool_calling = True
    def generate(self, model_input: ModelInput, request: AIRequest, trace: Any | None = None) -> ModelResponse:
        if request.strategy_name == "mcp":
            raise ValueError("unknown strategy: mcp")
        client = self._create_client()
        generation_config = self._build_generation_config(request, model_input)
        started_at = perf_counter()
        response = client.models.generate_content(
            model=request.model_name,
            contents=self._build_contents(model_input),
            config=generation_config or None,
        )
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
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
            metadata={"provider": "google", "model": request.model_name},
            continuation_state=self._build_continuation_state(response),
        )

    def _run_async(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                if pending:
                    for task in pending:
                        task.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()

    async def _generate_with_native_mcp(self, model_input: ModelInput, request: AIRequest) -> ModelResponse:
        client = self._create_client()
        generation_config = self._build_generation_config(
            request,
            model_input,
            additional_tools=[self._build_native_mcp_tool(request)],
        )
        started_at = perf_counter()
        response = await client.aio.models.generate_content(
            model=request.model_name,
            contents=self._build_contents(model_input),
            config=generation_config or None,
        )
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        input_tokens, output_tokens, total_tokens = self._extract_usage(response)
        cached_input_tokens = self._extract_cached_input_tokens(response)
        reasoning_tokens = self._extract_reasoning_tokens(response)
        metadata = {
            "provider": "google",
            "model": request.model_name,
            "native_mcp": self._extract_native_mcp_metadata(response),
        }
        return ModelResponse(
            text=self._extract_text(response),
            requested_tool_calls=self._extract_tool_calls(response),
            raw_response=self._normalize_raw_response(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
            metadata=metadata,
            continuation_state=self._build_continuation_state(response),
        )

    def _create_client(self) -> Any:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Gemini SDK is not installed.") from exc
        return genai.Client(api_key=self.params.get("api_key"))

    def _build_generation_config(
        self,
        request: AIRequest,
        model_input: ModelInput,
        additional_tools: list[Any] | None = None,
    ) -> Any:
        params = self._merged_params(request)
        sdk_types = self._sdk_types()
        config: dict[str, Any] = {"system_instruction": model_input.system_instruction}
        extra_tools = list(additional_tools or [])
        if model_input.tools:
            if sdk_types is None:
                declared_tools: list[Any] = [
                    {
                        "function_declarations": [
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters_json_schema": tool.input_schema,
                            }
                            for tool in model_input.tools
                        ]
                    }
                ]
                config["tools"] = declared_tools + extra_tools
                config["automatic_function_calling"] = {"disable": True}
            else:
                declarations = [
                    sdk_types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description,
                        parameters_json_schema=tool.input_schema,
                    )
                    for tool in model_input.tools
                ]
                config["tools"] = [sdk_types.Tool(function_declarations=declarations)] + extra_tools
                config["automatic_function_calling"] = sdk_types.AutomaticFunctionCallingConfig(disable=True)
        elif extra_tools:
            config["tools"] = extra_tools
        if "temperature" in params:
            config["temperature"] = params["temperature"]
        if "max_tokens" in params:
            config["max_output_tokens"] = params["max_tokens"]
        if "max_output_tokens" in params:
            config["max_output_tokens"] = params["max_output_tokens"]
        structured_output = params.get("structured_output")
        if isinstance(structured_output, dict):
            schema = structured_output.get("schema")
            if isinstance(schema, dict):
                config["response_mime_type"] = "application/json"
                config["response_json_schema"] = schema
        extra_config = params.get("config")
        if isinstance(extra_config, dict):
            config.update(self._normalize_config_keys(extra_config))
        if sdk_types is None:
            return config
        return sdk_types.GenerateContentConfig(**config)

    def _build_contents(self, model_input: ModelInput) -> Any:
        if not model_input.previous_tool_calls and not model_input.tool_results and not model_input.continuation_state:
            return model_input.prompt

        sdk_types = self._sdk_types()
        contents: list[Any] = [self._user_text_content(model_input.prompt, sdk_types)]
        model_content = model_input.continuation_state.get("model_content")
        if model_content is not None and not isinstance(model_content, dict):
            contents.append(model_content)
        elif isinstance(model_content, dict):
            contents.append(self._sdk_content_from_dict(model_content, sdk_types))
        elif model_input.previous_tool_calls:
            if sdk_types is None:
                contents.append(
                    {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": tool_call.name,
                                    "args": tool_call.arguments,
                                }
                            }
                            for tool_call in model_input.previous_tool_calls
                        ],
                    }
                )
            else:
                contents.append(
                    sdk_types.Content(
                        role="model",
                        parts=[
                            sdk_types.Part(
                                function_call=sdk_types.FunctionCall(
                                    name=tool_call.name,
                                    args=tool_call.arguments,
                                    id=tool_call.id,
                                )
                            )
                            for tool_call in model_input.previous_tool_calls
                        ],
                    )
                )
        if model_input.tool_results:
            if sdk_types is None:
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": result.name,
                                    "id": result.tool_call_id,
                                    "response": {"result": result.content},
                                }
                            }
                            for result in model_input.tool_results
                        ],
                    }
                )
            else:
                contents.append(
                    sdk_types.Content(
                        role="user",
                        parts=[
                            sdk_types.Part(
                                function_response=sdk_types.FunctionResponse(
                                    name=result.name,
                                    id=result.tool_call_id,
                                    response={"result": result.content},
                                )
                            )
                            for result in model_input.tool_results
                        ],
                    )
                )
        return contents

    def _extract_text(self, response: Any) -> str:
        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list):
            parts: list[str] = []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                parts_list = getattr(content, "parts", None)
                if not isinstance(parts_list, list):
                    continue
                for part in parts_list:
                    value = None
                    if isinstance(part, dict):
                        value = part.get("text")
                    else:
                        value = getattr(part, "text", None)
                    if isinstance(value, str):
                        parts.append(value)
            if parts:
                return "\n".join(parts).strip()
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        return ""

    def _extract_tool_calls(self, response: Any) -> list[ToolCall]:
        direct_calls = getattr(response, "function_calls", None)
        if isinstance(direct_calls, list):
            return [self._normalize_tool_call(call) for call in direct_calls]

        candidates = getattr(response, "candidates", None)
        if not isinstance(candidates, list):
            return []
        tool_calls: list[ToolCall] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts_list = getattr(content, "parts", None)
            if not isinstance(parts_list, list):
                continue
            for part in parts_list:
                call = getattr(part, "function_call", None) or getattr(part, "functionCall", None)
                if call is None and isinstance(part, dict):
                    call = part.get("functionCall") or part.get("function_call")
                if call is not None:
                    tool_calls.append(self._normalize_tool_call(call))
        return tool_calls

    def _normalize_tool_call(self, call: Any) -> ToolCall:
        if isinstance(call, dict):
            return ToolCall(
                id=call.get("id"),
                name=str(call.get("name", "")),
                arguments=call.get("args", {}) or {},
            )
        return ToolCall(
            id=getattr(call, "id", None),
            name=str(getattr(call, "name", "")),
            arguments=getattr(call, "args", {}) or {},
        )

    def _extract_usage(self, response: Any) -> tuple[int | None, int | None, int | None]:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None, None, None
        input_tokens = getattr(usage, "prompt_token_count", None)
        output_tokens = getattr(usage, "candidates_token_count", None)
        total_tokens = getattr(usage, "total_token_count", None)
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return input_tokens, output_tokens, total_tokens

    def _extract_reasoning_tokens(self, response: Any) -> int | None:
        usage = getattr(response, "usage_metadata", None)
        value = getattr(usage, "thoughts_token_count", None) if usage else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _extract_cached_input_tokens(self, response: Any) -> int | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None
        cached_input_tokens = getattr(usage, "cached_content_token_count", None)
        return cached_input_tokens if isinstance(cached_input_tokens, int) and not isinstance(cached_input_tokens, bool) else None

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
        candidates = getattr(response, "candidates", None)
        if isinstance(candidates, list) and candidates:
            content = getattr(candidates[0], "content", None)
            if content is not None:
                return {"model_content": content}
        return {}

    def _sdk_types(self) -> Any | None:
        try:
            from google.genai import types
        except ImportError:  # pragma: no cover
            return None
        return types

    def _user_text_content(self, prompt: str, sdk_types: Any | None) -> Any:
        if sdk_types is None:
            return {"role": "user", "parts": [{"text": prompt}]}
        return sdk_types.Content(role="user", parts=[sdk_types.Part(text=prompt)])

    def _sdk_content_from_dict(self, payload: dict[str, Any], sdk_types: Any | None) -> Any:
        if sdk_types is None:
            return payload
        role = str(payload.get("role", "model"))
        parts_payload = payload.get("parts", [])
        parts = [self._sdk_part_from_dict(part, sdk_types) for part in parts_payload if isinstance(part, dict)]
        return sdk_types.Content(role=role, parts=parts)

    def _sdk_part_from_dict(self, payload: dict[str, Any], sdk_types: Any) -> Any:
        if "text" in payload:
            return sdk_types.Part(text=payload["text"])
        if "functionCall" in payload:
            call = payload["functionCall"]
            kwargs: dict[str, Any] = {
                "function_call": sdk_types.FunctionCall(
                    name=call.get("name"),
                    args=call.get("args", {}),
                    id=call.get("id"),
                )
            }
            if "thought_signature" in payload:
                kwargs["thought_signature"] = payload["thought_signature"]
            return sdk_types.Part(**kwargs)
        if "functionResponse" in payload:
            response = payload["functionResponse"]
            return sdk_types.Part(
                function_response=sdk_types.FunctionResponse(
                    name=response.get("name"),
                    response=response.get("response", {}),
                    id=response.get("id"),
                )
            )
        return sdk_types.Part(text=str(payload))

    def _normalize_config_keys(self, d: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in d.items():
            s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", k)
            snake_k = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
            result[snake_k] = self._normalize_config_keys(v) if isinstance(v, dict) else v
        return result

    def _merged_params(self, request: AIRequest) -> dict[str, Any]:
        params = dict(self.params)
        params.update(request.params)
        return params

    def _extract_native_mcp_metadata(self, response: Any) -> dict[str, Any]:
        tool_calls = self._extract_tool_calls(response)
        if not tool_calls:
            return {}
        return {
            "visibleToolCallCount": len(tool_calls),
            "visibleToolCalls": [tool_call.model_dump(mode="json") for tool_call in tool_calls],
        }

    def _build_native_mcp_tool(self, request: AIRequest) -> Any:
        config = request.params.get("mcp_server")
        if not isinstance(config, dict):
            raise RuntimeError("Native MCP strategy requires params['mcp_server'] for Gemini models.")

        server_url = config.get("server_url") or config.get("url")
        if not isinstance(server_url, str) or not server_url:
            raise RuntimeError("Gemini MCP config requires a non-empty 'server_url' or 'url'.")

        server_label = str(config.get("server_label") or config.get("label") or "ctxbench-lattes")
        headers = self._build_mcp_headers(config)

        sdk_types = self._sdk_types()
        if sdk_types is None:
            return {
                "mcp_servers": [
                    {
                        "name": server_label,
                        "streamable_http_transport": {
                            "url": server_url,
                            **({"headers": headers} if headers else {}),
                        },
                    }
                ]
            }

        transport = sdk_types.StreamableHttpTransport(
            url=server_url,
            **({"headers": headers} if headers else {}),
        )
        server = sdk_types.McpServer(
            name=server_label,
            streamable_http_transport=transport,
        )
        return sdk_types.Tool(mcp_servers=[server])

    def _build_mcp_headers(self, config: dict[str, Any]) -> dict[str, str]:
        headers = dict(config.get("headers") or {}) if isinstance(config.get("headers"), dict) else {}
        auth_token = config.get("auth_token")
        if isinstance(auth_token, str) and auth_token:
            headers.pop("Authorization", None)
            headers.pop("authorization", None)
            if not auth_token.startswith("Bearer "):
                auth_token = f"Bearer {auth_token}"
            headers["Authorization"] = auth_token
        return headers
