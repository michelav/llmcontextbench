from __future__ import annotations

from ctxbench.dataset.errors import (
    AdapterUnavailableError,
    CapabilityUnavailableError,
    UnsupportedRepresentationError,
)
from ctxbench.dataset.payloads import (
    ORACLE_UNAVAILABLE,
    ContextPayload,
    EvidencePayload,
    OracleUnavailable,
    TaskPayload,
)


def test_adapter_errors_are_value_error_subclasses() -> None:
    assert issubclass(AdapterUnavailableError, ValueError)
    assert issubclass(CapabilityUnavailableError, ValueError)
    assert issubclass(UnsupportedRepresentationError, ValueError)


def test_oracle_unavailable_is_explicit_sentinel() -> None:
    assert ORACLE_UNAVAILABLE is not None
    assert isinstance(ORACLE_UNAVAILABLE, OracleUnavailable)


def test_payload_roles_and_task_statement() -> None:
    context = ContextPayload(role="context", representation="html", content="<html></html>")
    evidence = EvidencePayload(role="evidence", task={"id": "q1"}, evidence={"blocks": []})
    task = TaskPayload(task_id="q1", statement="What is the answer?")

    assert context.role == "context"
    assert evidence.role == "evidence"
    assert task.statement == "What is the answer?"
