"""Derived adaptive response and request/attempt projections."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.execution.service import TrialExecutionService
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import write_jsonl


RESPONSE_SCHEMA_VERSION = 2


def rebuild_adaptive_responses(
    root: str | Path,
    *,
    service: TrialExecutionService | None = None,
) -> list[dict[str, Any]]:
    """Project exactly one delivered response per terminal adaptive request.

    Request records and execution attempts remain the authorities. ``responses.jsonl`` is a
    rebuildable view of successful deliveries; rejected and failed requests have no response.
    """
    artifact_root = Path(root)
    records_root = artifact_root / "adaptive-records"
    execution_service = service or TrialExecutionService(artifact_root)
    responses: list[dict[str, Any]] = []
    seen_requests: set[str] = set()
    if records_root.exists():
        for path in sorted(records_root.glob("*.json")):
            record = load_json(path)
            if not isinstance(record, dict) or record.get("schemaVersion") != 2:
                raise ValueError(f"Unsupported adaptive request record: {path}")
            request_id = record.get("requestId")
            if not isinstance(request_id, str) or not request_id or path.stem != request_id:
                raise ValueError(f"Invalid request identity in {path}")
            if request_id in seen_requests:
                raise ValueError(f"Duplicate adaptive requestId: {request_id}")
            seen_requests.add(request_id)
            if record.get("state") != "delivered":
                continue
            delivery = record.get("delivery")
            if not isinstance(delivery, dict):
                raise ValueError(f"Delivered request has no delivery reference: {request_id}")
            execution_id = delivery.get("executionId")
            attempt_id = delivery.get("attemptId")
            if not isinstance(execution_id, str) or not isinstance(attempt_id, str):
                raise ValueError(f"Invalid delivery reference for request {request_id}")
            attempts = execution_service.attempts(execution_id)
            attempt = next((item for item in attempts if item.get("attemptId") == attempt_id), None)
            if attempt is None or attempt.get("state") != "succeeded":
                raise ValueError(f"Delivery does not reference a successful execution for {request_id}")
            if attempt.get("correlationId") != request_id:
                raise ValueError(f"Execution request correlation mismatch for {request_id}")
            result = attempt.get("result")
            if not isinstance(result, dict):
                raise ValueError(f"Delivered execution has no result for {request_id}")
            candidate_id = delivery.get("candidateId")
            if attempt.get("candidateId") != candidate_id:
                raise ValueError(f"Delivery candidate mismatch for request {request_id}")
            response = {key: value for key, value in result.items() if key != "_adaptiveSignals"}
            response.pop("trialId", None)
            response.update({
                "workflowKind": "adaptive",
                "responseSchemaVersion": RESPONSE_SCHEMA_VERSION,
                "responseId": request_id,
                "requestId": request_id,
                "executionId": execution_id,
                "attemptId": attempt_id,
            })
            responses.append(response)
    responses.sort(key=lambda row: (row.get("sequenceIndex", 0), row["requestId"]))
    write_jsonl(artifact_root / "responses.jsonl", responses)
    return responses

