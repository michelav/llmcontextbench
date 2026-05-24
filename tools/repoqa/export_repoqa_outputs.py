#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    args = parse_args()
    responses_path = Path(args.responses).expanduser().resolve()
    dataset_root = Path(args.dataset_root).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    rows = read_jsonl(responses_path)
    trials_by_id = read_trials_by_id(Path(args.trials).expanduser().resolve()) if args.trials else {}

    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in rows:
        merged = merge_trial_data(row, trials_by_id)

        if args.success_only and not is_successful_response(merged):
            skipped.append(skip_record(merged, "response_not_successful"))
            continue

        if args.format and str(merged.get("format") or "") not in set(args.format):
            skipped.append(skip_record(merged, "format_filtered"))
            continue

        if args.strategy and str(merged.get("strategy") or "") not in set(args.strategy):
            skipped.append(skip_record(merged, "strategy_filtered"))
            continue

        instance_id = str(merged.get("instanceId") or merged.get("instance_id") or "").strip()
        if not instance_id:
            skipped.append(skip_record(merged, "missing_instance_id"))
            continue

        native_task_path = dataset_root / "context" / instance_id / "native_task.json"
        if not native_task_path.exists():
            skipped.append(skip_record(merged, f"missing_native_task:{native_task_path}"))
            continue

        response_text = response_text_from_row(merged)
        if response_text is None:
            skipped.append(skip_record(merged, "missing_response_text"))
            continue

        native_task = read_json(native_task_path)
        exported.append(build_repoqa_output_row(native_task=native_task, response=merged, response_text=response_text))

    if not exported:
        raise SystemExit(f"No RepoQA output rows were exported. Skipped {len(skipped)} rows.")

    written = write_outputs(exported=exported, output_path=output_path, split=args.split)

    if args.skipped_output:
        write_jsonl(Path(args.skipped_output).expanduser().resolve(), skipped)

    print(f"Read responses: {len(rows)}")
    print(f"Exported RepoQA rows: {len(exported)}")
    print(f"Skipped rows: {len(skipped)}")
    for path, count in written:
        print(f"Wrote {count} rows -> {path}")

    raw_dataset_path = find_raw_dataset_path(dataset_root)
    raw_arg = raw_dataset_path if raw_dataset_path is not None else dataset_root / "raw" / "repoqa-<version>.json[.gz]"
    print("\nNext examples:")
    for path, _ in written[:3]:
        print(
            "  tools/repoqa/repoqa_python -m repoqa.compute_score "
            f"--model_output_path {path} --dataset_path {raw_arg}"
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export CTXBench responses.jsonl into RepoQA-compatible model-output JSONL. "
            "Each output row is native_task.json plus output=[ctxbench response]."
        )
    )
    parser.add_argument("--responses", required=True, help="Path to CTXBench responses.jsonl.")
    parser.add_argument("--dataset-root", required=True, help="Path to generated CTXBench RepoQA dataset root.")
    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output JSONL file or directory. If --split is set, this must be a directory. "
            "If --split is not set, all rows are written to this JSONL file."
        ),
    )
    parser.add_argument(
        "--trials",
        default=None,
        help="Optional path to trials.jsonl. Used to fill metadata if responses are incomplete.",
    )
    parser.add_argument(
        "--format",
        action="append",
        default=[],
        help="Only export responses with this CTXBench format. Can be repeated.",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        default=[],
        help="Only export responses with this CTXBench strategy. Can be repeated.",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="Write one RepoQA JSONL per model/strategy/format combination.",
    )
    parser.add_argument(
        "--success-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export only successful CTXBench responses. Default: true.",
    )
    parser.add_argument(
        "--skipped-output",
        default=None,
        help="Optional JSONL file with skipped rows and reasons.",
    )
    return parser.parse_args()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on {path}:{line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object on {path}:{line_number}")
            rows.append(payload)
    return rows


def read_trials_by_id(path: Path) -> dict[str, dict[str, Any]]:
    trials = read_jsonl(path)
    indexed: dict[str, dict[str, Any]] = {}
    for trial in trials:
        trial_id = str(trial.get("trialId") or trial.get("id") or "").strip()
        if trial_id:
            indexed[trial_id] = trial
    return indexed


def merge_trial_data(response: dict[str, Any], trials_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    trial_id = str(response.get("trialId") or response.get("id") or "").strip()
    trial = trials_by_id.get(trial_id, {})
    if not trial:
        return dict(response)
    merged = dict(trial)
    merged.update(response)
    # Preserve nested metadata from both if present.
    trial_metadata = trial.get("metadata") if isinstance(trial.get("metadata"), dict) else {}
    response_metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    if trial_metadata or response_metadata:
        merged["metadata"] = {**trial_metadata, **response_metadata}
    return merged


def is_successful_response(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    error_message = row.get("errorMessage") or row.get("error")
    if error_message:
        return False
    return status in {"", "success", "completed", "ok"}


def response_text_from_row(row: dict[str, Any]) -> str | None:
    for key in ("response", "answer", "output", "text"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    result = row.get("result")
    if isinstance(result, dict):
        return response_text_from_row(result)
    return None


def build_repoqa_output_row(*, native_task: dict[str, Any], response: dict[str, Any], response_text: str) -> dict[str, Any]:
    row = dict(native_task)
    row["output"] = [response_text]
    row["ctxbench"] = {
        "trialId": response.get("trialId") or response.get("id"),
        "experimentId": response.get("experimentId"),
        "instanceId": response.get("instanceId"),
        "taskId": response.get("taskId"),
        "modelId": response.get("modelId"),
        "modelName": response.get("model") or response.get("modelName"),
        "provider": response.get("provider"),
        "strategy": response.get("strategy"),
        "format": response.get("format"),
        "repeatIndex": response.get("repeatIndex"),
        "usage": response.get("usage", {}),
        "metricsSummary": response.get("metricsSummary", {}),
    }
    return row


def write_outputs(*, exported: list[dict[str, Any]], output_path: Path, split: bool) -> list[tuple[Path, int]]:
    if not split:
        if output_path.suffix != ".jsonl":
            raise SystemExit("When --split is not used, --output must be a .jsonl file.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_path, exported)
        return [(output_path, len(exported))]

    output_path.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in exported:
        groups[group_label(row)].append(row)

    written: list[tuple[Path, int]] = []
    for label, rows in sorted(groups.items()):
        path = output_path / f"{label}.jsonl"
        write_jsonl(path, rows)
        written.append((path, len(rows)))
    return written


def group_label(row: dict[str, Any]) -> str:
    ctxbench = row.get("ctxbench") if isinstance(row.get("ctxbench"), dict) else {}
    model = ctxbench.get("modelId") or ctxbench.get("modelName") or "model"
    strategy = ctxbench.get("strategy") or "strategy"
    fmt = ctxbench.get("format") or "format"
    return slug("__".join([str(model), str(strategy), str(fmt)]))


def skip_record(row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "reason": reason,
        "trialId": row.get("trialId") or row.get("id"),
        "instanceId": row.get("instanceId"),
        "status": row.get("status"),
        "errorMessage": row.get("errorMessage") or row.get("error"),
        "strategy": row.get("strategy"),
        "format": row.get("format"),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def find_raw_dataset_path(dataset_root: Path) -> Path | None:
    raw_dir = dataset_root / "raw"
    matches = sorted(
        path
        for pattern in ("*.json", "*.json.gz")
        for path in raw_dir.glob(pattern)
        if path.is_file()
    )
    if len(matches) == 1:
        return matches[0]
    return None


def slug(value: str) -> str:
    value = value.strip().replace("/", "_slash_")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
