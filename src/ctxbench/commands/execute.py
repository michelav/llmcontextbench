from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.ai.engine import Engine
from ctxbench.benchmark.executor import execute_runspec
from ctxbench.benchmark.models import TrialSpec
from ctxbench.benchmark.selectors import RunSelector, matches_runspec
from ctxbench.benchmark.results import serialize_run_result
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
) -> int:
    source = Path(queries).resolve() if queries else Path("trials.jsonl").resolve()
    logger = PhaseLogger(verbose=verbose)
    def event_logger(event_name: str, message: str, fields: dict[str, object]) -> None:
        payload = dict(fields)
        level = str(payload.pop("level", "INFO"))
        phase = str(payload.pop("phase", "EXECUTE"))
        logger.event(level, phase, event_name, message, **payload)

    logger.info("EXECUTE", "trials.loading", "Loading trials", path=str(source))
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
