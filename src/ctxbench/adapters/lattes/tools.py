from __future__ import annotations

from time import perf_counter
from typing import Any, Callable

from ctxbench.ai.models.base import ToolResult, ToolSpec
from ctxbench.adapters.lattes.provider import LattesProvider

TEMPORAL_SCHEMA = {
    "type": "object",
    "properties": {
        "lattes_id": {"type": "string"},
        "start_year": {"type": "integer"},
        "end_year": {"type": "integer"},
    },
    "required": ["lattes_id"],
    "additionalProperties": False,
}

IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "lattes_id": {"type": "string"},
    },
    "required": ["lattes_id"],
    "additionalProperties": False,
}


def list_lattes_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(name="get_profile", description="Return the researcher's identification data.", input_schema=IDENTITY_SCHEMA),
        ToolSpec(name="get_expertise", description="Return the researcher's expertise, research lines and awards.", input_schema=IDENTITY_SCHEMA),
        ToolSpec(name="get_education", description="Return the researcher's academic background.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_projects", description="Return the researcher's projects.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_supervisions", description="Return the researcher's supervision activities grouped by level (masters, doctoral, undergraduate, specialization, others), each with completed and ongoing lists.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_experience", description="Return the researcher's professional experience.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_academic_activities", description="Return academic service, boards, events and related activities.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_publications", description="Return the researcher's bibliographic production.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_technical_output", description="Return the researcher's technical output.", input_schema=TEMPORAL_SCHEMA),
        ToolSpec(name="get_artistic_output", description="Return the researcher's artistic and cultural output.", input_schema=TEMPORAL_SCHEMA),
    ]


class LattesToolService:
    def __init__(self, *, contexts_dir: str, provider: LattesProvider | None = None) -> None:
        self._contexts_dir = contexts_dir
        self._provider = provider or LattesProvider()
        self._tools = list_lattes_tool_specs()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "get_profile": self._call_get_profile,
            "get_expertise": self._call_get_expertise,
            "get_education": self._call_get_education,
            "get_projects": self._call_get_projects,
            "get_supervisions": self._call_get_supervisions,
            "get_experience": self._call_get_experience,
            "get_academic_activities": self._call_get_academic_activities,
            "get_publications": self._call_get_publications,
            "get_technical_output": self._call_get_technical_output,
            "get_artistic_output": self._call_get_artistic_output,
        }

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"Unknown Lattes tool: {name}")
        started_at = perf_counter()
        content = handler(arguments)
        duration_ms = max(0, int((perf_counter() - started_at) * 1000))
        lattes_id = _require_lattes_id(arguments)
        return ToolResult(
            name=name,
            content=content,
            metadata={
                "server_event": {
                    "toolName": name,
                    "arguments": dict(arguments),
                    "lattes_id": lattes_id,
                    "durationMs": duration_ms,
                }
            },
        )

    def close(self) -> None:
        self._provider.close()

    def _call_get_profile(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_profile(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
        )

    def _call_get_expertise(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_expertise(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
        )

    def _call_get_education(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_education(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_projects(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_projects(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_supervisions(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_supervisions(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_experience(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_experience(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_academic_activities(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_academic_activities(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_publications(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_publications(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_technical_output(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_technical_output(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )

    def _call_get_artistic_output(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._provider.get_artistic_output(
            contexts_dir=self._contexts_dir,
            lattes_id=_require_lattes_id(arguments),
            start_year=_optional_year(arguments, "start_year"),
            end_year=_optional_year(arguments, "end_year"),
        )


def _require_lattes_id(arguments: dict[str, Any]) -> str:
    value = arguments.get("lattes_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Lattes tools require a non-empty 'lattes_id' argument.")
    return value.strip()


def _optional_year(arguments: dict[str, Any], field_name: str) -> int | None:
    value = arguments.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Lattes tools require '{field_name}' to be an integer when provided.")
    return value
