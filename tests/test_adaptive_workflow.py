from __future__ import annotations

from pathlib import Path

import pytest

from ctxbench.adaptive.calibration_contract import (
    CalibrationArtifact,
    CalibrationEstimate,
    CalibrationProvenance,
)
from ctxbench.adaptive.estimator import EstimatorDefinition, FeaturePartitionKey
from ctxbench.adaptive.sensors import QualityObservation, SensorClass, SensorCost
from ctxbench.adaptive.types import (
    Candidate,
    ContextFit,
    Estimate,
    PerformanceEstimate,
    Provenance,
    RequestFeatures,
    TokenUsage,
)
from ctxbench.adaptive.workflow import (
    AdaptiveCandidateInvocation,
    AdaptivePlan,
    AdaptiveWorkflowPolicy,
    AdaptiveWorkloadRequest,
    QualitySLO,
    run_adaptive_workflow,
)
from ctxbench.dataset.capabilities import (
    FeatureCapability,
    RequestFeatureSchema,
    SignalCapability,
    SignalCost as CapabilityCost,
)
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.util.fs import load_json, write_json


def _capability() -> SignalCapability:
    return SignalCapability(
        signal_id="quality-proxy",
        version="1",
        metric_id="quality",
        sensor_class="semantic_proxy",
        value_provenance="estimated",
        cost=CapabilityCost(1, "estimated", 0, "derived"),
        value_scale="0..1",
    )


class QualityAssessor:
    capability = _capability()

    def __init__(self, values):
        self.values = values

    def assess(self, request_id, candidate_id, response):
        del response
        value = self.values.get((request_id, candidate_id))
        return QualityObservation(
            request_id=request_id,
            candidate_id=candidate_id,
            metric_id="quality",
            value=value,
            value_scale="0..1",
            assessor_id="quality-proxy",
            assessor_version="1",
            sensor_class=SensorClass.SEMANTIC_PROXY,
            provenance=Provenance.ESTIMATED if value is not None else Provenance.UNAVAILABLE,
            cost=(
                SensorCost(1, Provenance.MEASURED, TokenUsage(0, Provenance.DERIVED))
                if value is not None
                else SensorCost(None, Provenance.UNAVAILABLE, TokenUsage(None, Provenance.UNAVAILABLE))
            ),
        )


def _plan(request_ids=("request-1",), *, candidates=("candidate-a", "candidate-b"), policy=None, calibration=None):
    schema = RequestFeatureSchema(
        schema_id="fixture-features",
        version="1",
        features=(FeatureCapability("context_bytes", "number", "measured", unit="bytes"),),
        partition_keys=("context_bytes",),
    )
    requests = []
    for sequence, request_id in enumerate(request_ids, 1):
        invocations = {}
        for candidate_id in candidates:
            execution = ExecutionRequest(
                execution_id=f"{request_id}-{candidate_id}",
                workflow_id="workflow-fixture",
                correlation_id=request_id,
                experiment_id="experiment-fixture",
                execution_fingerprint="fingerprint-fixture",
                task_id="task-repeat",
                instance_id="instance-repeat",
                candidate_id=candidate_id,
                payload={"candidate": candidate_id},
            )
            invocations[candidate_id] = AdaptiveCandidateInvocation(
                Candidate(
                    candidate_id,
                    True,
                    ContextFit(10, 5, 100, Provenance.ESTIMATED),
                ),
                execution,
            )
        requests.append(
            AdaptiveWorkloadRequest(
                request_id=request_id,
                sequence_index=sequence,
                task_id="task-repeat",
                instance_id="instance-repeat",
                features=RequestFeatures(sequence, context_bytes=20),
                feature_values={"context_bytes": 20},
                candidate_order=tuple(candidates),
                candidates=invocations,
            )
        )
    return AdaptivePlan(
        workflow_id="workflow-fixture",
        execution_fingerprint="fingerprint-fixture",
        feature_schema=schema,
        policy=policy or AdaptiveWorkflowPolicy(),
        requests=tuple(requests),
        candidate_catalog=tuple(candidates),
        dataset_id="fixture-dataset" if calibration else None,
        dataset_version="1" if calibration else None,
        candidate_catalog_fingerprint="candidate-catalog-fp" if calibration else None,
        calibration=calibration,
    )


def _result(request, *, status="success", response="answer", duration=10, tokens=20):
    del request
    return {
        "status": status,
        "response": response,
        "timing": {"durationMs": duration},
        "metricsSummary": {
            "totalTokens": tokens,
            "totalTokensProvenance": "reported" if tokens is not None else "unavailable",
        },
    }


def _run(plan, tmp_path: Path, invoke, *, assessor=None, retry_uncertain=False):
    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    result = run_adaptive_workflow(
        plan,
        root=tmp_path,
        service=service,
        session=session,
        invoke=invoke,
        quality_assessor=assessor,
        retry_uncertain=retry_uncertain,
    )
    return result, service


def test_quality_slo_fallback_records_each_decision_and_repeated_occurrences(tmp_path):
    plan = _plan(("request-1", "request-2"), policy=AdaptiveWorkflowPolicy(
        quality_slos=(QualitySLO("quality", 0.8),),
    ))
    calls = []

    def invoke(request, _session):
        calls.append(request.execution_id)
        return _result(request)

    result, service = _run(
        plan,
        tmp_path,
        invoke,
        assessor=QualityAssessor({
            ("request-1", "candidate-a"): 0.2,
            ("request-1", "candidate-b"): 0.9,
            ("request-2", "candidate-a"): 0.95,
        }),
    )

    assert result.delivered == 2
    assert calls == ["request-1-candidate-a", "request-1-candidate-b", "request-2-candidate-a"]
    first = load_json(tmp_path / "adaptive-records" / "request-1.json")
    assert [row["decision"]["candidateId"] for row in first["attempts"]] == ["candidate-a", "candidate-b"]
    assert [row["decision"]["decisionId"] for row in first["attempts"]] == [
        "request-1:decision:0001", "request-1:decision:0002",
    ]
    assert first["delivery"]["candidateId"] == "candidate-b"
    assert service.attempts("request-1-candidate-a")[0]["result"]["_adaptiveSignals"]["quality"][0]["value"] == 0.2
    assert first["attempts"][0]["quality"][0]["cost"]["duration_ms"] == 1
    assert first["knowledgeAfter"]["estimatorId"] == "rolling_window_mean"


def test_latency_token_and_error_policies_route_to_the_next_candidate(tmp_path):
    policy = AdaptiveWorkflowPolicy(latency_limit_ms=50, token_limit=30)
    plan = _plan(candidates=("bad", "good"), policy=policy)

    def invoke(request, _session):
        if request.candidate_id == "bad":
            return _result(request, status="error", duration=100, tokens=90)
        return _result(request, duration=20, tokens=10)

    result, _ = _run(plan, tmp_path, invoke)
    record = result.requests[0]
    assert record["state"] == "delivered"
    assert record["attempts"][0]["analysis"]["unmet"] == [
        "execution_success", "latency_slo", "token_slo",
    ]
    assert record["delivery"]["candidateId"] == "good"


def test_unavailable_quality_is_explicit_and_never_satisfies_slo(tmp_path):
    plan = _plan(candidates=("candidate-a",), policy=AdaptiveWorkflowPolicy(
        quality_slos=(QualitySLO("quality", 0.8),),
    ))
    result, _ = _run(plan, tmp_path, lambda request, _session: _result(request), assessor=QualityAssessor({}))
    attempt = result.requests[0]["attempts"][0]
    assert result.failed == 1
    assert attempt["analysis"]["qualitySloStatus"] == {"quality": "unavailable"}
    assert "quality_unavailable:quality" in attempt["analysis"]["unmet"]
    assert attempt["quality"][0]["value"] is None
    assert attempt["quality"][0]["provenance"] == "unavailable"


def test_quality_slo_requires_declared_assessor_before_any_execution(tmp_path):
    plan = _plan( policy=AdaptiveWorkflowPolicy(quality_slos=(QualitySLO("quality", 0.8),)))
    calls = []
    with pytest.raises(ValueError, match="require a declared online quality assessor"):
        _run(plan, tmp_path, lambda *args: calls.append(args))
    assert calls == []


def test_quota_admission_is_persisted_and_does_not_invoke_provider(tmp_path):
    partition = FeaturePartitionKey("fixture-features", "1", (("context_bytes", 20),))
    calibration = CalibrationArtifact(
        provenance=CalibrationProvenance(
            source_run_id="calibration-run",
            source_artifact_fingerprint="calibration-fingerprint",
            dataset_id="fixture-dataset",
            dataset_version="1",
            candidate_catalog_fingerprint="candidate-catalog-fp",
            feature_schema_id="fixture-features",
            feature_schema_version="1",
            estimator=EstimatorDefinition(),
            source_request_ids=("calibration-request-1",),
        ),
        estimates=(CalibrationEstimate(
            "candidate-a", partition,
            PerformanceEstimate(Estimate(10, Provenance.DERIVED, 3),
                                Estimate(10, Provenance.DERIVED, 3)),
        ),),
    )
    plan = _plan(
        candidates=("candidate-a",),
        policy=AdaptiveWorkflowPolicy(token_budget=5),
        calibration=calibration,
    )
    calls = []
    result, _ = _run(plan, tmp_path, lambda *args: calls.append(args))
    assert result.rejected == 1
    assert calls == []
    record = load_json(tmp_path / "adaptive-records" / "request-1.json")
    assert record["attempts"][0]["decision"]["candidateId"] is None
    admission = record["attempts"][0]["admission"]
    assert admission["enabled"] is True
    assert admission["remainingTokens"] == 5
    assert admission["candidates"][0]["status"] == "token_budget_exceeded"
    replayed, _ = _run(plan, tmp_path, lambda *args: calls.append(args))
    assert replayed.rejected == 1
    replayed_record = load_json(tmp_path / "adaptive-records" / "request-1.json")
    assert replayed_record["attempts"][0]["decision"] == record["attempts"][0]["decision"]
    assert replayed_record["attempts"][0]["admission"] == admission


def test_future_request_observations_cannot_change_an_earlier_decision(tmp_path):
    plan = _plan(("request-1", "request-2"), policy=AdaptiveWorkflowPolicy(selection_metric="latency"))
    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    future_execution = plan.requests[1].candidates["candidate-b"].execution
    future_observation = {
        "configuration_id": "candidate-b", "size_bin": None,
        "status": "success", "end_to_end_duration_ms": 0.1,
        "duration_provenance": "measured",
        "tokens": {"value": 1, "provenance": "reported"},
    }
    future_outcome = service.execute(
        future_execution,
        session,
        lambda *_: {
            "status": "success", "response": "future",
            "_adaptiveSignals": {"observation": future_observation},
        },
    )
    future = {
        "schemaVersion": 2,
        "requestId": "request-2",
        "sequenceIndex": 2,
        "executionFingerprint": "fingerprint-fixture",
        "taskId": "task-repeat",
        "instanceId": "instance-repeat",
        "state": "delivered",
        "delivery": {"candidateId": "candidate-b", "executionId": "request-2-candidate-b"},
        "attempts": [{
            "decision": {
                "decisionId": "request-2:decision:0001", "requestId": "request-2",
                "sequenceIndex": 2, "candidateId": "candidate-b",
            },
            "executionId": "request-2-candidate-b",
            "execution": {
                "executionId": future_outcome.execution_id,
                "attemptId": future_outcome.attempt_id,
                "status": "success", "resumed": False,
            },
            "monitored": True,
            "observation": future_observation,
        }],
    }
    write_json(tmp_path / "adaptive-records" / "request-2.json", future)

    result = run_adaptive_workflow(
        plan, root=tmp_path, service=service, session=session,
        invoke=lambda request, _session: _result(request),
    )
    first = result.requests[0]["attempts"][0]["decision"]
    assert first["candidateId"] == "candidate-a"
    assert first["estimates"]["candidate-b"]["latency_ms"]["value"] is None


def test_started_request_resume_reuses_saved_decision_and_service_attempt(tmp_path):
    plan = _plan(candidates=("candidate-a", "candidate-b"))
    calls = 0

    def interrupted(request, _session):
        nonlocal calls
        calls += 1
        raise KeyboardInterrupt

    service = TrialExecutionService(tmp_path)
    session = ExecutionSession(object())
    with pytest.raises(KeyboardInterrupt):
        run_adaptive_workflow(
            plan, root=tmp_path, service=service, session=session, invoke=interrupted,
        )
    started = load_json(tmp_path / "adaptive-records" / "request-1.json")
    assert len(started["attempts"]) == 1
    saved_decision = started["attempts"][0]["decision"]
    assert saved_decision["candidateId"] == "candidate-a"

    result = run_adaptive_workflow(
        plan,
        root=tmp_path,
        service=service,
        session=session,
        invoke=lambda request, _session: _result(request),
        retry_uncertain=True,
    )
    completed = result.requests[0]
    assert completed["state"] == "delivered"
    assert len(completed["attempts"]) == 1
    assert completed["attempts"][0]["decision"] == saved_decision
    assert [row["state"] for row in service.attempts("request-1-candidate-a")] == ["started", "succeeded"]
