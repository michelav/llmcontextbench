from __future__ import annotations

from pathlib import Path

from ctxbench.benchmark.provisioning import validate_artifact_directory

from ctxbench.benchmark.evaluation import judge_identifier
from ctxbench.benchmark.models import EvaluationModelConfig
from ctxbench.util.fs import load_json
from ctxbench.util.jsonl import read_jsonl


def _trial_id(row: dict[str, object]) -> str:
    return str(row.get("trialId", ""))


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

    col = (10, 8, 10, 8, 8)
    header = (
        f"{'Phase':<{col[0]}} {'Total':>{col[1]}} {'Success':>{col[2]}} "
        f"{'Failed':>{col[3]}} {'Pending':>{col[4]}}"
    )
    sep = "─" * len(header)

    print(f"Experiment : {experiment_id}")
    print(f"Directory  : {root}")
    print()
    print(header)
    print(sep)

    execute_pending = max(0, trial_count - response_total)
    print(
        f"{'execute':<{col[0]}} {trial_count:>{col[1]}} {response_success:>{col[2]}} "
        f"{response_error:>{col[3]}} {execute_pending:>{col[4]}}"
    )

    eval_pending = max(0, response_success - eval_total)
    print(
        f"{'eval':<{col[0]}} {response_success:>{col[1]}} {eval_done:>{col[2]}} "
        f"{eval_error:>{col[3]}} {eval_pending:>{col[4]}}"
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
        elif by in {"configuration", "representation", "strategy", "model", "instance", "task"}:
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
