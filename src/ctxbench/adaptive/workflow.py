"""Adaptive workflow planning and durable one-decision/one-attempt execution."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
from inspect import signature
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Mapping, Sequence

from ctxbench.adaptive.artifacts import (
    ADAPTIVE_ARTIFACT_VERSION, adaptive_plan_from_payload, adaptive_plan_payload,
    validate_workflow_manifest, write_adaptive_artifacts,
)
from ctxbench.adaptive.definition import AdaptiveExperiment, load_adaptive_experiment
from ctxbench.adaptive.invocation import build_execution_request
from ctxbench.adaptive.plan import (
    ADAPTIVE_PLAN_VERSION, AdaptivePlan, CandidateSpec, PlannedRequest, WindowSpec,
)
from ctxbench.adaptive.policy import (
    CandidateRef, Decision, PolicyContractError, resolve_policy,
    validate_decision, verify_policy,
)
from ctxbench.adaptive.sensors import (
    AssessmentInput, assess_quality, resolve_quality_assessors, skipped_assessment_cost, skipped_quality,
)
from ctxbench.adaptive.signals import SignalValue, extract_signals
from ctxbench.adaptive.state import Observation, WindowSystemState, validate_reading_request
from ctxbench.core.errors import CapabilityUnavailableError, InvalidDefinitionError
from ctxbench.runtime.disturbances import build_runtime_disturbances
from ctxbench.core.fingerprint import digest
from ctxbench.core.provenance import Provenance
from ctxbench.core.surfaces import parse_surface
from ctxbench.core.workflow import (
    ExecuteOptions, ExecuteOutcome, MetricsOptions, MetricsOutcome, PlanOutcome, RunStatus,
    StatusGroupingError,
)
from ctxbench.dataset.cache import DatasetCache
from ctxbench.dataset.provenance import DatasetProvenance
from ctxbench.dataset.resolver import DatasetResolver
from ctxbench.dataset.validation import validate_package
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.env import resolve_plan_params
from ctxbench.util.fs import load_json, write_json


ADAPTIVE_RECORD_VERSION = 3
_TERMINAL = {"delivered", "failed"}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class AdaptiveWorkflow:
    """Adaptive run implementation behind the shared workflow contract."""

    kind = "adaptive"
    definition_types = (AdaptiveExperiment,)

    def load_definition(self, source, *, logger=None) -> AdaptiveExperiment:
        del logger
        return load_adaptive_experiment(source)   # accepts a path, a mapping, or an experiment object

    def plan(self, definition: AdaptiveExperiment, *, output: Path | None, cache_dir: Path | None = None,
             plugin_paths: Sequence[Path] = (), logger=None, progress: bool = False) -> PlanOutcome:
        del progress
        from ctxbench.adapters.registry import get_default_registry
        from ctxbench.dataset.errors import AdapterUnavailableError

        logger = logger
        cache = DatasetCache(cache_dir=cache_dir)
        resolved = DatasetResolver().resolve_for_planning(definition.dataset, cache)
        try:
            package = get_default_registry().resolve(resolved.adapter_ref)
        except AdapterUnavailableError:
            package = resolved.package
        validate_package(package)
        report = package.capability_report()
        provenance = DatasetProvenance(
            id=package.identity(), version=package.version(), origin=package.origin(),
            resolved_revision=report.resolved_revision, content_hash=report.content_hash,
            materialized_path=report.materialized_path,
        )
        try:
            plan = self._build_plan(definition, package, provenance, plugin_paths=plugin_paths, logger=logger)
        except (CapabilityUnavailableError, InvalidDefinitionError):
            raise
        except ValueError as exc:
            raise InvalidDefinitionError(str(exc)) from exc
        target = Path(output).expanduser().resolve() if output else definition.base_dir / definition.output
        if target.exists() and any(target.iterdir()):
            raise ValueError("Adaptive planning requires a fresh output directory; create a fresh plan.")
        write_adaptive_artifacts(target, plan)
        return PlanOutcome(plan.workflow_id, self.kind, target, target / "adaptive-plan.json", len(plan.requests),
                           f"Planned {len(plan.requests)} adaptive request(s) → {target / 'adaptive-plan.json'}")

    def _build_plan(self, definition: AdaptiveExperiment, package, provenance: DatasetProvenance, *,
                    plugin_paths: Sequence[Path], logger) -> AdaptivePlan:
        candidate_specs: list[CandidateSpec] = []
        for candidate_id, declaration in definition.candidates.items():
            model_id = declaration["model"]
            config_id = declaration["configuration"]
            if model_id not in definition.models:
                raise ValueError(f"Unknown model reference in candidates.{candidate_id}: {model_id}")
            if config_id not in definition.configurations:
                raise ValueError(f"Unknown configuration reference in candidates.{candidate_id}: {config_id}")
            model = definition.models[model_id]
            config = definition.configurations[config_id]
            surface_id = config["surface"]
            if surface_id not in definition.surfaces:
                raise ValueError(f"Unknown surface reference in configurations.{config_id}: {surface_id}")
            surface = parse_surface(dict(definition.surfaces[surface_id]))
            package.resolve_surface(surface)
            params = resolve_plan_params({**definition.execution_options, **dict(model.get("modelParams") or {})})
            _check_strategy_capability(package, candidate_id, config["strategy"], surface, params)
            candidate_specs.append(CandidateSpec(
                candidate_id=candidate_id, model_id=model_id, provider=model["provider"],
                model_name=model["name"], model_params=params, configuration_id=config_id,
                configuration={"strategy": config["strategy"], "representation": config["representation"],
                               "surface": config["surface"]},
                surface_spec=surface.model_dump(mode="json"),
                execution_options={}, labels=dict(declaration.get("labels") or {}),
            ))

        candidate_ids = {candidate.candidate_id for candidate in candidate_specs}
        _validate_disturbances(definition.disturbances, candidate_specs, len(definition.workload))
        policy_decl = definition.policy
        policy_ref, policy = resolve_policy(
            str(policy_decl["ref"]), dict(policy_decl.get("params") or {}), base_dir=definition.base_dir,
            plugin_paths=plugin_paths, sources=tuple(policy_decl.get("sources") or ()),
        )
        _validate_policy_targets(policy, candidate_ids)
        resolved_assessors = resolve_quality_assessors(
            definition.signals, package, plugin_paths=plugin_paths,
        )
        resolved_signals = tuple(row.signal for row in resolved_assessors)
        _validate_policy_readings(policy, resolved_signals)

        requests: list[PlannedRequest] = []
        request_ids: set[str] = set()
        for index, workload_item in enumerate(definition.workload, start=1):
            request_id = workload_item.request_id or f"r-{index:06d}"
            if not _REQUEST_ID.fullmatch(request_id) or request_id in {".", ".."}:
                raise ValueError(f"Invalid requestId: {request_id!r}")
            if request_id in request_ids:
                raise ValueError(f"Duplicate requestId: {request_id}")
            request_ids.add(request_id)
            if workload_item.task_id not in package.list_task_ids():
                raise ValueError(f"Unknown taskId in workload request {request_id}: {workload_item.task_id}")
            if workload_item.instance_id not in package.list_instance_ids():
                raise ValueError(f"Unknown instanceId in workload request {request_id}: {workload_item.instance_id}")
            task = package.get_task(workload_item.task_id)
            task_instance = package.get_task_instance(workload_item.instance_id, workload_item.task_id)
            instance_params = task_instance.get("parameters", {}) if isinstance(task_instance, dict) else {}
            parameters = {**dict(definition.task_params),
                          **(instance_params if isinstance(instance_params, dict) else {})}
            from ctxbench.dataset.tasks import render_task_template
            statement = render_task_template(task.statement, parameters,
                on_warning=(lambda message, **fields: logger.warn("PLAN", "task.template.warning", message, **fields))
                if logger is not None else None,
                task_id=workload_item.task_id, instance_id=workload_item.instance_id)
            requests.append(PlannedRequest(
                request_id=request_id, sequence_index=index, task_id=workload_item.task_id,
                instance_id=workload_item.instance_id, task_statement=statement,
                task_template=task.statement, parameters=parameters,
                task_tags=tuple(task.tags), validation_type=task.validation_type,
                validation_config=dict(task.validation_config), context_blocks=tuple(task.context_blocks),
                labels=dict(workload_item.labels),
            ))
        return AdaptivePlan(
            workflow_id=definition.id, seed=definition.seed, labels=dict(definition.labels),
            candidates=tuple(candidate_specs), requests=tuple(requests),
            workload_source={"kind": "explicit", "spec": {"requests": [
                {"requestId": row.request_id, "taskId": row.task_id, "instanceId": row.instance_id,
                 "labels": dict(row.labels)} for row in requests]},
                "poolDigest": digest([(row.task_id, row.instance_id) for row in requests])},
            policy=policy_ref, window=WindowSpec(definition.window["requests"], definition.window.get("mode", "sliding")),
            acceptance={"minimumResponseLength": definition.acceptance.get("minimumResponseLength", 0)},
            signals=resolved_signals, goals=definition.goals, disturbances=definition.disturbances,
            evaluation=definition.evaluation or {"enabled": False, "judges": []}, trace=definition.trace,
            allow_mixed_models=definition.allow_mixed_models, dataset=provenance,
            resolved_definition=definition.resolved_definition,
        )

    def execute(self, root: Path, *, options: ExecuteOptions, logger=None) -> ExecuteOutcome:
        from ctxbench.ai.engine import Engine
        from ctxbench.adaptive.runtime_adapter import invoke_adaptive_execution, resolve_adaptive_dataset
        from ctxbench.util.logging import PhaseLogger

        root = Path(root).resolve()
        if options.force:
            raise ValueError("--force is not supported for adaptive workflows; create a fresh plan and output directory.")
        selector = options.selector
        if selector is not None and any(getattr(selector, name) for name in selector.__dataclass_fields__):
            raise ValueError("Selectors cannot filter an adaptive workload because decisions require its frozen order.")
        manifest = validate_workflow_manifest(root, execution=True, plugin_paths=options.plugin_paths)
        plan = adaptive_plan_from_payload(load_json(root / "adaptive-plan.json"), dataset=manifest["dataset"])
        plan = replace(plan, execution_fingerprint=manifest["executionFingerprint"])
        dataset = resolve_adaptive_dataset(manifest["dataset"])
        assessors = resolve_quality_assessors(
            plan.signals, dataset, plugin_paths=options.plugin_paths, expected=True,
        )
        requests_by_id = {row.request_id: row for row in plan.requests}
        active_logger = logger or PhaseLogger()
        service = TrialExecutionService(root)
        engine = Engine(event_logger=lambda event, message, fields: active_logger.event(
            str(fields.pop("level", "INFO")), str(fields.pop("phase", "EXECUTE")), event, message, **fields
        ))

        def invoke(request, session):
            metadata = dict(request.payload["resultMetadata"])
            metadata.setdefault("dataset", manifest["dataset"])
            invocation = replace(request, payload={
                **request.payload, "resultMetadata": metadata,
                "traceOptions": dict(plan.trace),
            })
            planned_request = requests_by_id[invocation.execution_id]
            interceptors, applied_effects = build_runtime_disturbances(
                plan.disturbances, component_sequence=planned_request.sequence_index,
                candidate_id=invocation.candidate_id,
            )
            result = invoke_adaptive_execution(
                invocation, session, dataset=dataset, trace_options=dict(plan.trace),
                runtime_interceptors=interceptors,
            )
            response = result.get("response")
            response_text = response if isinstance(response, str) else str(response or "")
            quality_values: dict[str, dict[str, Any]] = {}
            assessor_cost: list[dict[str, Any]] = []
            succeeded = result.get("status") == "success"
            for resolved_assessor in assessors:
                if not succeeded:
                    # A failed attempt has no answer to assess. Its quality is unavailable, not zero,
                    # so quality readings never mix failures with poor answers; failure has its own
                    # failed.<category> signals.
                    quality_values[str(resolved_assessor.signal["id"])] = skipped_quality(resolved_assessor)
                    assessor_cost.append(skipped_assessment_cost(resolved_assessor))
                    continue
                observation, cost = assess_quality(
                    resolved_assessor,
                    AssessmentInput(
                        request_id=planned_request.request_id, task_id=planned_request.task_id,
                        instance_id=planned_request.instance_id, candidate_id=invocation.candidate_id,
                        response=response_text,
                    ),
                )
                quality_values[str(resolved_assessor.signal["id"])] = {
                    "value": observation.value,
                    "provenance": observation.provenance.value,
                    "unit": observation.value_scale,
                }
                assessor_cost.append(cost)
            result["_runtimeQuality"] = quality_values
            result["_runtimeAssessorCost"] = assessor_cost
            return {**result, "_runtimeDisturbances": applied_effects()}

        with ExecutionSession(engine) as session:
            outcome = run_adaptive_workflow(
                plan, root=root, service=service, session=session, invoke=invoke,
                retry_uncertain=options.retry_uncertain, plugin_paths=options.plugin_paths,
            )
        summary = (f"Adaptive requests: {outcome.counts['delivered']} delivered, "
                   f"{outcome.counts['failed']} failed.")
        return ExecuteOutcome(plan.workflow_id, self.kind, outcome.counts, summary)

    def prepare_responses(self, root: Path) -> Mapping[str, Any]:
        manifest = validate_workflow_manifest(root)
        from ctxbench.adaptive.projections import rebuild_adaptive_responses
        rebuild_adaptive_responses(root)
        return manifest

    def responses(self, root: Path):
        from ctxbench.util.jsonl import read_jsonl
        yield from read_jsonl(Path(root) / "responses.jsonl")

    def requests(self, root: Path):
        plan = self._plan(root)
        records = _load_request_records(Path(root))
        for request in plan.requests:
            yield records.get(request.request_id) or {
                "requestId": request.request_id, "sequenceIndex": request.sequence_index,
                "taskId": request.task_id, "instanceId": request.instance_id, "state": "pending",
            }

    def attempts(self, root: Path):
        service = TrialExecutionService(Path(root))
        for request in self._plan(root).requests:
            yield from service.attempts(request.request_id)

    def status(self, root: Path, *, by: str | None = None) -> RunStatus:
        root = Path(root)
        manifest = validate_workflow_manifest(root)
        plan = self._plan(root, manifest=manifest)
        records = _load_request_records(root)
        counts = {state: sum(record.get("state") == state for record in records.values())
                  for state in ("delivered", "failed", "started")}
        counts.update({"planned": len(plan.requests), "pending": len(plan.requests) - len(records)})
        counts["attempts"] = sum(len(row.get("attempts", [])) for row in records.values())
        lines = [f"Experiment : {manifest['experimentId']}", f"Directory  : {root}", "Workflow   : adaptive", "",
                 "Requests: " + ", ".join(f"{key}={value}" for key, value in counts.items())]
        if by in {"task", "instance", "candidate"}:
            groups: dict[str, dict[str, int]] = {}
            for request in plan.requests:
                record = records.get(request.request_id, {})
                if by == "candidate":   # the candidate chosen by the request's decision, if any
                    attempts = record.get("attempts") or [{}]
                    value = (attempts[0].get("decision") or {}).get("candidateId")
                else:
                    value = getattr(request, f"{by}_id")
                bucket = groups.setdefault(str(value or "<undecided>"),
                                           {"total": 0, "delivered": 0, "failed": 0, "pending": 0})
                state = record.get("state")
                bucket["total"] += 1
                bucket["delivered"] += state == "delivered"
                bucket["failed"] += state == "failed"
                bucket["pending"] += state not in _TERMINAL
            lines.append(f"\n{by:<24} {'Total':>8} {'Delivered':>10} {'Failed':>8} {'Pending':>8}")
            for label, row in sorted(groups.items()):
                lines.append(f"{label:<24} {row['total']:>8} {row['delivered']:>10} {row['failed']:>8} {row['pending']:>8}")
        elif by is not None:
            raise StatusGroupingError("Adaptive status --by supports task, instance, or candidate.", lines)
        return RunStatus(plan.workflow_id, self.kind, root, counts, tuple(lines))

    def metric_tables(self, root: Path):
        from ctxbench.metrics.adaptive import build_adaptive_metrics
        requests, attempts = build_adaptive_metrics(root)
        return {"requests": requests, "attempts": attempts}

    def write_metrics(self, roots: Sequence[str], *, options: MetricsOptions, logger=None) -> MetricsOutcome:
        del logger
        if len(roots) != 1:
            raise ValueError("Adaptive metrics accept exactly one run directory.")
        source, output_dir = Path(roots[0]), options.output_dir
        validate_workflow_manifest(source)
        from ctxbench.metrics.adaptive import build_adaptive_metrics
        requests, attempts = build_adaptive_metrics(source)
        if output_dir.exists() and any(output_dir.iterdir()):
            if not options.force:
                raise ValueError(f"Output directory exists and is non-empty: {output_dir}. Use --force to replace it.")
            import shutil
            shutil.rmtree(output_dir)
        from ctxbench.metrics.adaptive import write_adaptive_metrics
        write_adaptive_metrics(output_dir, requests, attempts)
        request_states = {state: sum(row.get("state") == state for row in requests)
                          for state in ("delivered", "failed", "started")}
        manifest = load_json(source / "manifest.json")
        write_json(output_dir / "metrics-manifest.json", {
            "schemaVersion": "4.0-adaptive", "workflowKind": self.kind,
            "inputDirectory": str(source), "requestCount": len(requests), "attemptCount": len(attempts),
            "privileged": bool(manifest.get("privileged")),
            "requestStates": request_states,
            "outputs": ["adaptive_request_metrics.csv", "adaptive_attempt_metrics.csv"],
        })
        return MetricsOutcome(self.kind, output_dir, {"requests": len(requests), "attempts": len(attempts)},
                              f"Wrote adaptive metrics to {output_dir}")

    def _plan(self, root: Path, *, manifest=None) -> AdaptivePlan:
        manifest = manifest or validate_workflow_manifest(root)
        plan = adaptive_plan_from_payload(load_json(Path(root) / "adaptive-plan.json"), dataset=manifest["dataset"])
        return replace(plan, execution_fingerprint=manifest["executionFingerprint"])


@dataclass(frozen=True, slots=True)
class AdaptiveWorkflowOutcome:
    counts: Mapping[str, int]


def run_adaptive_workflow(plan: AdaptivePlan, *, root: str | Path, service: TrialExecutionService,
                          session: ExecutionSession,
                          invoke,
                          retry_uncertain: bool = False,
                          plugin_paths: Sequence[str | Path] = ()) -> AdaptiveWorkflowOutcome:
    root = Path(root)
    with _adaptive_lock(root):
        records_root = root / "adaptive-records"
        records_root.mkdir(parents=True, exist_ok=True)
        records = _load_request_records(root)
        observations: list[Observation] = []
        memo: Mapping[str, Any] | None = None
        counts = {"delivered": 0, "failed": 0, "started": 0}
        session_started_at = utc_now_iso()
        provider_invocations = replayed_executions = 0
        for request in plan.requests:
            record = records.get(request.request_id)
            interrupted = record is not None and record.get("state") == "started"
            if record is None:
                record = _new_request_record(plan, request)
                write_json(_record_path(records_root, request.request_id), record)
            else:
                _validate_saved_record(record, plan, request)
            attempt = record["attempts"][0] if record["attempts"] else None
            decision_payload = attempt.get("decision") if attempt else None
            if record.get("state") in _TERMINAL:
                _append_observation(observations, record)
                memo = (decision_payload or {}).get("memo")
                counts[record["state"]] += 1
                continue

            started = perf_counter()
            if attempt is None:
                current_reference, policy = resolve_policy(
                    plan.policy.ref, plan.policy.params,
                    plugin_paths=plugin_paths, sources=plan.policy.sources,
                )
                if current_reference.source_digest != plan.policy.source_digest:
                    raise PolicyContractError("Policy source changed since planning; create a fresh adaptive plan.")
                candidates = tuple(CandidateRef(item.candidate_id, item.labels) for item in plan.candidates)
                state = WindowSystemState(
                    decision_index=request.sequence_index, observations=observations, memo=memo,
                    seed=plan.seed, decision_id=f"{request.request_id}:d1", default_window=plan.window,
                    candidate_ids=[item.candidate_id for item in plan.candidates],
                    declared_signals=plan.signals,
                )
                try:
                    decision = validate_decision(policy.decide(candidates, state),
                                                 {row.candidate_id for row in plan.candidates})
                except PolicyContractError:
                    raise
                except Exception as exc:
                    raise PolicyContractError(f"Policy decision failed: {exc}") from exc
                candidate_id = decision.candidate_id
                attempt = {
                    "ordinal": 1,
                    "decision": {
                        "decisionId": f"{request.request_id}:d1", "decisionIndex": request.sequence_index,
                        "policy": {"id": plan.policy.policy_id, "version": plan.policy.version},
                        "candidateId": candidate_id, "reason": decision.reason,
                        "memo": dict(decision.memo) if decision.memo is not None else None,
                        "readings": [dict(item) for item in state.reading_audit], "createdAt": utc_now_iso(),
                    },
                    "executionId": request.request_id,
                }
                record["attempts"].append(attempt)
                decision_payload = attempt["decision"]
                write_json(_record_path(records_root, request.request_id), record)
            else:
                candidate_id = decision_payload["candidateId"]
                decision = Decision(candidate_id, decision_payload["reason"], decision_payload.get("memo"))

            candidate = next(item for item in plan.candidates if item.candidate_id == candidate_id)
            execution_request = build_execution_request(plan, request, candidate,
                                                        _load_manifest_fingerprint(root))

            def invoke_with_acceptance(active_request: ExecutionRequest, active_session: ExecutionSession):
                result = invoke(active_request, active_session)
                response = result.get("response")
                response_text = response if isinstance(response, str) else str(response or "")
                accepted = result.get("status") == "success" and len(response_text.strip()) >= int(
                    plan.acceptance.get("minimumResponseLength", 0))
                signal_values, known_subtotals, failure_category = extract_signals(result, accepted=accepted)
                disturbances = result.pop("_runtimeDisturbances", [])
                quality_values = result.pop("_runtimeQuality", {})
                assessor_cost = result.pop("_runtimeAssessorCost", [])
                for name, raw in quality_values.items():
                    signal_values[name] = SignalValue(
                        raw.get("value"), Provenance(raw["provenance"]), str(raw["unit"]),
                    )
                adaptive_signals = {
                    "signals": {name: value.to_dict() for name, value in signal_values.items()},
                    "knownSubtotals": known_subtotals,
                    "failureCategory": failure_category,
                    "accepted": accepted,
                    "disturbances": disturbances,
                    "assessorCost": assessor_cost,
                }
                return {**result, "_adaptiveSignals": adaptive_signals}

            outcome = service.execute(execution_request, session, invoke_with_acceptance,
                                      retry_uncertain=retry_uncertain)
            if outcome.resumed:
                replayed_executions += 1
            else:
                provider_invocations += 1
            result = outcome.result
            response = result.get("response")
            response_text = response if isinstance(response, str) else str(response or "")
            runtime_signals = result.get("_adaptiveSignals")
            runtime_signals = runtime_signals if isinstance(runtime_signals, Mapping) else {}
            accepted = bool(runtime_signals.get(
                "accepted", result.get("status") == "success" and
                len(response_text.strip()) >= int(plan.acceptance.get("minimumResponseLength", 0))))
            status = "success" if result.get("status") == "success" else "error"
            recorded_signals = runtime_signals.get("signals")
            if not isinstance(recorded_signals, Mapping):
                raise ValueError("Completed adaptive execution is missing its persisted signal observation")
            failure_category = runtime_signals.get("failureCategory")
            terminal_reason = "delivered" if accepted else (
                "response_too_short" if status == "success" else "attempt_failed")
            attempt["execution"] = {"attemptId": outcome.attempt_id, "status": outcome.status,
                                    "resumed": outcome.resumed}
            attempt["observation"] = {"status": status,
                                      "signals": dict(recorded_signals),
                                      "knownSubtotals": dict(runtime_signals.get("knownSubtotals") or {}),
                                      "failureCategory": failure_category, "accepted": accepted}
            attempt["disturbances"] = list(runtime_signals.get("disturbances") or [])
            attempt["assessorCost"] = list(runtime_signals.get("assessorCost") or [])
            record["state"] = "delivered" if accepted else "failed"
            record["terminalReason"] = terminal_reason
            record["requestDurationMs"] = max(0, int((perf_counter() - started) * 1000))
            record["requestDurationProvenance"] = "measured"
            record["interrupted"] = bool(interrupted or outcome.resumed)
            record["delivery"] = ({"candidateId": candidate_id, "executionId": outcome.execution_id,
                                   "attemptId": outcome.attempt_id} if accepted else None)
            write_json(_record_path(records_root, request.request_id), record)
            _append_observation(observations, record)
            memo = decision_payload.get("memo")
            counts[record["state"]] += 1
        lifecycle_path = root / "adaptive-lifecycle.json"
        lifecycle = load_json(lifecycle_path) if lifecycle_path.exists() else {"schemaVersion": 1, "sessions": []}
        lifecycle["sessions"].append({"startedAt": session_started_at, "finishedAt": utc_now_iso(),
                                      "providerInvocations": provider_invocations,
                                      "replayedExecutions": replayed_executions})
        write_json(lifecycle_path, lifecycle)
        from ctxbench.adaptive.projections import rebuild_adaptive_responses
        rebuild_adaptive_responses(root, service=service)
        return AdaptiveWorkflowOutcome(counts)


def _new_request_record(plan: AdaptivePlan, request: PlannedRequest) -> dict[str, Any]:
    return {
        "schemaVersion": ADAPTIVE_RECORD_VERSION, "requestId": request.request_id,
        "sequenceIndex": request.sequence_index, "executionFingerprint": _load_manifest_fingerprint_from_plan(plan),
        "taskId": request.task_id, "instanceId": request.instance_id, "labels": dict(request.labels),
        "state": "started", "terminalReason": None, "requestDurationMs": None,
        "requestDurationProvenance": "unavailable", "interrupted": False, "attempts": [], "delivery": None,
    }


def _load_manifest_fingerprint_from_plan(plan: AdaptivePlan) -> str:
    return plan.execution_fingerprint


def _load_manifest_fingerprint(root: Path) -> str:
    return str(load_json(root / "manifest.json")["executionFingerprint"])


def _append_observation(observations: list[Observation], record: Mapping[str, Any]) -> None:
    attempts = record.get("attempts") or []
    if not attempts:
        return
    observations.append(Observation.from_record(record))


def _validate_saved_record(record: Mapping[str, Any], plan: AdaptivePlan, request: PlannedRequest) -> None:
    if record.get("schemaVersion") != ADAPTIVE_RECORD_VERSION:
        raise ValueError("Unsupported adaptive request record; create a fresh adaptive plan.")
    if (record.get("requestId") != request.request_id or record.get("sequenceIndex") != request.sequence_index
            or record.get("taskId") != request.task_id or record.get("instanceId") != request.instance_id):
        raise ValueError(f"Adaptive request record differs from frozen request {request.request_id}")
    if record.get("state") not in _TERMINAL | {"started"}:
        raise ValueError(f"Invalid adaptive request state for {request.request_id}")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or len(attempts) > 1:
        raise ValueError(f"Adaptive request {request.request_id} must have at most one attempt")
    if attempts:
        decision = attempts[0].get("decision")
        if not isinstance(decision, dict) or decision.get("candidateId") not in {c.candidate_id for c in plan.candidates}:
            raise ValueError(f"Invalid saved decision for {request.request_id}")


def _load_request_records(root: Path) -> dict[str, dict[str, Any]]:
    records_root = root / "adaptive-records"
    if not records_root.exists():
        return {}
    rows = [load_json(path) for path in sorted(records_root.glob("*.json"))]
    result = {str(row.get("requestId")): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("Adaptive request ledger contains duplicate request IDs")
    return result


def _record_path(root: Path, request_id: str) -> Path:
    return root / f"{request_id}.json"


def _validate_policy_targets(policy, candidate_ids: set[str]) -> None:
    target_reader = getattr(policy, "candidate_targets", None)
    named = tuple(target_reader()) if callable(target_reader) else ()
    unknown = set(named) - candidate_ids
    if unknown:
        raise ValueError(f"Policy references unknown candidates: {', '.join(sorted(unknown))}")


def _validate_disturbances(disturbances, candidates, request_count: int) -> None:
    """Refuse a disturbance that could never take effect, so a scenario is not silently undisturbed."""
    strategies = {candidate.candidate_id: candidate.configuration["strategy"] for candidate in candidates}
    names: set[str] = set()
    for disturbance in disturbances:
        name = disturbance["name"]
        if name in names:
            raise ValueError(f"Duplicate disturbance name: {name}")
        names.add(name)
        targets = list(disturbance.get("candidates") or ())
        unknown = set(targets) - set(strategies)
        if unknown:
            raise ValueError(f"Unknown candidate(s) in disturbance {name}: {', '.join(sorted(unknown))}")
        component = disturbance["component"]
        if component != "model":  # every candidate calls a model; tool components depend on strategy
            unaffected = sorted(candidate_id for candidate_id in (targets or strategies)
                                if strategies[candidate_id] != component)
            if targets and unaffected:
                raise ValueError(f"Disturbance {name} targets component {component}, which candidate(s) "
                                 f"{', '.join(unaffected)} do not use")
            if not targets and len(unaffected) == len(strategies):
                raise ValueError(f"Disturbance {name} targets component {component}, which no candidate uses")
        first = disturbance.get("firstSequence", 1)
        if first > request_count:
            raise ValueError(f"Disturbance {name} starts at sequence {first}, after the last request "
                             f"({request_count})")


def _validate_policy_readings(policy, declared_signals) -> None:
    """Check at planning every (signal, statistic) pair the policy says it will read."""
    reader = getattr(policy, "signal_readings", None)
    for signal, statistic in (reader() if callable(reader) else ()):
        try:
            validate_reading_request(signal, statistic, declared_signals)
        except ValueError as exc:
            raise ValueError(f"Policy reading is invalid: {exc}") from exc


def _check_strategy_capability(package, candidate_id: str, strategy: str, surface, params: Mapping[str, Any]) -> None:
    """Fail at planning when the dataset cannot serve a candidate's strategy.

    This mirrors what the provisioning runtime requires at execution, so an unsupported
    candidate is refused before any request is attempted.
    """
    needs = {"local_function": "tool_provider", "local_mcp": "mcp_server"}.get(strategy)
    if needs is not None:
        method = getattr(package, needs, None)
        value = None
        if method is not None:
            operations = surface.model_dump(mode="json").get("operations")
            kwargs = {"allowed_operations": operations} if "allowed_operations" in signature(method).parameters else {}
            value = method(**kwargs)
        if value is None:
            raise CapabilityUnavailableError(
                f"Candidate {candidate_id} uses {strategy}, but the dataset provides no {needs} capability")
    elif strategy == "remote_mcp" and not isinstance(params.get("mcp_server"), dict):
        raise CapabilityUnavailableError(
            f"Candidate {candidate_id} uses remote_mcp, which requires execution MCP server settings")


@contextmanager
def _adaptive_lock(root: Path):
    lock_path = root / ".adaptive.lock"
    with lock_path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


__all__ = ["ADAPTIVE_PLAN_VERSION", "ADAPTIVE_RECORD_VERSION", "AdaptiveWorkflow",
           "AdaptiveWorkflowOutcome", "run_adaptive_workflow"]
