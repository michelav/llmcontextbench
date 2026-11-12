from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.benchmark.provisioning import validate_artifact_directory, validate_manifest

from ctxbench.ai.engine import Engine
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.execution_records import execution_lock, rebuild_responses
from ctxbench.benchmark.results import serialize_run_result
from ctxbench.benchmark.selectors import RunSelector, matches_runspec
from ctxbench.benchmark.workflow import execute_benchmark_trials
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
    from ctxbench.adaptive.artifacts import validate_workflow_manifest
    manifest = validate_workflow_manifest(source.parent)
    if manifest.get("workflowKind") == "adaptive":
        return _execute_adaptive_plan(
            source.parent, manifest, force=force, retry_uncertain=retry_uncertain,
            selector=selector, verbose=verbose,
        )
    if manifest.get("experimentKind") == "adaptive":
        adaptive_plan = load_json(source.parent / "adaptive-plan.json")
        version = adaptive_plan.get("schemaVersion") if isinstance(adaptive_plan, dict) else None
        if version == 1:
            raise ValueError(
                "Adaptive plan schemaVersion 1 is not supported or migrated. "
                "Create a fresh adaptive plan using the versioned adaptive workflow contract."
            )
        raise ValueError("Legacy adaptive artifacts require a fresh plan using the versioned adaptive workflow contract.")
    if manifest.get("provisioningArtifactVersion") == 4:
        with execution_lock(source.parent):
            verify_snapshot(source.parent, manifest, execution=True)
            rebuild_responses(source.parent, execution_fingerprint=str(manifest["executionFingerprint"]))
            validate_artifact_directory(source.parent)
            runspecs = _load_runspecs(source)
            active_selector = selector or RunSelector()
            runspecs = [r for r in runspecs if matches_runspec(r, active_selector)]
            if not runspecs:
                print("No trials matched the selector.")
                return 0
            return execute_benchmark_trials(
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


def _execute_adaptive_plan(
    root: Path,
    manifest: dict[str, Any],
    *,
    force: bool,
    retry_uncertain: bool,
    selector: RunSelector | None,
    verbose: bool,
) -> int:
    from dataclasses import replace

    from ctxbench.adaptive.artifacts import adaptive_plan_from_payload
    from ctxbench.adaptive.runtime_adapter import invoke_adaptive_execution, resolve_adaptive_dataset
    from ctxbench.adaptive.workflow import run_adaptive_workflow
    from ctxbench.execution.service import ExecutionSession, TrialExecutionService

    if force:
        raise ValueError("--force is not supported for adaptive workflows; create a fresh plan and output directory.")
    selected = selector or RunSelector()
    if any(getattr(selected, name) for name in selected.__dataclass_fields__):
        raise ValueError("Selectors cannot filter an adaptive workload because decisions require its frozen order.")
    plan = adaptive_plan_from_payload(load_json(root / "adaptive-plan.json"))
    dataset_metadata = manifest.get("dataset")
    if not isinstance(dataset_metadata, dict):
        raise ValueError("Adaptive manifest requires dataset provenance.")
    dataset = resolve_adaptive_dataset(dataset_metadata)
    logger = PhaseLogger(verbose=verbose)
    service = TrialExecutionService(root)
    engine = Engine(event_logger=lambda event, message, fields: logger.event(
        str(fields.pop("level", "INFO")), str(fields.pop("phase", "EXECUTE")), event, message, **fields
    ))

    def invoke(request, session):
        payload = request.payload
        if not isinstance(payload, dict):
            raise ValueError("adaptive execution payload must be an object")
        metadata = dict(payload.get("resultMetadata") or {})
        metadata.setdefault("dataset", dataset_metadata)
        metadata.setdefault("experimentId", manifest.get("experimentId", plan.workflow_id))
        metadata.setdefault("configurationId", request.candidate_id)
        invocation = replace(request, payload={**payload, "resultMetadata": metadata})
        return invoke_adaptive_execution(
            invocation, session, dataset=dataset,
            trace_options=dict(payload.get("traceOptions") or manifest.get("trace") or {}),
        )

    with ExecutionSession(engine) as session:
        outcome = run_adaptive_workflow(
            plan, root=root, service=service, session=session, invoke=invoke,
            retry_uncertain=retry_uncertain,
        )
    print(
        f"Adaptive requests: {outcome.delivered} delivered, "
        f"{outcome.rejected} rejected, {outcome.failed} failed."
    )
    return 0
