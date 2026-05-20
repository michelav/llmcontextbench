from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ContextPayload:
    role: Literal["context"]
    representation: str
    content: object
    content_type: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class EvidencePayload:
    role: Literal["evidence"]
    task: object
    evidence: object
    task_instance: object | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class TaskPayload:
    task_id: str
    statement: str
    tags: list[str] = field(default_factory=list)
    validation_type: str = "judge"
    context_blocks: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


class OracleUnavailable:
    """Distinct sentinel returned when no oracle is available."""


ORACLE_UNAVAILABLE = OracleUnavailable()
