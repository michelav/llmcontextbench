from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, Protocol

from ctxbench.ai.models.base import ToolResult, ToolSpec


class ToolRuntime(Protocol):
    def list_tools(self) -> list[ToolSpec]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...

    def close(self) -> None:
        ...


class ToolService(Protocol):
    def list_tools(self) -> list[ToolSpec]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        ...

    def close(self) -> None:
        ...


class InMemoryMCPServer(Protocol):
    app: Any

    def close(self) -> None:
        ...


class LocalFunctionRuntime:
    def __init__(self, service: ToolService) -> None:
        self._service = service

    def list_tools(self) -> list[ToolSpec]:
        return self._service.list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = self._service.call_tool(name, arguments)
        metadata = dict(result.metadata)
        metadata["runtime"] = "local_function"
        return result.model_copy(update={"metadata": metadata})

    def close(self) -> None:
        self._service.close()


class MCPRuntime:
    def __init__(
        self,
        *,
        transport: str,
        server: InMemoryMCPServer | None = None,
        server_url: str | None = None,
        headers: dict[str, str] | None = None,
        authorization: str | None = None,
        verify: Any | None = None,
        sse_read_timeout: float | int | None = None,
        server_label: str = "ctxbench-lattes",
        allowed_operations: list[str] | None = None,
    ) -> None:
        self._transport = transport.strip().lower().replace("-", "_")
        self._server = server
        self._server_url = server_url
        self._headers = dict(headers or {})
        self._authorization = authorization
        self._verify = verify
        self._sse_read_timeout = sse_read_timeout
        self._server_label = server_label
        self._allowed_operations = set(allowed_operations) if allowed_operations is not None else None
        self._closed = False

    @classmethod
    def for_local_server(cls, server: InMemoryMCPServer) -> "MCPRuntime":
        return cls(transport="in_memory", server=server)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MCPRuntime":
        transport = str(config.get("transport", "streamable_http"))
        server_url = config.get("server_url") or config.get("url")
        if transport.strip().lower().replace("-", "_") != "in_memory":
            if not isinstance(server_url, str) or not server_url:
                raise RuntimeError("MCP runtime config requires a non-empty 'server_url' or 'url'.")
        headers = config.get("headers") if isinstance(config.get("headers"), dict) else None
        authorization = config.get("auth_token") if isinstance(config.get("auth_token"), str) else None
        return cls(
            transport=transport,
            server_url=server_url if isinstance(server_url, str) else None,
            headers=headers,
            authorization=authorization,
            verify=config.get("verify"),
            sse_read_timeout=config.get("sse_read_timeout"),
            server_label=str(config.get("server_label") or config.get("label") or "ctxbench-lattes"),
            allowed_operations=(
                [str(name) for name in config["allowed_operations"]]
                if isinstance(config.get("allowed_operations"), list)
                else None
            ),
        )

    def list_tools(self) -> list[ToolSpec]:
        self._ensure_open()
        tools = asyncio.run(self._list_tools_async())
        if self._allowed_operations is not None:
            tools = [tool for tool in tools if tool.name in self._allowed_operations]
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self._ensure_open()
        if self._allowed_operations is not None and name not in self._allowed_operations:
            raise ValueError(f"MCP operation is not allowed: {name}")
        return asyncio.run(self._call_tool_async(name, arguments))

    def close(self) -> None:
        if self._closed:
            return
        if self._server is not None:
            self._server.close()
        self._closed = True

    async def _list_tools_async(self) -> list[ToolSpec]:
        async with self.session() as (session, _metadata):
            tools_result = await session.list_tools()
            tools = list(getattr(tools_result, "tools", []) or [])
        tools = [
            ToolSpec(
                name=str(tool.name),
                description=str(tool.description or ""),
                input_schema=dict(getattr(tool, "inputSchema", {}) or {}),
            )
            for tool in tools
        ]
        return tools

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        started_at = perf_counter()
        async with self.session() as (session, _metadata):
            result = await session.call_tool(name, arguments)
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        metadata = {
            "runtime": "mcp",
            "server_event": {
                "toolName": name,
                "arguments": dict(arguments),
                "durationMs": duration_ms,
                "transport": self._transport,
                "serverLabel": self._server_label,
            },
        }
        return ToolResult(
            name=name,
            content=_normalize_call_tool_result(result),
            is_error=bool(getattr(result, "isError", False)),
            metadata=metadata,
        )

    @asynccontextmanager
    async def session(self) -> Any:
        self._ensure_open()
        try:
            from fastmcp.client.transports import FastMCPTransport, StreamableHttpTransport
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("FastMCP client support is not installed.") from exc

        if self._transport == "in_memory":
            if self._server is None:
                raise RuntimeError("In-memory MCP runtime requires a local server instance.")
            transport = FastMCPTransport(self._server.app)
            async with transport.connect_session() as session:
                await session.initialize()
                yield session, self._session_metadata()
            return

        if self._transport == "streamable_http":
            transport = StreamableHttpTransport(
                url=str(self._server_url),
                headers=self._headers or None,
                auth=self._authorization,
                verify=self._verify,
                sse_read_timeout=self._sse_read_timeout,
            )
            async with transport.connect_session() as session:
                await session.initialize()
                yield session, self._session_metadata()
            return

        raise RuntimeError(f"Unsupported MCP transport: {self._transport}.")

    def _session_metadata(self) -> dict[str, Any]:
        metadata = {
            "transport": self._transport,
            "serverLabel": self._server_label,
            "clientFramework": "fastmcp",
        }
        if self._server_url:
            metadata["serverUrl"] = self._server_url
        return metadata

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("MCP runtime is closed.")


def _normalize_call_tool_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        return content
    normalized: list[Any] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            normalized.append(text)
            continue
        if hasattr(item, "model_dump"):
            normalized.append(item.model_dump(mode="json"))
            continue
        normalized.append(item)
    if len(normalized) == 1:
        return normalized[0]
    return normalized
