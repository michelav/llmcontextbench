"""Runtime request and result contracts with no benchmark dependency."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ctxbench.ai.models.base import AIResult
from ctxbench.core.provisioning import ProvisioningConfiguration


class ContextContent(Protocol):
    content: object


class ContextSource(Protocol):
    def get_context(self, instance_id: str, task_id: str, representation: str) -> ContextContent: ...


@dataclass(slots=True)
class RuntimeRequest:
    task: str
    task_id: str
    instance_id: str
    provider: str
    model_name: str
    configuration: ProvisioningConfiguration
    surface_spec: dict[str, Any]
    params: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    cache_model_name: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    ai_result: AIResult
    started_at: str
    finished_at: str
    duration_ms: int
