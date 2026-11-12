"""Durable invocation service shared by benchmark and adaptive workflows.

Workflow adapters provide the invocation callback and serialize its result. This module owns
execution identity, attempt recovery, and session lifetime without importing workflow models.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Callable

from ctxbench.util.clock import utc_now_iso
from ctxbench.util.fs import load_json, write_json


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    execution_id: str
    workflow_id: str
    correlation_id: str
    experiment_id: str
    execution_fingerprint: str
    task_id: str
    instance_id: str
    candidate_id: str | None
    payload: Any
    trial_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("execution_id", "workflow_id", "correlation_id", "experiment_id",
                           "execution_fingerprint", "task_id", "instance_id"):
            if not getattr(self, field_name):
                raise ValueError(f"ExecutionRequest.{field_name} must be nonempty")


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    execution_id: str
    attempt_id: str
    status: str
    result: dict[str, Any]
    resumed: bool


class ExecutionSession:
    """Explicit owner for reusable runtime resources within one execution batch/episode."""

    def __init__(self, resource: Any):
        self.resource = resource
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            close = getattr(self.resource, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> "ExecutionSession":
        if self._closed:
            raise RuntimeError("ExecutionSession is already closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


Invocation = Callable[[ExecutionRequest, ExecutionSession], dict[str, Any]]


class TrialExecutionService:
    """Execute and persist one workflow-neutral invocation with explicit recovery semantics."""

    def __init__(self, artifact_root: str | Path):
        self.root = Path(artifact_root)

    def attempts(self, execution_id: str) -> list[dict[str, Any]]:
        directory = self._directory(execution_id)
        if not directory.exists():
            return []
        attempts: list[dict[str, Any]] = []
        for path in sorted(directory.glob("attempt-*.json")):
            try:
                record = load_json(path)
            except Exception as exc:
                raise ValueError(f"Invalid execution record {path}: {exc}") from exc
            self._validate_record(record, path, execution_id)
            attempts.append(record)
        return sorted(attempts, key=lambda row: row["attemptIndex"])

    def execute(
        self,
        request: ExecutionRequest,
        session: ExecutionSession,
        invoke: Invocation,
        *,
        force: bool = False,
        retry_uncertain: bool = False,
    ) -> ExecutionOutcome:
        if session.closed:
            raise RuntimeError("Cannot execute with a closed ExecutionSession")
        attempts = self.attempts(request.execution_id)
        if attempts:
            last = attempts[-1]
            if last.get("executionFingerprint") != request.execution_fingerprint:
                raise ValueError(f"Execution fingerprint mismatch for executionId {request.execution_id}.")
            if last["state"] == "started" and not retry_uncertain:
                raise ValueError(
                    f"Execution has uncertain started attempt for executionId {request.execution_id}; "
                    "pass --retry-uncertain to create a new attempt."
                )
            if last["state"] in {"succeeded", "failed"} and not force:
                return ExecutionOutcome(
                    request.execution_id, last["attemptId"], last["result"].get("status", "error"),
                    last["result"], True,
                )

        index = attempts[-1]["attemptIndex"] + 1 if attempts else 1
        record = self._begin(request, index)
        result = invoke(request, session)
        if not isinstance(result, dict):
            raise TypeError("Execution invocation must return a serialized result object")
        if request.trial_id and result.get("trialId") != request.trial_id:
            raise ValueError("Invocation result trialId does not match the execution request")
        terminal = "succeeded" if result.get("status") == "success" else "failed"
        finished = {**record, "state": terminal, "finishedAt": utc_now_iso(), "result": result}
        write_json(self._attempt_path(request.execution_id, index), finished)
        return ExecutionOutcome(request.execution_id, record["attemptId"], result.get("status", "error"), result, False)

    def _begin(self, request: ExecutionRequest, index: int) -> dict[str, Any]:
        key = self._key(request.execution_id)
        record = {
            "executionRecordVersion": 1,
            "executionId": request.execution_id,
            "workflowId": request.workflow_id,
            "correlationId": request.correlation_id,
            "trialId": request.trial_id,
            "experimentId": request.experiment_id,
            "taskId": request.task_id,
            "instanceId": request.instance_id,
            "candidateId": request.candidate_id,
            "attemptId": f"{key[:16]}-{index:06d}",
            "attemptIndex": index,
            "executionFingerprint": request.execution_fingerprint,
            "state": "started",
            "startedAt": utc_now_iso(),
        }
        write_json(self._attempt_path(request.execution_id, index), record)
        return record

    def _validate_record(self, record: Any, path: Path, execution_id: str) -> None:
        if not isinstance(record, dict) or record.get("executionRecordVersion") != 1:
            raise ValueError(f"Invalid execution record {path}: unsupported record")
        # Older benchmark v4 attempts used trialId as the execution identity.
        stored_id = record.get("executionId", record.get("trialId"))
        if stored_id != execution_id:
            raise ValueError(f"Execution record identity mismatch in {path}")
        index = record.get("attemptIndex")
        if type(index) is not int or index < 1 or path.name != f"attempt-{index:06d}.json":
            raise ValueError(f"Invalid attempt index in {path}")
        if record.get("state") not in {"started", "succeeded", "failed"}:
            raise ValueError(f"Invalid execution state in {path}")
        expected_id = f"{self._key(execution_id)[:16]}-{index:06d}"
        if record.get("attemptId") != expected_id:
            raise ValueError(f"Invalid attemptId in {path}")
        if not record.get("executionFingerprint"):
            raise ValueError(f"Missing execution fingerprint in {path}")
        if record["state"] in {"succeeded", "failed"} and not isinstance(record.get("result"), dict):
            raise ValueError(f"Completed execution record has no result in {path}")

    def _directory(self, execution_id: str) -> Path:
        return self.root / "execution-records" / self._key(execution_id)

    def _attempt_path(self, execution_id: str, index: int) -> Path:
        return self._directory(execution_id) / f"attempt-{index:06d}.json"

    @staticmethod
    def _key(execution_id: str) -> str:
        return hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:24]
