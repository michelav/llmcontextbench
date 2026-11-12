"""Static benchmark workflow over the shared execution service."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from ctxbench.ai.engine import Engine
from ctxbench.ai.models.base import AIResult
from ctxbench.benchmark.execution_records import rebuild_responses
from ctxbench.benchmark.executor import execute_runtime_request, resolve_trial_dataset
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.provisioning import validate_manifest
from ctxbench.benchmark.results import serialize_run_result
from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.runtime.models import ExecutionResult
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.logging import PhaseLogger, ProgressTracker, trial_log_context


def execute_benchmark_trials(
    runspecs: list[TrialSpec],
    *,
    artifact_root: Path,
    manifest: dict[str, Any],
    force: bool,
    retry_uncertain: bool,
    logger: PhaseLogger,
    progress: bool,
    local_mcp_runtime_decorator=None,
) -> int:
    """Execute a frozen benchmark trial selection and rebuild its response projection."""
    validate_manifest(artifact_root)
    service = TrialExecutionService(artifact_root)
    latest_by_trial = {
        runspec.trialId: _latest_attempt(service.attempts(runspec.trialId))
        for runspec in runspecs
    }
    expected_fingerprint = str(manifest["executionFingerprint"])
    for trial_id, latest in latest_by_trial.items():
        if latest and latest.get("executionFingerprint") != expected_fingerprint:
            raise ValueError(f"Execution fingerprint mismatch in attempt record for trialId {trial_id}.")
    uncertain = [trial_id for trial_id, record in latest_by_trial.items() if record and record["state"] == "started"]
    if uncertain and not retry_uncertain:
        ids = ", ".join(uncertain[:5])
        suffix = "…" if len(uncertain) > 5 else ""
        raise ValueError(
            f"Execution has uncertain started attempts for trialId(s): {ids}{suffix}. "
            "Inspect execution-records; pass --retry-uncertain to create new attempts."
        )

    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()
    session = ExecutionSession(Engine(event_logger=_event_logger(logger)))
    processed = skipped = 0
    try:
        for runspec in runspecs:
            latest = latest_by_trial[runspec.trialId]
            if latest and latest["state"] in {"succeeded", "failed"} and not force:
                skipped += 1
                processed += 1
                progress_tracker.advance()
                logger.info(
                    "EXECUTE", "trial.response.skipped", "Attempt already completed; skipping",
                    **trial_log_context(runspec), status=latest["result"]["status"],
                )
                continue

            runtime_adapter = TrialRuntimeAdapter()
            dataset = resolve_trial_dataset(runspec)
            request = ExecutionRequest(
                execution_id=runspec.trialId,
                workflow_id=runspec.experimentId,
                correlation_id=runspec.trialId,
                experiment_id=runspec.experimentId,
                execution_fingerprint=expected_fingerprint,
                task_id=runspec.taskId,
                instance_id=runspec.instanceId,
                candidate_id=runspec.configurationId,
                payload=runtime_adapter.to_runtime_request(runspec),
                trial_id=runspec.trialId,
            )

            def invoke(_request, active_session):
                started_at = utc_now_iso()
                started_clock = perf_counter()
                try:
                    execution = execute_runtime_request(
                        _request.payload, active_session.resource, dataset,
                        local_mcp_runtime_decorator=local_mcp_runtime_decorator,
                    )
                    result = runtime_adapter.to_trial_result(runspec, execution)
                except Exception as exc:
                    result = TrialRuntimeAdapter().to_trial_result(
                        runspec,
                        ExecutionResult(
                            ai_result=AIResult(answer="", error=str(exc)),
                            started_at=started_at,
                            finished_at=utc_now_iso(),
                            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                        ),
                    )
                return serialize_run_result(
                    result,
                    artifact_root=artifact_root,
                    write_trace=runspec.trace.writeFiles,
                )

            outcome = service.execute(
                request, session, invoke, force=force,
                retry_uncertain=retry_uncertain,
            )
            logger.info(
                "EXECUTE", "trial.response.completed", "Response generated",
                **trial_log_context(runspec), status=outcome.result.get("status"),
                attemptId=outcome.attempt_id,
            )
            progress_tracker.advance()
            processed += 1
    finally:
        session.close()

    rebuild_responses(artifact_root, execution_fingerprint=expected_fingerprint)
    responses_path = artifact_root / "responses.jsonl"
    print(
        f"Processed {processed} trial(s) → {responses_path}"
        + (f" ({skipped} skipped)" if skipped else "")
    )
    return 0


def _latest_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    return attempts[-1] if attempts else None


def _event_logger(logger: PhaseLogger):
    def emit(event_name: str, message: str, fields: dict[str, object]) -> None:
        payload = dict(fields)
        level = str(payload.pop("level", "INFO"))
        phase = str(payload.pop("phase", "EXECUTE"))
        logger.event(level, phase, event_name, message, **payload)
    return emit
