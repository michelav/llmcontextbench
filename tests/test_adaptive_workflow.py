from __future__ import annotations

from pathlib import Path
from dataclasses import replace

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
from ctxbench.adaptive.projections import rebuild_adaptive_responses
from ctxbench.dataset.capabilities import (
    FeatureCapability,
    RequestFeatureSchema,
    SignalCapability,
    SignalCost as CapabilityCost,
)
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import read_jsonl
from ctxbench.metrics.adaptive import build_adaptive_metrics
from ctxbench.commands.metrics import metrics_command


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
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
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
    projected = read_jsonl(tmp_path / "responses.jsonl")
    assert [row["requestId"] for row in projected] == ["request-1", "request-2"]
    assert all("trialId" not in row and "_adaptiveSignals" not in row for row in projected)
    assert all(row["responseId"] == row["requestId"] for row in projected)
    request_metrics, attempt_metrics = build_adaptive_metrics(tmp_path)
    first_metrics = request_metrics[0]
    assert first_metrics["attemptCount"] == 2
    assert first_metrics["generationTotalTokens"] == 30
    assert first_metrics["deliveredTotalTokens"] == 15
    assert first_metrics["nonDeliveredAttemptCount"] == 1
    assert first_metrics["knownNonDeliveredTotalTokens"] == 15
    assert first_metrics["nonDeliveredUsageCompleteness"] == "complete"
    assert first_metrics["attemptsNotAccepted"] == 1
    assert first_metrics["unmetConditions"]
    assert first_metrics["terminalReason"] == "all_declared_acceptance_and_quality_slos_met"
    assert first_metrics["requestDurationProvenance"] == "measured"
    (tmp_path / "responses.jsonl").unlink()
    rebuilt = rebuild_adaptive_responses(tmp_path, service=service)
    assert rebuilt == projected
    assert len(attempt_metrics) == 3
    assert sum(row["delivered"] for row in attempt_metrics) == 2


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
    request_metrics, attempt_metrics = build_adaptive_metrics(tmp_path)
    assert request_metrics[0]["state"] == "failed"
    assert request_metrics[0]["delivered"] is False
    assert request_metrics[0]["terminalReason"] == "candidate_catalog_exhausted"
    assert request_metrics[0]["nonDeliveredAttemptCount"] == 1
    assert len(attempt_metrics) == 1


def test_quality_slo_requires_declared_assessor_before_any_execution(tmp_path):
    plan = _plan( policy=AdaptiveWorkflowPolicy(quality_slos=(QualitySLO("quality", 0.8),)))
    calls = []
    with pytest.raises(ValueError, match="require a declared online quality assessor"):
        _run(plan, tmp_path, lambda *args: calls.append(args))
    assert calls == []


def test_adaptive_metrics_command_writes_request_and_attempt_artifacts(tmp_path):
    from ctxbench.adaptive.artifacts import write_adaptive_artifacts

    plan = _plan()
    write_adaptive_artifacts(
        tmp_path, plan, dataset={"id": "fixture", "version": "1", "materializedPath": str(tmp_path)},
    )
    _run(plan, tmp_path, lambda request, _session: _result(request))

    output = tmp_path / "metrics"
    assert metrics_command([str(tmp_path)], output=str(output)) == 0
    assert (output / "adaptive_request_metrics.csv").exists()
    assert (output / "adaptive_attempt_metrics.csv").exists()
    request_csv = (output / "adaptive_request_metrics.csv").read_text(encoding="utf-8")
    assert "requestId" in request_csv.splitlines()[0]
    assert "generationTotalTokens" in request_csv.splitlines()[0]


def test_adaptive_plan_cli_contract_and_status_cover_all_request_states(tmp_path, capsys):
    from ctxbench.adaptive.artifacts import adaptive_plan_payload, validate_workflow_manifest
    from ctxbench.commands.plan import plan_command
    from ctxbench.commands.status import status_command

    base = _plan(
        ("request-1", "request-2", "request-3"),
        policy=AdaptiveWorkflowPolicy(quality_slos=(QualitySLO("quality", 0.8),)),
    )
    requests = list(base.requests)
    rejected_candidates = {
        candidate_id: replace(
            invocation,
            candidate=Candidate(
                invocation.candidate.configuration_id, False, invocation.candidate.context_fit,
            ),
        )
        for candidate_id, invocation in requests[2].candidates.items()
    }
    requests[2] = replace(requests[2], candidates=rejected_candidates)
    plan = replace(base, requests=tuple(requests))
    definition_path = tmp_path / "adaptive-definition.json"
    write_json(definition_path, {
        "workflowKind": "adaptive",
        **adaptive_plan_payload(plan),
        "dataset": {"id": "fixture", "version": "1", "materializedPath": str(tmp_path)},
    })
    output_root = tmp_path / "fresh-adaptive"

    assert plan_command(str(definition_path), str(output_root)) == 0
    manifest = validate_workflow_manifest(output_root)
    assert manifest["adaptivePlanVersion"] == 2
    with pytest.raises(ValueError, match="schemaVersion 1.*not supported"):
        from ctxbench.adaptive.artifacts import adaptive_plan_from_payload
        adaptive_plan_from_payload({"schemaVersion": 1})

    _run(
        plan, output_root,
        lambda request, _session: _result(request),
        assessor=QualityAssessor({
            ("request-1", "candidate-a"): 0.9,
            ("request-2", "candidate-a"): 0.2,
            ("request-2", "candidate-b"): 0.2,
        }),
    )
    assert status_command(str(output_root)) == 0
    report = capsys.readouterr().out
    assert "Workflow   : adaptive" in report
    assert "requests" in report and "Rejected" in report
    request_status = next(line.split() for line in report.splitlines() if line.strip().startswith("requests"))
    assert request_status == ["requests", "3", "1", "1", "1", "0", "0"]
    states = [load_json(output_root / "adaptive-records" / f"request-{index}.json")["state"]
              for index in range(1, 4)]
    assert states == ["delivered", "failed", "rejected"]


def test_adaptive_cli_rejects_legacy_manifest_without_migration(tmp_path):
    from ctxbench.adaptive.artifacts import validate_workflow_manifest
    from ctxbench.commands.execute import execute_command

    write_json(tmp_path / "manifest.json", {
        "schemaVersion": 1,
        "workflowKind": "adaptive",
        "adaptiveArtifactVersion": 1,
        "adaptivePlanVersion": 1,
    })
    with pytest.raises(ValueError, match="fresh adaptive plan"):
        validate_workflow_manifest(tmp_path)
    with pytest.raises(ValueError, match="fresh adaptive plan"):
        execute_command(str(tmp_path / "adaptive-plan.json"))


def test_adaptive_plan_schema_rejects_unknown_fields():
    from ctxbench.adaptive.artifacts import adaptive_plan_from_payload, adaptive_plan_payload

    payload = adaptive_plan_payload(_plan())
    payload["workflowGuess"] = "adaptive"
    with pytest.raises(Exception, match="Additional properties are not allowed"):
        adaptive_plan_from_payload(payload)


def test_execute_cli_dispatches_fresh_adaptive_plan_without_trial_specs(tmp_path):
    from ctxbench.benchmark.selectors import RunSelector
    from ctxbench.adaptive.artifacts import write_adaptive_artifacts
    from ctxbench.commands.execute import execute_command
    from ctxbench.commands.export import export_command

    dataset_root = Path(__file__).parent / "fixtures" / "fake_dataset" / "dataset"
    base = _plan()
    original_request = base.requests[0]
    candidate_invocations = {}
    for candidate_id, invocation in original_request.candidates.items():
        execution = replace(
            invocation.execution,
            task_id="task_role",
            instance_id="person-001",
            payload={
                "runtimeRequest": {
                    "task": "What role does Avery Example have?",
                    "provider": "mock",
                    "model_name": "mock",
                    "configuration": {
                        "strategy": "inline", "representation": "json", "surface": "full",
                    },
                    "surface_spec": {"type": "full_context"},
                    "params": {},
                },
                "resultMetadata": {
                    "configurationId": candidate_id,
                    "modelId": "mock",
                    "taskTags": ["synthetic"],
                    "contextBlocks": ["profile"],
                },
            },
        )
        candidate_invocations[candidate_id] = replace(invocation, execution=execution)
    request = replace(
        original_request,
        task_id="task_role",
        instance_id="person-001",
        candidates=candidate_invocations,
    )
    plan = replace(
        base,
        dataset_id="ctxbench/fake-dataset",
        dataset_version="0.1.0",
        requests=(request,),
    )
    dataset = {
        "id": "ctxbench/fake-dataset", "version": "0.1.0",
        "origin": str(dataset_root), "materializedPath": str(dataset_root),
    }
    write_adaptive_artifacts(tmp_path, plan, dataset=dataset)

    with pytest.raises(ValueError, match="--force is not supported for adaptive"):
        execute_command(str(tmp_path / "adaptive-plan.json"), force=True)
    with pytest.raises(ValueError, match="Selectors cannot filter an adaptive workload"):
        execute_command(str(tmp_path / "adaptive-plan.json"), selector=RunSelector(task=("task_role",)))
    assert execute_command(str(tmp_path / "adaptive-plan.json")) == 0
    responses = read_jsonl(tmp_path / "responses.jsonl")
    assert len(responses) == 1
    assert responses[0]["requestId"] == "request-1"
    assert "trialId" not in responses[0]
    assert export_command(str(tmp_path / "evals.jsonl")) == 0
    exported = (tmp_path / "results.csv").read_text(encoding="utf-8").splitlines()
    assert "responseId" in exported[0] and "requestId" in exported[0]
    assert (tmp_path / "results.csv.manifest.json").exists()


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
        "delivery": {
            "candidateId": "candidate-b", "executionId": "request-2-candidate-b",
            "attemptId": future_outcome.attempt_id,
        },
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
