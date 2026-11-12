"""Causal adaptive MAPE-K workflow over the shared execution service."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
import fcntl
from math import isfinite
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Mapping

from ctxbench.dataset.capabilities import RequestFeatureSchema, SignalCapability
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.fs import load_json, write_json

from .calibration_contract import CalibrationArtifact
from .estimator import Estimator, EstimatorDefinition, FeaturePartitionKey, RollingWindowEstimator
from .sensors import (
    MinimumResponseLengthSensor,
    OnlineQualityAssessor,
    QualityObservation,
    ResponseAcceptanceObservation,
    SensorClass,
    SensorCost,
)
from .types import (
    Candidate,
    Decision,
    Observation,
    PerformanceEstimate,
    Provenance,
    RequestFeatures,
    SizeBin,
    TokenUsage,
    validate_candidates,
)

ADAPTIVE_PLAN_VERSION = 2
ADAPTIVE_RECORD_VERSION = 2


@dataclass(frozen=True, slots=True)
class QualitySLO:
    metric_id: str
    minimum_value: float

    def __post_init__(self) -> None:
        if (not self.metric_id or isinstance(self.minimum_value, bool)
                or not isinstance(self.minimum_value, (int, float)) or not isfinite(self.minimum_value)):
            raise ValueError("quality SLO requires a metric and finite minimum")


@dataclass(frozen=True, slots=True)
class AdaptiveWorkflowPolicy:
    """Frozen objectives and admission settings used by every MAPE-K decision."""

    quality_slos: tuple[QualitySLO, ...] = ()
    latency_limit_ms: float | None = None
    token_limit: int | None = None
    minimum_response_length: int = 0
    token_budget: int | None = None
    best_effort_admission: bool = False
    selection_metric: str = "declared_order"

    def __post_init__(self) -> None:
        if len({slo.metric_id for slo in self.quality_slos}) != len(self.quality_slos):
            raise ValueError("quality SLO metric IDs must be unique")
        if self.latency_limit_ms is not None and (
            isinstance(self.latency_limit_ms, bool)
            or not isinstance(self.latency_limit_ms, (int, float))
            or not isfinite(self.latency_limit_ms) or self.latency_limit_ms < 0
        ):
            raise ValueError("latency limit must be finite and nonnegative")
        if self.token_limit is not None and (type(self.token_limit) is not int or self.token_limit < 0):
            raise ValueError("token limit must be a nonnegative integer")
        if type(self.minimum_response_length) is not int or self.minimum_response_length < 0:
            raise ValueError("minimum response length must be nonnegative")
        if type(self.best_effort_admission) is not bool:
            raise ValueError("best_effort_admission must be a boolean")
        if self.token_budget is not None and (type(self.token_budget) is not int or self.token_budget < 0):
            raise ValueError("token budget must be a nonnegative integer")
        if self.selection_metric not in {"declared_order", "latency", "tokens"}:
            raise ValueError("selection_metric must be declared_order, latency, or tokens")


@dataclass(frozen=True, slots=True)
class AdaptiveCandidateInvocation:
    candidate: Candidate
    execution: ExecutionRequest

    def __post_init__(self) -> None:
        if self.execution.candidate_id != self.candidate.configuration_id:
            raise ValueError("execution candidate ID does not match candidate contract")


@dataclass(frozen=True, slots=True)
class AdaptiveWorkloadRequest:
    request_id: str
    sequence_index: int
    task_id: str
    instance_id: str
    features: RequestFeatures
    feature_values: Mapping[str, object]
    candidate_order: tuple[str, ...]
    candidates: Mapping[str, AdaptiveCandidateInvocation]

    def __post_init__(self) -> None:
        if (not self.request_id or not self.task_id or not self.instance_id
                or type(self.sequence_index) is not int or self.sequence_index < 1
                or self.features.sequence_index != self.sequence_index):
            raise ValueError("adaptive request identity or sequence is invalid")
        if len(self.candidate_order) != len(set(self.candidate_order)):
            raise ValueError("candidate order contains duplicates")
        if set(self.candidate_order) != set(self.candidates):
            raise ValueError("candidate order must name every declared request candidate exactly once")
        validate_candidates(tuple(invocation.candidate for invocation in self.candidates.values()))
        for candidate_id, invocation in self.candidates.items():
            if candidate_id != invocation.candidate.configuration_id:
                raise ValueError("candidate map key differs from candidate identity")
            execution = invocation.execution
            if (execution.task_id != self.task_id or execution.instance_id != self.instance_id
                    or execution.trial_id is not None):
                raise ValueError("adaptive execution must match request task/instance and omit trialId")


@dataclass(frozen=True, slots=True)
class AdaptivePlan:
    workflow_id: str
    execution_fingerprint: str
    feature_schema: RequestFeatureSchema
    policy: AdaptiveWorkflowPolicy
    requests: tuple[AdaptiveWorkloadRequest, ...]
    candidate_catalog: tuple[str, ...]
    schema_version: int = ADAPTIVE_PLAN_VERSION
    dataset_id: str | None = None
    dataset_version: str | None = None
    candidate_catalog_fingerprint: str | None = None
    estimator_definition: EstimatorDefinition = field(default_factory=EstimatorDefinition)
    calibration: CalibrationArtifact | None = None

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.execution_fingerprint:
            raise ValueError("adaptive plan requires workflow ID and execution fingerprint")
        if self.schema_version != ADAPTIVE_PLAN_VERSION:
            raise ValueError(f"unsupported adaptive plan schemaVersion {self.schema_version}")
        if not self.requests:
            raise ValueError("adaptive workload must not be empty")
        request_ids = [row.request_id for row in self.requests]
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", request_id) or request_id in {".", ".."}
               for request_id in request_ids):
            raise ValueError("adaptive request IDs must be safe artifact identifiers")
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("adaptive request IDs must be unique, including repeated task occurrences")
        if [row.sequence_index for row in self.requests] != list(range(1, len(self.requests) + 1)):
            raise ValueError("adaptive workload sequence must be contiguous and ordered")
        if len(self.candidate_catalog) != len(set(self.candidate_catalog)):
            raise ValueError("candidate catalog IDs must be unique")
        catalog = set(self.candidate_catalog)
        execution_ids: list[str] = []
        for request in self.requests:
            self.feature_schema.partition_for(dict(request.feature_values))
            if not set(request.candidates).issubset(catalog):
                raise ValueError("request contains a candidate outside the declared catalog")
            for invocation in request.candidates.values():
                execution = invocation.execution
                if (execution.workflow_id != self.workflow_id
                        or execution.execution_fingerprint != self.execution_fingerprint
                        or execution.correlation_id != request.request_id):
                    raise ValueError("execution request identity differs from its adaptive plan")
                execution_ids.append(execution.execution_id)
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("each request/candidate invocation requires a unique executionId")
        if self.calibration is not None:
            if not all((self.dataset_id, self.dataset_version, self.candidate_catalog_fingerprint)):
                raise ValueError("calibration requires dataset and candidate-catalog provenance")
            self.calibration.provenance.validate_for(
                active_request_ids=set(request_ids),
                dataset_id=str(self.dataset_id),
                dataset_version=str(self.dataset_version),
                candidate_catalog_fingerprint=str(self.candidate_catalog_fingerprint),
                feature_schema_id=self.feature_schema.schema_id,
                feature_schema_version=self.feature_schema.version,
                estimator=self.estimator_definition,
            )
            if any(row.configuration_id not in catalog for row in self.calibration.estimates):
                raise ValueError("calibration contains an estimate outside the declared candidate catalog")


@dataclass(frozen=True, slots=True)
class AdaptiveWorkflowOutcome:
    requests: tuple[dict[str, Any], ...]
    delivered: int
    rejected: int
    failed: int


def run_adaptive_workflow(
    plan: AdaptivePlan,
    *,
    root: str | Path,
    service: TrialExecutionService,
    session: ExecutionSession,
    invoke: Callable[[ExecutionRequest, ExecutionSession], dict[str, Any]],
    quality_assessor: OnlineQualityAssessor | None = None,
    estimator: Estimator | None = None,
    retry_uncertain: bool = False,
) -> AdaptiveWorkflowOutcome:
    artifact_root = Path(root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    with _adaptive_lock(artifact_root):
        return _run_adaptive_workflow_locked(
            plan,
            root=artifact_root,
            service=service,
            session=session,
            invoke=invoke,
            quality_assessor=quality_assessor,
            estimator=estimator,
            retry_uncertain=retry_uncertain,
        )


def _run_adaptive_workflow_locked(
    plan: AdaptivePlan,
    *,
    root: str | Path,
    service: TrialExecutionService,
    session: ExecutionSession,
    invoke: Callable[[ExecutionRequest, ExecutionSession], dict[str, Any]],
    quality_assessor: OnlineQualityAssessor | None = None,
    estimator: Estimator | None = None,
    retry_uncertain: bool = False,
) -> AdaptiveWorkflowOutcome:
    """Run requests serially; persist each decision before its execution attempt.

    Existing request records are replayed in workload order. The controller sees calibration
    priors and observations from earlier requests or earlier attempts of the current request only.
    """
    if session.closed:
        raise RuntimeError("adaptive workflow requires an open execution session")
    _validate_assessor(plan.policy, quality_assessor)
    active_estimator = estimator or RollingWindowEstimator(plan.estimator_definition)
    if active_estimator.definition != plan.estimator_definition:
        raise ValueError("runtime estimator differs from the frozen adaptive plan")
    artifact_root = Path(root)
    records_root = artifact_root / "adaptive-records"
    records_root.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    for request in plan.requests:
        path = _record_path(records_root, request.request_id)
        if path.exists():
            record = load_json(path)
            _validate_saved_record(record, plan, request, service)
            existing[request.request_id] = record

    started_at = utc_now_iso()
    delivered = rejected = failed = 0
    provider_invocations = replayed_executions = 0
    results: list[dict[str, Any]] = []
    for request in plan.requests:
        record = existing.get(request.request_id)
        if record is None:
            record = _new_request_record(plan, request)
            write_json(_record_path(records_root, request.request_id), record)
        if record["state"] in {"delivered", "failed", "rejected"}:
            _replay_request_observations(active_estimator, plan, request, record)
            results.append(record)
            delivered += record["state"] == "delivered"
            rejected += record["state"] == "rejected"
            failed += record["state"] == "failed"
            continue

        _replay_request_observations(active_estimator, plan, request, record)
        tried = {row["decision"].get("candidateId") for row in record["attempts"]}
        ordinal = len(record["attempts"]) + 1
        while True:
            if record["attempts"] and record["attempts"][-1].get("monitored"):
                last = record["attempts"][-1]
                if last.get("analysis", {}).get("accepted"):
                    _restore_delivery(record, last, service)
                    write_json(_record_path(records_root, request.request_id), record)
                    break
                if len(tried) >= len(request.candidates):
                    record["state"] = "failed"
                    record["terminalReason"] = "candidate_catalog_exhausted"
                    write_json(_record_path(records_root, request.request_id), record)
                    break
            decision_row = record["attempts"][-1] if record["attempts"] and not record["attempts"][-1].get("monitored") else None
            if decision_row is None:
                decision = _plan_next_candidate(
                    plan, request, active_estimator, tried, record,
                    prior_spend=_spent_tokens_records(results),
                )
                decision, admission = decision
                decision_row = {
                    "decision": _decision_payload(decision, plan, request, ordinal),
                    "executionId": (request.candidates[decision.selected_configuration].execution.execution_id
                                    if decision.selected_configuration else None),
                    "admission": admission,
                    "monitored": False,
                }
                record["attempts"].append(decision_row)
                write_json(_record_path(records_root, request.request_id), record)

            candidate_id = decision_row["decision"].get("candidateId")
            if candidate_id is None:
                record["knowledgeAfter"] = _knowledge_snapshot(plan, active_estimator)
                record["state"] = "rejected"
                record["terminalReason"] = decision_row["decision"].get("reason")
                write_json(_record_path(records_root, request.request_id), record)
                break

            invocation = request.candidates[candidate_id]
            def invoke_with_sensors(execution_request, active_session):
                result = invoke(execution_request, active_session)
                observation, acceptance, quality = _monitor(
                    request, candidate_id, result, plan.policy, quality_assessor,
                )
                return {
                    **result,
                    "_adaptiveSignals": _signals_payload(observation, acceptance, quality),
                }

            outcome = service.execute(
                invocation.execution, session, invoke_with_sensors,
                retry_uncertain=retry_uncertain,
            )
            if outcome.resumed:
                replayed_executions += 1
            else:
                provider_invocations += 1
            signals = outcome.result.get("_adaptiveSignals")
            if not isinstance(signals, dict):
                raise ValueError("completed adaptive execution is missing its persisted observations")
            observation, acceptance, quality = _signals_from_payload(signals)
            decision_row["execution"] = {
                "executionId": outcome.execution_id,
                "attemptId": outcome.attempt_id,
                "status": outcome.status,
                "resumed": outcome.resumed,
            }
            decision_row["observation"] = _observation_payload(observation)
            decision_row["acceptance"] = _json_value(asdict(acceptance))
            decision_row["quality"] = [_json_value(asdict(value)) for value in quality]
            decision_row["analysis"] = _analyze(plan.policy, outcome.result, observation, acceptance, quality)
            decision_row["monitored"] = True
            write_json(_record_path(records_root, request.request_id), record)
            _update_estimator(active_estimator, plan, request, candidate_id, observation)
            record["knowledgeAfter"] = _knowledge_snapshot(plan, active_estimator)
            write_json(_record_path(records_root, request.request_id), record)
            tried.add(candidate_id)
            if decision_row["analysis"]["accepted"]:
                _restore_delivery(record, decision_row, service)
                write_json(_record_path(records_root, request.request_id), record)
                break
            ordinal += 1
            if ordinal > len(request.candidates):
                record["state"] = "failed"
                record["terminalReason"] = "candidate_catalog_exhausted"
                write_json(_record_path(records_root, request.request_id), record)
                break

        results.append(record)
        delivered += record["state"] == "delivered"
        rejected += record["state"] == "rejected"
        failed += record["state"] == "failed"

    lifecycle_path = artifact_root / "adaptive-lifecycle.json"
    lifecycle = load_json(lifecycle_path) if lifecycle_path.exists() else {"schemaVersion": 1, "sessions": []}
    if lifecycle.get("schemaVersion") != 1 or not isinstance(lifecycle.get("sessions"), list):
        raise ValueError("invalid adaptive lifecycle record")
    lifecycle["sessions"].append({"startedAt": started_at, "finishedAt": utc_now_iso(),
                                  "providerInvocations": provider_invocations,
                                  "replayedExecutions": replayed_executions,
                                  "sessionReusedAcrossRequests": provider_invocations > 1})
    write_json(lifecycle_path, lifecycle)
    from .projections import rebuild_adaptive_responses
    rebuild_adaptive_responses(artifact_root, service=service)
    return AdaptiveWorkflowOutcome(tuple(results), delivered, rejected, failed)


def _plan_next_candidate(
    plan: AdaptivePlan,
    request: AdaptiveWorkloadRequest,
    estimator: Estimator,
    tried: set[str],
    record: dict[str, Any],
    *,
    prior_spend: tuple[int, bool],
) -> tuple[Decision, dict[str, Any]]:
    eligible = tuple(
        request.candidates[cid].candidate
        for cid in request.candidate_order
        if cid not in tried and request.candidates[cid].candidate.eligible
    )
    estimates: dict[str, PerformanceEstimate] = {}
    for candidate in eligible:
        estimates[candidate.configuration_id] = estimator.estimate(
            candidate.configuration_id,
            _partition(plan, request),
            plan.calibration.estimate_for(candidate.configuration_id, _partition(plan, request))
            if plan.calibration else None,
        )
    selected: str | None = None
    reason = "candidate_catalog_exhausted"
    current_spend = _spent_tokens(record)
    admission = (prior_spend[0] + current_spend[0], prior_spend[1] or current_spend[1])
    remaining = (None if plan.policy.token_budget is None
                 else max(0, plan.policy.token_budget - admission[0]))
    unknown_spend = admission[1]
    candidates = list(eligible)
    if plan.policy.selection_metric != "declared_order":
        metric = "latency_ms" if plan.policy.selection_metric == "latency" else "total_tokens"
        candidates.sort(key=lambda candidate: (
            getattr(estimates[candidate.configuration_id], metric).value is None,
            getattr(estimates[candidate.configuration_id], metric).value
            if getattr(estimates[candidate.configuration_id], metric).value is not None else float("inf"),
            request.candidate_order.index(candidate.configuration_id),
        ))
    admission_rows = []
    for candidate in candidates:
        estimate = estimates[candidate.configuration_id].total_tokens.value
        candidate_reason = "admission_disabled"
        if plan.policy.token_budget is not None:
            if unknown_spend and not plan.policy.best_effort_admission:
                candidate_reason = "unknown_prior_consumption"
                admission_rows.append({"candidateId": candidate.configuration_id,
                                       "estimatedTokens": estimate, "status": candidate_reason})
                reason = "admission_unknown_prior_consumption"
                continue
            if estimate is None and not plan.policy.best_effort_admission:
                candidate_reason = "unknown_candidate_cost"
                admission_rows.append({"candidateId": candidate.configuration_id,
                                       "estimatedTokens": None, "status": candidate_reason})
                reason = "admission_unknown_candidate_cost"
                continue
            if estimate is not None and remaining is not None and estimate > remaining:
                candidate_reason = "token_budget_exceeded"
                admission_rows.append({"candidateId": candidate.configuration_id,
                                       "estimatedTokens": estimate, "status": candidate_reason})
                reason = "admission_token_budget_exceeded"
                continue
        selected = candidate.configuration_id
        candidate_reason = "admitted"
        admission_rows.append({"candidateId": candidate.configuration_id,
                               "estimatedTokens": estimate, "status": candidate_reason})
        reason = "selected_by_declared_order" if plan.policy.selection_metric == "declared_order" else "selected_by_estimate"
        break
    features = request.features
    decision = Decision(
        sequence_index=features.sequence_index,
        features=features,
        eligible_candidates=tuple(candidate.configuration_id for candidate in eligible),
        estimates=estimates,
        selected_configuration=selected,
        reason=reason,
        probe=False,
        cooldown_active=False,
        candidates=tuple(eligible),
    )
    admission_record = {
        "enabled": plan.policy.token_budget is not None,
        "budgetTokens": plan.policy.token_budget,
        "spentTokensBeforeRequest": admission[0] - current_spend[0],
        "spentTokensEarlierAttempts": current_spend[0],
        "unknownConsumptionBeforeCandidate": admission[1],
        "remainingTokens": remaining,
        "bestEffort": plan.policy.best_effort_admission,
        "candidates": admission_rows,
    }
    return decision, admission_record


def _monitor(request, candidate_id, result, policy, assessor):
    response = result.get("response")
    response_text = response if isinstance(response, str) else str(response or "")
    acceptance = MinimumResponseLengthSensor(policy.minimum_response_length).observe(
        request.request_id, candidate_id, response_text,
    )
    timing = result.get("timing") or {}
    metrics = result.get("metricsSummary") or {}
    duration = timing.get("durationMs")
    if duration is None:
        duration = metrics.get("totalDurationMs")
    duration_available = (not isinstance(duration, bool) and isinstance(duration, (int, float))
                          and isfinite(duration) and duration >= 0)
    duration_provenance = Provenance.MEASURED if duration_available else Provenance.UNAVAILABLE
    total_tokens = metrics.get("totalTokens")
    try:
        token_provenance = Provenance(metrics.get("totalTokensProvenance", "unavailable"))
    except ValueError:
        token_provenance = Provenance.UNAVAILABLE
    token_available = (
        type(total_tokens) is int and total_tokens >= 0
        and token_provenance != Provenance.UNAVAILABLE
    )
    if not token_available:
        token_provenance = Provenance.UNAVAILABLE
    observation = Observation(
        candidate_id,
        request.features.size_bin,
        str(result.get("status", "error")),
        float(duration) if duration_available else None,
        TokenUsage(total_tokens if token_available else None, token_provenance),
        duration_provenance,
    )
    quality: list[QualityObservation] = []
    if assessor is not None:
        capability = assessor.capability
        started = perf_counter()
        try:
            signal = assessor.assess(request.request_id, candidate_id, response_text)
        except Exception:
            signal = None
        assessment_duration = max(0.0, (perf_counter() - started) * 1000)
        valid_signal = isinstance(signal, QualityObservation)
        if valid_signal:
            valid_signal = (
                signal.request_id == request.request_id
                and signal.candidate_id == candidate_id
                and signal.metric_id == capability.metric_id
                and signal.assessor_id == capability.signal_id
                and signal.assessor_version == capability.version
                and signal.sensor_class.value == capability.sensor_class
                and signal.uses_reference_data == capability.uses_reference_data
                and (signal.provenance.value == capability.value_provenance
                     or (signal.provenance == Provenance.UNAVAILABLE and signal.value is None))
                and signal.value_scale == (capability.value_scale or "")
            )
        if not valid_signal:
            signal = QualityObservation(
                request_id=request.request_id,
                candidate_id=candidate_id,
                metric_id=capability.metric_id,
                value=None,
                value_scale=capability.value_scale or "unknown",
                assessor_id=capability.signal_id,
                assessor_version=capability.version,
                sensor_class=SensorClass(capability.sensor_class),
                provenance=Provenance.UNAVAILABLE,
                cost=SensorCost(
                    assessment_duration, Provenance.MEASURED,
                    TokenUsage(None, Provenance.UNAVAILABLE),
                ),
                uses_reference_data=capability.uses_reference_data,
            )
        quality = [signal]
    return observation, acceptance, quality


def _analyze(policy, result, observation, acceptance, quality):
    unmet: list[str] = []
    if result.get("status") != "success":
        unmet.append("execution_success")
    if not acceptance.accepted:
        unmet.append(acceptance.sensor_id)
    if policy.latency_limit_ms is not None:
        duration = observation.end_to_end_duration_ms
        if duration is None or duration > policy.latency_limit_ms:
            unmet.append("latency_slo_unavailable" if duration is None else "latency_slo")
    if policy.token_limit is not None:
        tokens = observation.tokens.value
        if tokens is None or tokens > policy.token_limit:
            unmet.append("token_slo_unavailable" if tokens is None else "token_slo")
    quality_by_metric = {row.metric_id: row for row in quality}
    for slo in policy.quality_slos:
        signal = quality_by_metric.get(slo.metric_id)
        if signal is None or signal.value is None:
            unmet.append(f"quality_unavailable:{slo.metric_id}")
        elif signal.value < slo.minimum_value:
            unmet.append(f"quality_slo:{slo.metric_id}")
    return {"accepted": not unmet, "unmet": unmet,
            "qualitySloStatus": {slo.metric_id: _quality_status(quality_by_metric.get(slo.metric_id), slo.minimum_value)
                                 for slo in policy.quality_slos}}


def _quality_status(observation: QualityObservation | None, minimum: float) -> str:
    if observation is None or observation.value is None:
        return "unavailable"
    return "met" if observation.value >= minimum else "missed"


def _validate_assessor(policy: AdaptiveWorkflowPolicy, assessor: OnlineQualityAssessor | None) -> None:
    if policy.quality_slos and assessor is None:
        raise ValueError("quality SLOs require a declared online quality assessor")
    if assessor is None:
        return
    capability = assessor.capability
    if not isinstance(capability, SignalCapability):
        raise ValueError("online assessor must expose a declared signal capability")
    if policy.quality_slos and {slo.metric_id for slo in policy.quality_slos} != {capability.metric_id}:
        raise ValueError("one online assessor per metric is required for the declared quality SLOs")
    if capability.sensor_class not in {"semantic_proxy", "judge", "oracle"}:
        raise ValueError("online quality assessor capability must declare a quality sensor class")


def _update_estimator(estimator, plan, request, candidate_id, observation):
    estimator.observe(candidate_id, _partition(plan, request), observation)


def _replay_request_observations(estimator, plan, request, record):
    for row in record.get("attempts", []):
        observation = row.get("observation")
        candidate_id = row.get("decision", {}).get("candidateId")
        if not row.get("monitored") or not candidate_id or not isinstance(observation, dict):
            continue
        typed = _observation_from_payload(observation)
        _update_estimator(estimator, plan, request, candidate_id, typed)


def _observation_payload(observation: Observation) -> dict[str, Any]:
    return _json_value(asdict(observation))


def _signals_payload(observation, acceptance, quality) -> dict[str, Any]:
    return {
        "observation": _observation_payload(observation),
        "acceptance": _json_value(asdict(acceptance)),
        "quality": [_json_value(asdict(row)) for row in quality],
    }


def _signals_from_payload(payload):
    observation = _observation_from_payload(payload["observation"])
    acceptance_row = payload["acceptance"]
    cost = acceptance_row["cost"]
    acceptance = ResponseAcceptanceObservation(
        request_id=acceptance_row["request_id"],
        candidate_id=acceptance_row["candidate_id"],
        sensor_id=acceptance_row["sensor_id"],
        sensor_version=acceptance_row["sensor_version"],
        accepted=acceptance_row["accepted"],
        sensor_class=SensorClass(acceptance_row["sensor_class"]),
        provenance=Provenance(acceptance_row["provenance"]),
        cost=SensorCost(
            cost.get("duration_ms"), Provenance(cost["duration_provenance"]),
            TokenUsage(cost["tokens"].get("value"), Provenance(cost["tokens"]["provenance"])),
        ),
    )
    quality = []
    for row in payload.get("quality", []):
        cost = row["cost"]
        quality.append(QualityObservation(
            request_id=row["request_id"], candidate_id=row["candidate_id"],
            metric_id=row["metric_id"], value=row.get("value"), value_scale=row["value_scale"],
            assessor_id=row["assessor_id"], assessor_version=row["assessor_version"],
            sensor_class=SensorClass(row["sensor_class"]), provenance=Provenance(row["provenance"]),
            cost=SensorCost(
                cost.get("duration_ms"), Provenance(cost["duration_provenance"]),
                TokenUsage(cost["tokens"].get("value"), Provenance(cost["tokens"]["provenance"])),
            ),
            uses_reference_data=row.get("uses_reference_data", False),
        ))
    return observation, acceptance, quality


def _observation_from_payload(payload: dict[str, Any]) -> Observation:
    token = payload["tokens"]
    return Observation(
        configuration_id=payload["configuration_id"],
        size_bin=SizeBin(payload["size_bin"]) if payload.get("size_bin") is not None else None,
        status=payload["status"], end_to_end_duration_ms=payload.get("end_to_end_duration_ms"),
        tokens=TokenUsage(token.get("value"), Provenance(token["provenance"])),
        duration_provenance=Provenance(payload["duration_provenance"]),
    )


def _decision_payload(decision: Decision, plan: AdaptivePlan, request: AdaptiveWorkloadRequest, ordinal: int) -> dict[str, Any]:
    return {
        "decisionId": f"{request.request_id}:decision:{ordinal:04d}",
        "requestId": request.request_id,
        "sequenceIndex": request.sequence_index,
        "attemptOrdinal": ordinal,
        "candidateId": decision.selected_configuration,
        "eligibleCandidates": list(decision.eligible_candidates),
        "reason": decision.reason,
        "estimates": {cid: _json_value(asdict(value)) for cid, value in decision.estimates.items()},
        "features": _json_value(asdict(request.features)),
        "featureValues": _json_value(dict(request.feature_values)),
        "partition": _json_value(asdict(_partition(plan, request))),
        "createdAt": utc_now_iso(),
    }


def _knowledge_snapshot(plan: AdaptivePlan, estimator: Estimator) -> dict[str, Any]:
    partitions = {_partition(plan, request) for request in plan.requests}
    snapshot = []
    for partition in sorted(partitions, key=lambda value: (value.schema_id, value.schema_version, value.values)):
        for candidate_id in plan.candidate_catalog:
            estimate = estimator.estimate(
                candidate_id,
                partition,
                plan.calibration.estimate_for(candidate_id, partition) if plan.calibration else None,
            )
            snapshot.append({
                "candidateId": candidate_id,
                "partition": _json_value(asdict(partition)),
                "estimate": _json_value(asdict(estimate)),
            })
    return {"estimatorId": estimator.definition.estimator_id,
            "estimatorVersion": estimator.definition.version,
            "windowSize": estimator.definition.window_size,
            "minimumObservations": estimator.definition.minimum_observations,
            "estimates": snapshot}


def _partition(plan: AdaptivePlan, request: AdaptiveWorkloadRequest) -> FeaturePartitionKey:
    partition = FeaturePartitionKey.from_features(plan.feature_schema, dict(request.feature_values))
    if partition is None:
        return FeaturePartitionKey(plan.feature_schema.schema_id, plan.feature_schema.version, ())
    return partition


def _new_request_record(plan: AdaptivePlan, request: AdaptiveWorkloadRequest) -> dict[str, Any]:
    return {
        "schemaVersion": ADAPTIVE_RECORD_VERSION,
        "requestId": request.request_id,
        "sequenceIndex": request.sequence_index,
        "executionFingerprint": plan.execution_fingerprint,
        "taskId": request.task_id,
        "instanceId": request.instance_id,
        "state": "started",
        "attempts": [],
        "delivery": None,
    }


def _validate_saved_record(
    record: Any, plan: AdaptivePlan, request: AdaptiveWorkloadRequest,
    service: TrialExecutionService,
) -> None:
    if (not isinstance(record, dict) or record.get("schemaVersion") != ADAPTIVE_RECORD_VERSION
            or record.get("requestId") != request.request_id
            or record.get("sequenceIndex") != request.sequence_index
            or record.get("executionFingerprint") != plan.execution_fingerprint
            or record.get("taskId") != request.task_id or record.get("instanceId") != request.instance_id
            or record.get("state") not in {"started", "delivered", "failed", "rejected"}
            or not isinstance(record.get("attempts"), list)):
        raise ValueError(f"adaptive request ledger mismatch for {request.request_id}")
    if len(record["attempts"]) > len(request.candidates):
        raise ValueError(f"adaptive request has excess attempts: {request.request_id}")
    if record["state"] == "delivered" and not isinstance(record.get("delivery"), dict):
        raise ValueError(f"delivered request has no delivery record: {request.request_id}")
    if record["state"] in {"failed", "rejected"} and record.get("delivery") is not None:
        raise ValueError(f"undelivered request has a delivery record: {request.request_id}")
    seen_candidates: set[str] = set()
    for index, row in enumerate(record["attempts"], 1):
        if not isinstance(row, dict) or not isinstance(row.get("decision"), dict):
            raise ValueError(f"invalid adaptive attempt record for {request.request_id}")
        decision = row.get("decision", {})
        if (decision.get("decisionId") != f"{request.request_id}:decision:{index:04d}"
                or decision.get("sequenceIndex") != request.sequence_index
                or decision.get("requestId") != request.request_id):
            raise ValueError(f"adaptive decision identity mismatch for {request.request_id}")
        candidate_id = decision.get("candidateId")
        if candidate_id is not None and candidate_id not in request.candidates:
            raise ValueError(f"adaptive decision selected undeclared candidate {candidate_id}")
        if candidate_id is not None and candidate_id in seen_candidates:
            raise ValueError(f"adaptive request repeats candidate decision {candidate_id}")
        if candidate_id is not None:
            seen_candidates.add(candidate_id)
        expected_execution = request.candidates[candidate_id].execution.execution_id if candidate_id else None
        if row.get("executionId") != expected_execution:
            raise ValueError(f"adaptive decision execution identity mismatch for {request.request_id}")
        execution_meta = row.get("execution")
        if row.get("monitored") is True and execution_meta is None:
            raise ValueError(f"monitored adaptive attempt has no execution link for {request.request_id}")
        if execution_meta is not None:
            if expected_execution is None:
                raise ValueError(f"adaptive admission decision has an execution link for {request.request_id}")
            if not isinstance(execution_meta, dict) or execution_meta.get("executionId") != expected_execution:
                raise ValueError(f"adaptive execution link mismatch for {request.request_id}")
            attempts = service.attempts(expected_execution)
            matching = next((attempt for attempt in attempts
                             if attempt.get("attemptId") == execution_meta.get("attemptId")), None)
            if matching is None or matching.get("state") not in {"succeeded", "failed"}:
                raise ValueError(f"adaptive execution outcome is missing for {request.request_id}")
            if row.get("monitored") is True:
                signals = matching.get("result", {}).get("_adaptiveSignals")
                if not isinstance(signals, dict) or signals.get("observation") != row.get("observation"):
                    raise ValueError(f"adaptive observation differs from execution record for {request.request_id}")


def _spent_tokens(record: dict[str, Any]) -> tuple[int, bool]:
    total, unknown = 0, False
    for row in record.get("attempts", []):
        observation = row.get("observation")
        token = observation.get("tokens", {}) if isinstance(observation, dict) else {}
        value = token.get("value")
        if isinstance(value, (int, float)):
            total += int(value)
        elif row.get("monitored"):
            unknown = True
    return total, unknown


def _spent_tokens_records(records: list[dict[str, Any]]) -> tuple[int, bool]:
    total, unknown = 0, False
    for record in records:
        spent, incomplete = _spent_tokens(record)
        total += spent
        unknown = unknown or incomplete
    return total, unknown


def _restore_delivery(record, attempt, service):
    candidate_id = attempt["decision"].get("candidateId")
    execution_id = attempt.get("executionId")
    outcomes = service.attempts(execution_id) if execution_id else []
    if not outcomes:
        raise ValueError(f"missing execution outcome for delivered request {record['requestId']}")
    attempt_id = (attempt.get("execution") or {}).get("attemptId")
    execution = next((row for row in outcomes if row.get("attemptId") == attempt_id), None)
    if execution is None or execution.get("state") != "succeeded":
        raise ValueError(f"delivery does not reference a successful execution for {record['requestId']}")
    record["state"] = "delivered"
    record["delivery"] = {
        "candidateId": candidate_id,
        "executionId": execution_id,
        "attemptId": attempt_id,
    }
    record["terminalReason"] = "all_declared_acceptance_and_quality_slos_met"


def _record_path(root: Path, request_id: str) -> Path:
    return root / f"{request_id}.json"


@contextmanager
def _adaptive_lock(root: Path):
    lock_path = root / ".adaptive.lock"
    with lock_path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another adaptive workflow holds {lock_path}.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _json_value(value: Any) -> Any:
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
