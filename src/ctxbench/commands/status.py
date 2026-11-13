from __future__ import annotations

from pathlib import Path

from ctxbench.benchmark.provisioning import validate_artifact_directory
from ctxbench.benchmark.execution_records import latest_attempt_states, rebuild_responses
from ctxbench.benchmark.provisioning import validate_manifest

from ctxbench.benchmark.evaluation import judge_identifier
from ctxbench.benchmark.models import EvaluationModelConfig
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import read_jsonl


def _trial_id(row: dict[str, object]) -> str:
    return str(row.get("responseId") or row.get("requestId") or row.get("trialId", ""))


def _last_status_map(path: Path) -> dict[str, str]:
    """Returns {trialId: status}, last entry per trialId wins (handles duplicates)."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for item in read_jsonl(path):
        trial_id = _trial_id(item)
        if trial_id:
            result[trial_id] = str(item.get("status", "unknown"))
    return result


def _tally(status_map: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in status_map.values():
        counts[status] = counts.get(status, 0) + 1
    return counts


def _judge_status(value: dict[str, object]) -> str:
    status = value.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "error" if value.get("error") else "evaluated"


def _load_judge_votes(path: Path) -> dict[tuple[str, str], dict[str, object]]:
    """Returns {(trialId, judgeId): vote}, last entry wins."""
    if not path.exists():
        return {}
    result: dict[tuple[str, str], dict[str, object]] = {}
    for item in read_jsonl(path):
        trial_id = _trial_id(item)
        judge_id = str(item.get("judgeId", ""))
        if trial_id and judge_id:
            result[(trial_id, judge_id)] = dict(item)
    return result


def _load_configured_judges(root: Path) -> list[EvaluationModelConfig]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = load_json(manifest_path)
    except Exception:
        return []
    if not isinstance(manifest, dict):
        return []
    evaluation = manifest.get("evaluation", {})
    if not isinstance(evaluation, dict):
        return []
    judges = evaluation.get("judges", [])
    if not isinstance(judges, list):
        return []
    return [
        EvaluationModelConfig.model_validate(item)
        for item in judges
        if isinstance(item, dict)
    ]


def _judge_breakdown(root: Path, answer_total: int) -> list[tuple[str, int, int, int, int]]:
    votes = _load_judge_votes(root / "judge_votes.jsonl")
    configured = [judge_identifier(judge) for judge in _load_configured_judges(root)]
    observed = sorted(
        {
            judge_id
            for _, judge_id in votes.keys()
            if judge_id
        }
    )
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for judge_id in configured + observed:
        if judge_id and judge_id not in seen:
            ordered_ids.append(judge_id)
            seen.add(judge_id)

    counts: dict[str, dict[str, int]] = {
        judge_id: {"evaluated": 0, "error": 0}
        for judge_id in ordered_ids
    }
    for (_, judge_id), vote in votes.items():
        status = _judge_status(vote)
        counts.setdefault(judge_id, {"evaluated": 0, "error": 0})
        if status == "error":
            counts[judge_id]["error"] += 1
        else:
            counts[judge_id]["evaluated"] += 1

    rows: list[tuple[str, int, int, int, int]] = []
    for judge_id in ordered_ids:
        evaluated = counts.get(judge_id, {}).get("evaluated", 0)
        failed = counts.get(judge_id, {}).get("error", 0)
        pending = max(0, answer_total - evaluated - failed)
        rows.append((judge_id, answer_total, evaluated, failed, pending))
    return rows


def _count_trials(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in read_jsonl(path))


def _load_experiment_id(root: Path) -> str:
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = load_json(manifest_path)
            if isinstance(manifest, dict):
                return str(manifest.get("experimentId", "unknown"))
        except Exception:
            pass
    return "unknown"


def status_command(output_dir: str | None = None, *, by: str | None = None) -> int:
    root = Path(output_dir).resolve() if output_dir else Path(".").resolve()

    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        raw_manifest = load_json(manifest_path)
        if isinstance(raw_manifest, dict) and raw_manifest.get("workflowKind") == "adaptive":
            return _adaptive_status_command(root, by=by)

    manifest = validate_manifest(root)
    rebuild_responses(root, execution_fingerprint=str(manifest["executionFingerprint"]))
    attempt_states = latest_attempt_states(root)
    validate_artifact_directory(root)
    trials_path = root / "trials.jsonl"
    responses_path = root / "responses.jsonl"
    evals_path = root / "evals.jsonl"

    experiment_id = _load_experiment_id(root)
    trial_count = _count_trials(trials_path)
    response_map = _last_status_map(responses_path)
    eval_map = _last_status_map(evals_path)

    response_tally = _tally(response_map)
    eval_tally = _tally(eval_map)

    response_success = response_tally.get("success", 0)
    response_error = response_tally.get("error", 0)
    response_total = sum(response_tally.values())

    eval_done = eval_tally.get("evaluated", 0)
    eval_error = eval_tally.get("error", 0)
    eval_total = sum(eval_tally.values())

    uncertain_count = sum(state == "started" for state in attempt_states.values())
    col = (10, 8, 10, 8, 8, 8)
    header = (
        f"{'Phase':<{col[0]}} {'Total':>{col[1]}} {'Success':>{col[2]}} "
        f"{'Failed':>{col[3]}} {'Started':>{col[4]}} {'Pending':>{col[5]}}"
    )
    sep = "─" * len(header)

    print(f"Experiment : {experiment_id}")
    print(f"Directory  : {root}")
    print()
    print(header)
    print(sep)

    execute_pending = max(0, trial_count - response_total - uncertain_count)
    print(
        f"{'execute':<{col[0]}} {trial_count:>{col[1]}} {response_success:>{col[2]}} "
        f"{response_error:>{col[3]}} {uncertain_count:>{col[4]}} {execute_pending:>{col[5]}}"
    )

    eval_pending = max(0, response_success - eval_total)
    print(
        f"{'eval':<{col[0]}} {response_success:>{col[1]}} {eval_done:>{col[2]}} "
        f"{eval_error:>{col[3]}} {0:>{col[4]}} {eval_pending:>{col[5]}}"
    )

    if by:
        if by == "judge":
            rows = _judge_breakdown(root, response_success)
            print()
            print(f"{'Judge':<24} {'Total':>8} {'Success':>8} {'Failed':>8} {'Pending':>8}")
            print("─" * 64)
            for judge_id, total, success, failed, pending in rows:
                print(
                    f"{judge_id:<24} {total:>8} {success:>8} {failed:>8} {pending:>8}"
                )
        elif by in {"configuration", "representation", "surface", "strategy", "model", "instance", "task"}:
            field = {"configuration": "configurationId", "model": "modelId", "instance": "instanceId", "task": "taskId"}.get(by, by)
            from ctxbench.util.jsonl import read_jsonl
            groups: dict[str, list[dict[str, object]]] = {}
            for trial in read_jsonl(trials_path):
                groups.setdefault(str(trial.get(field)), []).append(trial)
            print(f"\n{by:<24} {'Total':>8} {'Success':>8} {'Failed':>8} {'Pending':>8}")
            for label, trials in sorted(groups.items()):
                statuses = [response_map.get(_trial_id(trial)) for trial in trials]
                success = statuses.count("success")
                failed = statuses.count("error")
                print(f"{label:<24} {len(trials):>8} {success:>8} {failed:>8} {statuses.count(None):>8}")
                if by == "strategy" and len({t["configurationId"] for t in trials}) > 1:
                    print("  Pools multiple configurations: " + ", ".join(sorted({str(t["configurationId"]) for t in trials})))
        else:
            raise ValueError(f"Unsupported status grouping: {by}")

    return 0


def _adaptive_status_command(root: Path, *, by: str | None) -> int:
    from ctxbench.adaptive.artifacts import adaptive_plan_from_payload, validate_workflow_manifest
    from ctxbench.adaptive.projections import rebuild_adaptive_responses
    from ctxbench.execution.service import TrialExecutionService

    manifest = validate_workflow_manifest(root)
    plan = adaptive_plan_from_payload(load_json(root / "adaptive-plan.json"))
    rebuild_adaptive_responses(root)
    records_path = root / "adaptive-records"
    records = [load_json(path) for path in sorted(records_path.glob("*.json"))] if records_path.exists() else []
    by_request = {str(row["requestId"]): row for row in records}
    if len(by_request) != len(records):
        raise ValueError("Adaptive request ledger contains duplicate request IDs.")
    planned_requests = {request.request_id: request for request in plan.requests}
    unknown_requests = set(by_request) - set(planned_requests)
    if unknown_requests:
        raise ValueError(f"Adaptive ledger contains request IDs outside its plan: {', '.join(sorted(unknown_requests))}")
    terminal_states = {"delivered", "failed", "rejected"}
    if any(row.get("state") not in terminal_states | {"started"} for row in records):
        raise ValueError("Adaptive request ledger contains an unsupported state.")
    for request_id, record in by_request.items():
        request = planned_requests[request_id]
        if (record.get("sequenceIndex") != request.sequence_index
                or record.get("taskId") != request.task_id
                or record.get("instanceId") != request.instance_id):
            raise ValueError(f"Adaptive ledger identity differs from frozen request {request_id}.")
    state_counts = {state: sum(row.get("state") == state for row in records)
                    for state in ("delivered", "failed", "rejected", "started")}
    response_count = state_counts["delivered"]
    eval_tally = _tally(_last_status_map(root / "evals.jsonl"))
    eval_done = eval_tally.get("evaluated", 0)
    eval_error = eval_tally.get("error", 0)
    service = TrialExecutionService(root)
    execution_ids = {
        invocation.execution.execution_id
        for request in plan.requests
        for invocation in request.candidates.values()
    }
    attempts_by_execution = {execution_id: service.attempts(execution_id) for execution_id in execution_ids}
    attempt_records = [row for rows in attempts_by_execution.values() for row in rows]
    uncertain = sum(bool(rows) and rows[-1].get("state") == "started" for rows in attempts_by_execution.values())
    planned = len(plan.requests)
    pending = max(0, planned - len(records))

    print(f"Experiment : {manifest.get('experimentId', plan.workflow_id)}")
    print(f"Directory  : {root}")
    print("Workflow   : adaptive")
    print()
    col = (12, 8, 10, 8, 10, 8, 8)
    header = (f"{'Phase':<{col[0]}} {'Total':>{col[1]}} {'Delivered':>{col[2]}} "
              f"{'Failed':>{col[3]}} {'Rejected':>{col[4]}} {'Started':>{col[5]}} {'Pending':>{col[6]}}")
    print(header)
    print("─" * len(header))
    print(f"{'requests':<{col[0]}} {planned:>{col[1]}} {state_counts['delivered']:>{col[2]}} "
          f"{state_counts['failed']:>{col[3]}} {state_counts['rejected']:>{col[4]}} "
          f"{state_counts['started']:>{col[5]}} {pending:>{col[6]}}")
    delivered_attempts = sum(
        row.get("attemptId") == ((by_request.get(str(row.get("correlationId")), {}).get("delivery") or {}).get("attemptId"))
        for row in attempt_records
    )
    print(f"{'attempts':<{col[0]}} {len(attempt_records):>{col[1]}} {delivered_attempts:>{col[2]}} "
          f"{sum(row.get('state') == 'failed' for row in attempt_records):>{col[3]}} {0:>{col[4]}} "
          f"{uncertain:>{col[5]}} {0:>{col[6]}}")
    print(f"{'eval':<{col[0]}} {response_count:>{col[1]}} {eval_done:>{col[2]}} "
          f"{eval_error:>{col[3]}} {0:>{col[4]}} {0:>{col[5]}} "
          f"{max(0, response_count - eval_done - eval_error):>{col[6]}}")

    if by == "judge":
        rows = _judge_breakdown(root, response_count)
        print()
        print(f"{'Judge':<24} {'Total':>8} {'Success':>8} {'Failed':>8} {'Pending':>8}")
        print("─" * 64)
        for judge_id, total, success, failed, pending_count in rows:
            print(f"{judge_id:<24} {total:>8} {success:>8} {failed:>8} {pending_count:>8}")
    elif by in {"task", "instance", "candidate"}:
        counts: dict[str, dict[str, int]] = {}
        for request in plan.requests:
            record = by_request.get(request.request_id, {})
            value = (record.get("delivery") or {}).get("candidateId") if by == "candidate" else getattr(request, f"{by}_id")
            label = str(value or "<unassigned>")
            bucket = counts.setdefault(label, {"total": 0, "delivered": 0, "failed": 0, "pending": 0})
            bucket["total"] += 1
            state = record.get("state")
            bucket["delivered"] += state == "delivered"
            bucket["failed"] += state in {"failed", "rejected"}
            bucket["pending"] += state not in terminal_states
        print(f"\n{by:<24} {'Total':>8} {'Delivered':>10} {'Failed':>8} {'Pending':>8}")
        for label, row in sorted(counts.items()):
            print(f"{label:<24} {row['total']:>8} {row['delivered']:>10} {row['failed']:>8} {row['pending']:>8}")
    elif by is not None:
        raise ValueError("Adaptive status --by supports task, instance, candidate, or judge.")
    return 0
