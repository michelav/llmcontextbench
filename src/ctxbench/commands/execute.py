from __future__ import annotations

from pathlib import Path
from time import perf_counter

from ctxbench.benchmark.provisioning import validate_artifact_directory, validate_manifest
from typing import Any

from ctxbench.ai.engine import Engine
from ctxbench.benchmark.executor import execute_runspec, execute_runtime_request, resolve_trial_dataset
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.execution_records import execution_lock, rebuild_responses
from ctxbench.benchmark.runtime_adapter import TrialRuntimeAdapter
from ctxbench.benchmark.selectors import RunSelector, matches_runspec
from ctxbench.benchmark.results import serialize_run_result
from ctxbench.runtime.models import ExecutionResult
from ctxbench.ai.models.base import AIResult
from ctxbench.execution.service import ExecutionRequest, ExecutionSession, TrialExecutionService
from ctxbench.util.clock import utc_now_iso
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import append_jsonl, read_jsonl, write_jsonl
from ctxbench.util.logging import PhaseLogger, ProgressTracker, trial_log_context


def _load_runspecs(path: Path) -> list[TrialSpec]:
    if not path.exists():
        raise FileNotFoundError(f"Trials file not found: {path}. Run 'llmctxbench plan' first.")
    payloads = [dict(item) for item in read_jsonl(path)]
    if not payloads:
        return []
    if "dataset" not in payloads[0]:
        raise ValueError(
            "Trials file is missing context data. Re-run 'llmctxbench plan' to regenerate."
        )
    return [TrialSpec.model_validate(payload) for payload in payloads]


def _load_response_statuses(path: Path) -> dict[str, str]:
    """Returns {trialId: latest status} from responses.jsonl. Handles duplicates by taking last entry."""
    if not path.exists():
        return {}
    statuses: dict[str, str] = {}
    for item in read_jsonl(path):
        trial_id = str(item.get("trialId", ""))
        if trial_id:
            statuses[trial_id] = str(item.get("status", ""))
    return statuses


def _compact_responses(path: Path) -> None:
    """Rewrite responses.jsonl keeping only the last entry per trialId."""
    if not path.exists():
        return
    rows = list(read_jsonl(path))
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        trial_id = str(row.get("trialId", ""))
        if trial_id:
            seen[trial_id] = dict(row)
    write_jsonl(path, list(seen.values()))


def execute_command(
    queries: str | None = None,
    *,
    force: bool = False,
    verbose: bool = False,
    progress: bool = False,
    selector: RunSelector | None = None,
    retry_uncertain: bool = False,
) -> int:
    source = Path(queries).resolve() if queries else Path("trials.jsonl").resolve()
    logger = PhaseLogger(verbose=verbose)
    def event_logger(event_name: str, message: str, fields: dict[str, object]) -> None:
        payload = dict(fields)
        level = str(payload.pop("level", "INFO"))
        phase = str(payload.pop("phase", "EXECUTE"))
        logger.event(level, phase, event_name, message, **payload)

    logger.info("EXECUTE", "trials.loading", "Loading trials", path=str(source))
    from ctxbench.benchmark.fingerprint import verify_snapshot
    manifest = validate_manifest(source.parent)
    if manifest.get("provisioningArtifactVersion") == 4:
        with execution_lock(source.parent):
            verify_snapshot(source.parent, manifest, execution=True)
            rebuild_responses(source.parent, execution_fingerprint=str(manifest["executionFingerprint"]))
            validate_artifact_directory(source.parent)
            runspecs = _load_runspecs(source)
            if manifest.get("experimentKind") == "adaptive":
                from ctxbench.adaptive.v1 import execute_adaptive
                adaptive_plan = load_json(source.parent / "adaptive-plan.json")
                knowledge_path = source.parent / "knowledge.json"
                knowledge = load_json(knowledge_path) if knowledge_path.exists() else None
                return execute_adaptive(adaptive_plan, knowledge, runspecs, root=source.parent,
                                        manifest=manifest, force=force, retry_uncertain=retry_uncertain,
                                        logger=logger, progress=progress)
            active_selector = selector or RunSelector()
            runspecs = [r for r in runspecs if matches_runspec(r, active_selector)]
            if not runspecs:
                print("No trials matched the selector.")
                return 0
            return _execute_durable(
                runspecs,
                artifact_root=source.parent,
                manifest=manifest,
                force=force,
                retry_uncertain=retry_uncertain,
                logger=logger,
                progress=progress,
            )

    manifest = validate_artifact_directory(source.parent)
    verify_snapshot(source.parent, manifest, execution=True)
    runspecs = _load_runspecs(source)

    active_selector = selector or RunSelector()
    runspecs = [r for r in runspecs if matches_runspec(r, active_selector)]
    if not runspecs:
        print("No trials matched the selector.")
        return 0

    responses_path = source.parent / "responses.jsonl"
    artifact_root = source.parent
    write_traces = runspecs[0].trace.writeFiles

    response_statuses = {} if force else _load_response_statuses(responses_path)
    has_duplicates = False
    logger.info(
        "EXECUTE",
        "trials.loaded",
        "Trials loaded",
        total=len(runspecs),
        answered=sum(1 for s in response_statuses.values() if s == "success"),
    )

    progress_tracker = ProgressTracker(total=len(runspecs), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()

    completed = 0
    skipped = 0
    engine = Engine(event_logger=event_logger)
    try:
        for runspec in runspecs:
            existing_status = response_statuses.get(runspec.trialId)

            if existing_status == "success" and not force:
                skipped += 1
                logger.info(
                    "EXECUTE",
                    "trial.response.skipped",
                    "Already responded successfully; skipping",
                    **trial_log_context(runspec),
                )
                progress_tracker.advance()
                completed += 1
                continue

            logger.info(
                "EXECUTE",
                "trial.response.started",
                "Generating response",
                **trial_log_context(runspec),
            )
            result = execute_runspec(runspec, engine)
            logger.info(
                "EXECUTE",
                "trial.response.completed",
                "Response generated",
                **trial_log_context(result),
                status=result.status,
            )
            payload = serialize_run_result(result, artifact_root=artifact_root, write_trace=write_traces)
            append_jsonl(responses_path, [payload])
            if existing_status is not None:
                # Previous entry exists (error case) — will compact at end
                has_duplicates = True
            response_statuses[result.trialId] = result.status
            logger.info("EXECUTE", "response.written", "Response written", **trial_log_context(result), path=str(responses_path))
            progress_tracker.advance()
            completed += 1
    finally:
        engine.close()

    if has_duplicates or force:
        _compact_responses(responses_path)

    print(
        f"Processed {completed} trial(s) → {responses_path}"
        + (f" ({skipped} skipped)" if skipped else "")
    )
    return 0


def _execute_durable(
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

            write_traces = runspec.trace.writeFiles
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
                return serialize_run_result(result, artifact_root=artifact_root, write_trace=write_traces)

            outcome = service.execute(
                request, session, invoke, force=force,
                retry_uncertain=retry_uncertain,
            )
            payload = outcome.result
            logger.info("EXECUTE", "trial.response.completed", "Response generated", **trial_log_context(runspec), status=payload.get("status"), attemptId=outcome.attempt_id)
            progress_tracker.advance()
            processed += 1
    finally:
        session.close()

    rebuild_responses(artifact_root, execution_fingerprint=str(manifest["executionFingerprint"]))
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
