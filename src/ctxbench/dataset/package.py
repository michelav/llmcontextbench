from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    TaskPayload,
)

if TYPE_CHECKING:
    from ctxbench.dataset.capabilities import DatasetCapabilityReport


@dataclass(slots=True)
class DatasetMetadata:
    name: str
    description: str
    domain: str
    intended_uses: str
    limitations: str
    license_url: str | None
    citation_url: str | None


@dataclass(slots=True)
class StrategyDescriptor:
    name: str
    classification: str
    context_access_mode: str
    inline_vs_operation: str
    local_vs_remote: str
    loop_ownership: str
    metric_provenance: dict[str, str]
    observability_limitations: str
    comparability_implications: str


@runtime_checkable
class DatasetPackage(Protocol):
    def metadata(self) -> DatasetMetadata: ...

    def identity(self) -> str: ...

    def version(self) -> str: ...

    def origin(self) -> str | None: ...

    def list_instance_ids(self) -> list[str]: ...

    def list_task_ids(self) -> list[str]: ...

    def get_task(self, task_id: str) -> TaskPayload: ...

    def get_context(
        self,
        instance_id: str,
        task_id: str,
        representation: str,
    ) -> ContextPayload: ...

    def get_evidence(self, instance_id: str, task_id: str) -> EvidencePayload: ...

    def capability_report(self) -> DatasetCapabilityReport: ...

    def get_oracle(self, instance_id: str, task_id: str) -> object:
        return ORACLE_UNAVAILABLE

    def get_task_instance(self, instance_id: str, task_id: str) -> dict[str, object] | None:
        return None

    def tool_provider(self) -> object | None:
        return None

    def fixtures(self) -> object | None:
        return None

    def dataset_instructions(self) -> str | None:
        return None
