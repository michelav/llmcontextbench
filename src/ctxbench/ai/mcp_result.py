"""Preserve recoverable service errors at the FastMCP protocol boundary."""
from fastmcp.tools.tool import ToolResult as FastMCPToolResult
from mcp.types import CallToolResult

from ctxbench.ai.models.base import ToolResult


class OperationErrorResult(FastMCPToolResult):
    def to_mcp_result(self) -> CallToolResult:
        return CallToolResult(
            content=self.content,
            structuredContent=self.structured_content,
            isError=True,
        )


def mcp_operation_result(result: ToolResult) -> object:
    if not result.is_error:
        return result.content
    return OperationErrorResult(
        content=result.content,
        structured_content=result.content if isinstance(result.content, dict) else {"result": result.content},
    )
