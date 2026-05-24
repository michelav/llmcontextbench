from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxbench.adapters.repoqa.evaluation import evaluate_response as evaluate_repoqa_response
from ctxbench.benchmark.evaluation import (
    build_evaluation_jobs,
    build_evaluation_summary_rows,
    evaluate_run_results,
    judge_identifier,
    recompute_judge_outcome,
)
from ctxbench.benchmark.evaluation_batch import (
    DEFAULT_BATCH_POLL_INTERVAL_SECONDS,
    load_batch_id_from_manifest,
    retrieve_evaluation_batch,
    submit_evaluation_batch,
)
from ctxbench.benchmark.models import EvaluationModelConfig, ExperimentTrace, TrialResult
from ctxbench.benchmark.selectors import RunSelector, matches_run_result
from ctxbench.benchmark.results import (
    _resolve_eval_trace_ref,
    serialize_evaluation_result,
    serialize_judge_votes,
)
from ctxbench.util.fs import load_json, write_json
from ctxbench.util.jsonl import append_jsonl, read_jsonl, write_jsonl
from ctxbench.util.logging import PhaseLogger, ProgressTracker


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------

def _trial_id(row: dict[str, Any]) -> str:
    return str(row.get("trialId", ""))


def _load_responses(path: Path) -> list[TrialResult]:
    if not path.exists():
        raise FileNotFoundError(f"Responses file not found: {path}. Run 'ctxbench execute' first.")
    payloads = [dict(item) for item in read_jsonl(path)]
    if not payloads:
        return []
    required = {"response", "status", "timing"}
    missing = sorted(required - set(payloads[0]))
    if missing:
        raise ValueError(
            f"Input looks like trials, not responses (missing: {', '.join(missing)}). "
            "Pass responses.jsonl, not trials.jsonl."
        )
    if "dataset" not in payloads[0]:
        raise ValueError(
            "Responses file is missing context data. Re-run 'ctxbench execute' to regenerate."
        )
    return [TrialResult.model_validate(item) for item in payloads]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _load_manifest(source_root: Path) -> dict[str, Any]:
    path = source_root / "manifest.json"
    if not path.exists():
        raise ValueError(
            f"Missing manifest: {path}. Re-run 'ctxbench plan' to regenerate."
        )
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid manifest: {path}")
    return payload


def _load_judges(source_root: Path) -> list[EvaluationModelConfig]:
    manifest = _load_manifest(source_root)
    evaluation = manifest.get("evaluation", {})
    judges_payload = evaluation.get("judges", []) if isinstance(evaluation, dict) else []
    return [
        EvaluationModelConfig.model_validate(item)
        for item in judges_payload
        if isinstance(item, dict)
    ]


def _load_trace_config(source_root: Path) -> ExperimentTrace:
    manifest = _load_manifest(source_root)
    trace = manifest.get("trace")
    return ExperimentTrace.model_validate(trace) if isinstance(trace, dict) else ExperimentTrace()


def _filter_judges(
    judges: list[EvaluationModelConfig],
    *,
    judge: tuple[str, ...] = (),
    not_judge: tuple[str, ...] = (),
) -> list[EvaluationModelConfig]:
    include = set(judge)
    exclude = set(not_judge)
    filtered = list(judges)
    if include:
        filtered = [j for j in filtered if _judge_matches(j, include)]
    if exclude:
        filtered = [j for j in filtered if not _judge_matches(j, exclude)]
    return filtered


def _judge_matches(config: EvaluationModelConfig, selectors: set[str]) -> bool:
    return bool(_judge_identifiers(config) & selectors)


def _judge_identifiers(config: EvaluationModelConfig) -> set[str]:
    ids: set[str] = set()
    for value in (config.provider, config.model):
        if isinstance(value, str) and value.strip():
            ids.add(value.strip())
    judge_id = config.params.get("id") if isinstance(config.params, dict) else None
    if isinstance(judge_id, str) and judge_id.strip():
        ids.add(judge_id.strip())
    return ids


# ---------------------------------------------------------------------------
# Eval status tracking (replaces checkpoint)
# ---------------------------------------------------------------------------

def _load_skipped_run_ids(path: Path) -> set[str]:
    """Returns trialIds already recorded as 'skipped' in evals.jsonl."""
    if not path.exists():
        return set()
    return {
        _trial_id(item)
        for item in read_jsonl(path)
        if item.get("status") == "skipped" and _trial_id(item)
    }


def _load_evaluated_run_ids(path: Path, *, method: str) -> set[str]:
    if not path.exists():
        return set()
    return {
        _trial_id(item)
        for item in read_jsonl(path)
        if item.get("evaluationMethod") == method and _trial_id(item)
    }


def _load_votes_index(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Returns {trialId: [vote dicts]} from judge_votes.jsonl."""
    if not path.exists():
        return {}
    index: dict[str, list[dict[str, Any]]] = {}
    for item in read_jsonl(path):
        trial_id = _trial_id(item)
        if trial_id:
            index.setdefault(trial_id, []).append(dict(item))
    return index


def _merge_existing_votes(details: dict[str, Any], existing_votes: list[dict[str, Any]]) -> None:
    """Add votes from judge_votes.jsonl for judges not in the current evaluation, recompute outcome."""
    current_ids = {j.get("judgeId") for j in details.get("judges", [])}
    added = False
    for vote in existing_votes:
        jid = vote.get("judgeId")
        if jid in current_ids:
            continue
        criterias = vote.get("criterias") or {}
        entry: dict[str, Any] = {
            "judgeId": jid,
            "provider": vote.get("provider"),
            "model": vote.get("model"),
            "status": vote.get("status") or ("error" if vote.get("error") else "evaluated"),
            "correctness": criterias.get("correctness") or {},
            "completeness": criterias.get("completeness") or {},
            "inputTokens": vote.get("inputTokens"),
            "outputTokens": vote.get("outputTokens"),
            "durationMs": vote.get("durationMs"),
        }
        if vote.get("error"):
            entry["error"] = vote.get("error")
        details.setdefault("judges", []).append(entry)
        added = True
    if added:
        outcome = recompute_judge_outcome(details["judges"])
        if outcome is not None:
            details["outcome"] = outcome


def _compact_evals(path: Path) -> None:
    """Rewrite evals.jsonl keeping only the last entry per trialId."""
    if not path.exists():
        return
    rows = list(read_jsonl(path))
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        trial_id = _trial_id(row)
        if trial_id:
            seen[trial_id] = dict(row)
    write_jsonl(path, list(seen.values()))


def _compact_judge_votes(path: Path) -> None:
    """Rewrite judge_votes.jsonl keeping only the last entry per (trialId, judgeId)."""
    if not path.exists():
        return
    rows = list(read_jsonl(path))
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        trial_id = _trial_id(row)
        judge_id = str(row.get("judgeId", ""))
        if trial_id:
            seen[(trial_id, judge_id)] = dict(row)
    write_jsonl(path, list(seen.values()))


def _validation_type(result: TrialResult) -> str | None:
    return result.validationType or result.metadata.validationType


def _repoqa_threshold(config: dict[str, Any]) -> float:
    raw = config.get("threshold", 0.8)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"RepoQA validationConfig.threshold must be numeric, got {raw!r}.") from exc


def _repoqa_ignore_comments(config: dict[str, Any]) -> bool:
    return bool(config.get("ignoreComments", False))


# ---------------------------------------------------------------------------
# eval command
# ---------------------------------------------------------------------------

def eval_command(
    responses: str | None = None,
    *,
    force: bool = False,
    judge: tuple[str, ...] = (),
    not_judge: tuple[str, ...] = (),
    batch: bool = False,
    batch_id: str | None = None,
    wait: bool = False,
    poll_interval: int = DEFAULT_BATCH_POLL_INTERVAL_SECONDS,
    continue_on_error: bool = False,
    verbose: bool = False,
    progress: bool = False,
    selector: RunSelector | None = None,
) -> int:
    # --batch-id implies --batch
    if batch_id:
        batch = True
    if not batch and wait:
        raise ValueError("--wait requires --batch.")
    if not batch and poll_interval != DEFAULT_BATCH_POLL_INTERVAL_SECONDS:
        raise ValueError("--poll-interval requires --batch.")
    if poll_interval < 1:
        raise ValueError("--poll-interval must be >= 1.")

    logger = PhaseLogger(verbose=verbose)
    event_logger = lambda label, message, fields: logger.phase(label, message, **fields)

    source = Path(responses).resolve() if responses else Path("responses.jsonl").resolve()
    source_root = source.parent

    logger.phase("LOAD", "Loading responses", path=str(source))
    results = _load_responses(source)

    active_selector = selector or RunSelector()
    results = [r for r in results if matches_run_result(r, active_selector)]
    if not results:
        print("No responses matched the selector.")
        return 0

    supported_validation_types = {"judge", "repoqa-scorer"}
    unsupported = sorted({
        str(_validation_type(result))
        for result in results
        if _validation_type(result) not in supported_validation_types
    })
    if unsupported:
        raise ValueError(f"Unsupported validation type(s): {', '.join(unsupported)}")

    repoqa_results = [result for result in results if _validation_type(result) == "repoqa-scorer"]
    judge_results = [result for result in results if _validation_type(result) == "judge"]
    if batch and repoqa_results:
        raise ValueError("--batch is not supported for repoqa-scorer validation.")

    judges: list[EvaluationModelConfig] = []
    if judge_results:
        judges = _filter_judges(
            _load_judges(source_root),
            judge=judge,
            not_judge=not_judge,
        )
        if not judges:
            selected = ", ".join(list(judge) or ["<all>"])
            raise ValueError(f"No judges matched the selector(s): {selected}.")

    trace_config = _load_trace_config(source_root)
    write_traces = trace_config.writeFiles

    evals_path = source_root / "evals.jsonl"
    votes_path = source_root / "judge_votes.jsonl"
    artifact_root = source_root

    votes_index = _load_votes_index(votes_path)
    evaluated_judge_ids: dict[str, set[str]] = {
        run_id: {v.get("judgeId", "") for v in votes if v.get("status") != "error"}
        for run_id, votes in votes_index.items()
    }
    skipped_run_ids: set[str] = _load_skipped_run_ids(evals_path) if not force else set()
    evaluated_repoqa_ids: set[str] = (
        _load_evaluated_run_ids(evals_path, method="repoqa-scorer") if not force else set()
    )
    has_duplicates = False

    # Group pending runs by which judges they still need.
    # A run is pending if at least one selected judge hasn't voted for it yet.
    # Runs already marked as "skipped" (missing context blocks) are excluded unless --force.
    groups: dict[tuple[str, ...], tuple[list[TrialResult], list[EvaluationModelConfig]]] = {}
    for r in judge_results:
        if not force and r.trialId in skipped_run_ids:
            continue
        if force:
            missing = judges
        else:
            done = evaluated_judge_ids.get(r.trialId, set())
            missing = [j for j in judges if judge_identifier(j) not in done]
        if not missing:
            continue
        key = tuple(sorted(judge_identifier(j) for j in missing))
        if key not in groups:
            groups[key] = ([], missing)
        groups[key][0].append(r)

    pending_repoqa = [
        result
        for result in repoqa_results
        if force or result.trialId not in evaluated_repoqa_ids
    ]
    pending = [r for runs, _ in groups.values() for r in runs] + pending_repoqa
    logger.phase(
        "LOAD",
        "Responses loaded",
        total=len(results),
        evaluated=len(results) - len(pending),
        pending=len(pending),
    )

    progress_tracker = ProgressTracker(total=len(pending), enabled=progress)
    logger.progress = progress_tracker
    progress_tracker.start()

    def _persist(result: TrialResult, evaluated: Any) -> None:
        if evaluated is None:
            progress_tracker.advance()
            return
        item = evaluated.items[0] if evaluated.items else None
        is_skipped = item is not None and item.status == "skipped"
        is_repoqa = item is not None and item.evaluationMethod == "repoqa-scorer"
        if not is_skipped and not is_repoqa:
            existing = votes_index.get(evaluated.trialId)
            if item is not None and existing:
                _merge_existing_votes(item.details, existing)
                nonlocal has_duplicates
                has_duplicates = True
        trace_ref = _resolve_eval_trace_ref(evaluated, artifact_root=artifact_root, write_trace=write_traces)
        payload = serialize_evaluation_result(evaluated, trace_ref=trace_ref)
        append_jsonl(evals_path, [payload])
        if not is_skipped:
            votes = serialize_judge_votes(evaluated, trace_ref=trace_ref)
            if votes:
                append_jsonl(votes_path, votes)
        if is_skipped and is_repoqa:
            logger.phase("SKIP", "Evaluation skipped", run=evaluated.trialId)
        elif is_skipped:
            logger.phase("SKIP", "Evaluation skipped (missing context blocks)", run=evaluated.trialId)
        else:
            logger.phase("WRITE", "Evaluation written", run=evaluated.trialId)
        progress_tracker.advance()

    if batch:
        if len(judges) != 1:
            raise ValueError("--batch requires exactly one judge. Use --judge to select one.")
        jobs = build_evaluation_jobs(
            [r for runs, _ in groups.values() for r in runs],
            judges=judges,
            only=None,
            mode=None,
            event_logger=event_logger,
        )
        evaluated_pairs = {
            (run_id, jid)
            for run_id, jids in evaluated_judge_ids.items()
            for jid in jids
        }
        if not force:
            jobs = [j for j in jobs if (j.result.trialId, judge_identifier(j.judge)) not in evaluated_pairs]
        if not jobs:
            print("No pending evaluation jobs.")
            return 0
        resolved_batch_id = batch_id or (None if force else load_batch_id_from_manifest(source_root))
        if resolved_batch_id is None:
            manifest = submit_evaluation_batch(jobs=jobs, source_root=source_root)
            resolved_batch_id = str(manifest.get("batchId") or "")
            print(f"Submitted batch {resolved_batch_id} ({len(jobs)} request(s)).")
            if not wait:
                return 0

        manifest, batch_evaluations = retrieve_evaluation_batch(
            batch_id=resolved_batch_id,
            jobs=jobs,
            source_root=source_root,
            wait=wait,
            poll_interval=poll_interval,
        )
        if not batch_evaluations:
            print(
                f"Batch {resolved_batch_id} status: "
                f"{manifest.get('processingStatus') or manifest.get('status') or 'unknown'}"
            )
            return 0

        progress_tracker.total = len(batch_evaluations)
        progress_tracker.current = 0
        progress_tracker.start()
        results_by_run_id = {r.trialId: r for runs, _ in groups.values() for r in runs}
        for evaluated in batch_evaluations:
            source_result = results_by_run_id.get(evaluated.trialId)
            if source_result is not None:
                _persist(source_result, evaluated)

        if has_duplicates:
            _compact_evals(evals_path)
            _compact_judge_votes(votes_path)
        _write_summary(evals_path, source_root)
        print(f"Collected batch {resolved_batch_id} ({len(batch_evaluations)} result(s)).")
        return 0

    for result in pending_repoqa:
        config = dict(result.validationConfig or result.metadata.validationConfig)
        evaluated = evaluate_repoqa_response(
            result,
            threshold=_repoqa_threshold(config),
            ignore_comments=_repoqa_ignore_comments(config),
        )
        _persist(result, evaluated)

    for group_runs, group_judges in groups.values():
        evaluate_run_results(
            group_runs,
            judges=group_judges,
            only=None,
            mode=None,
            continue_on_error=continue_on_error,
            event_logger=event_logger,
            on_result=_persist,
        )

    if has_duplicates or force:
        _compact_evals(evals_path)
        _compact_judge_votes(votes_path)
    _write_summary(evals_path, source_root)

    skipped = len(results) - len(pending)
    print(
        f"Evaluated {len(pending)} response(s) → {evals_path}"
        + (f" ({skipped} skipped)" if skipped else "")
    )
    return 0


def _write_summary(evals_path: Path, source_root: Path) -> None:
    if not evals_path.exists():
        return
    rows = [dict(item) for item in read_jsonl(evals_path)]
    summary_path = source_root / "evals-summary.json"
    write_json(summary_path, build_evaluation_summary_rows(rows).model_dump(mode="json"))
