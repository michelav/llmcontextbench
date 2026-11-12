from __future__ import annotations

import pytest

from ctxbench.execution.service import (
    ExecutionRequest,
    ExecutionSession,
    TrialExecutionService,
)


def _request(**changes):
    values = {
        "execution_id": "execution-1",
        "workflow_id": "workflow-1",
        "correlation_id": "trial-1",
        "experiment_id": "experiment-1",
        "execution_fingerprint": "fingerprint-1",
        "task_id": "task-1",
        "instance_id": "instance-1",
        "candidate_id": "model/configuration",
        "payload": {"runtime": "opaque"},
        "trial_id": "trial-1",
    }
    values.update(changes)
    return ExecutionRequest(**values)


def test_service_persists_and_resumes_a_terminal_execution(tmp_path):
    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    calls = []

    def invoke(request, active_session):
        calls.append((request.execution_id, active_session is session))
        return {"trialId": request.trial_id, "status": "success", "response": "answer"}

    first = service.execute(_request(), session, invoke)
    second = service.execute(_request(), session, invoke)

    assert first.status == "success" and not first.resumed
    assert second.resumed and second.result == first.result
    assert calls == [("execution-1", True)]
    records = service.attempts("execution-1")
    assert len(records) == 1
    assert records[0]["executionId"] == "execution-1"
    assert records[0]["correlationId"] == "trial-1"


def test_uncertain_execution_requires_explicit_retry_and_records_new_attempt(tmp_path):
    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    request = _request()

    def interrupted(_request, _session):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        service.execute(request, session, interrupted)
    with pytest.raises(ValueError, match="uncertain started attempt"):
        service.execute(request, session, lambda *_: pytest.fail("must not invoke"))

    outcome = service.execute(
        request, session,
        lambda req, _session: {"trialId": req.trial_id, "status": "error", "response": ""},
        retry_uncertain=True,
    )
    assert outcome.status == "error"
    assert [row["state"] for row in service.attempts("execution-1")] == ["started", "failed"]


def test_force_creates_a_new_attempt_and_fingerprint_mismatch_is_rejected(tmp_path):
    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    invoke = lambda req, _session: {"trialId": req.trial_id, "status": "success"}
    service.execute(_request(), session, invoke)
    second = service.execute(_request(), session, invoke, force=True)
    assert second.attempt_id.endswith("000002")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        service.execute(_request(execution_fingerprint="different"), session, invoke)


def test_execution_session_closes_its_resource_once():
    class Resource:
        closed = 0

        def close(self):
            self.closed += 1

    resource = Resource()
    session = ExecutionSession(resource)
    session.close()
    session.close()
    assert resource.closed == 1 and session.closed
    with pytest.raises(RuntimeError, match="already closed"):
        session.__enter__()
