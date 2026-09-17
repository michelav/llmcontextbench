from __future__ import annotations

import argparse
from pathlib import Path

from fastmcp import FastMCP

from ctxbench.ai.models.base import ToolResult, ToolSpec
from ctxbench.adapters.lattes.tools import LattesToolService


class LattesMCPServer:
    def __init__(
        self,
        *,
        contexts_dir: str,
        provider: object | None = None,
        allowed_operations: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self._service = LattesToolService(
            contexts_dir=contexts_dir,
            provider=provider,
            allowed_operations=allowed_operations,
        )
        self.app = FastMCP(
            name="ctxbench-lattes",
            instructions=(
                "MCP server for querying Lattes researcher data."
                " All tools are read-only and require lattes_id."
            ),
        )
        self._register_tools()
        self._tool_specs = self._service.list_tools()

    def _register_tools(self) -> None:
        for spec in self._service.list_tools():
            def make_tool(name: str):
                if name in {
                    "get_education", "get_projects", "get_supervisions", "get_experience",
                    "get_academic_activities", "get_publications", "get_technical_output", "get_artistic_output",
                }:
                    async def temporal_tool(
                        lattes_id: str,
                        start_year: int | None = None,
                        end_year: int | None = None,
                    ) -> object:
                        return self.call_tool(
                            name,
                            {"lattes_id": lattes_id, "start_year": start_year, "end_year": end_year},
                        ).content
                    temporal_tool.__name__ = name
                    return temporal_tool
                async def selected_tool(lattes_id: str) -> object:
                    return self.call_tool(name, {"lattes_id": lattes_id}).content
                selected_tool.__name__ = name
                return selected_tool
            selected_tool = make_tool(spec.name)
            self.app.tool(name=spec.name, description=spec.description)(selected_tool)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tool_specs)

    def call_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        result = self._service.call_tool(name, arguments)
        metadata = dict(result.metadata)
        metadata["transport"] = "mcp_server"
        return result.model_copy(update={"metadata": metadata})

    def close(self) -> None:
        self._service.close()


def build_lattes_mcp_server(*, contexts_dir: str, provider: object | None = None, allowed_operations: list[str] | tuple[str, ...] | None = None) -> LattesMCPServer:
    return LattesMCPServer(contexts_dir=contexts_dir, provider=provider, allowed_operations=allowed_operations)


def create_mcp(*, contexts_dir: str | None = None) -> FastMCP:
    resolved_contexts_dir = contexts_dir or _default_contexts_dir()
    return build_lattes_mcp_server(contexts_dir=resolved_contexts_dir).app


def _default_contexts_dir() -> str:
    return str((Path(__file__).resolve().parents[4] / "datasets" / "lattes" / "context").resolve())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the LLMContextBench Lattes MCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "http", "sse"],
        default="streamable-http",
        help="FastMCP transport to use.",
    )
    parser.add_argument(
        "--contexts-dir",
        default=_default_contexts_dir(),
        help="Directory containing Lattes context artifacts.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP-based transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP-based transports.",
    )
    parser.add_argument(
        "--path",
        default="/mcp",
        help="Path for streamable HTTP or SSE transports.",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="Disable the FastMCP startup banner.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    server = build_lattes_mcp_server(contexts_dir=args.contexts_dir)
    run_kwargs: dict[str, object] = {"show_banner": not args.no_banner}
    if args.transport in {"streamable-http", "http", "sse"}:
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port
        if args.transport == "streamable-http":
            run_kwargs["path"] = args.path
        if args.transport == "sse":
            run_kwargs["path"] = args.path
    try:
        server.app.run(args.transport, **run_kwargs)
    finally:
        server.close()


if __name__ == "__main__":
    main()
