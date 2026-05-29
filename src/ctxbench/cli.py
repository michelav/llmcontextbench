from __future__ import annotations

import argparse
import sys

from ctxbench.benchmark.selectors import RunSelector, load_ids_from_file, load_ids_from_stdin
from ctxbench.commands.dataset import fetch_command_from_args, inspect_command_from_args
from ctxbench.commands.eval import eval_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.commands.status import status_command
from ctxbench.util.logging import PhaseLogger


# ---------------------------------------------------------------------------
# Selector argument helpers
# ---------------------------------------------------------------------------

def _add_selector_args(parser: argparse.ArgumentParser, *, include_status: bool = False) -> None:
    parser.add_argument(
        "--model", action="append", default=[], metavar="ID[,ID...]",
        help="Filter by model id or name (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--provider", action="append", default=[], metavar="NAME[,NAME...]",
        help="Filter by provider (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--instance", action="append", default=[], metavar="ID[,ID...]",
        help="Filter by instance id (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--task", action="append", default=[], metavar="ID[,ID...]",
        help="Filter by task id (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--strategy", action="append", default=[], metavar="NAME[,NAME...]",
        help="Filter by strategy (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--format", action="append", default=[], metavar="NAME[,NAME...]",
        help="Filter by context format (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--repetition", action="append", default=[], metavar="N[,N...]",
        help="Filter by repetition index (repeatable, comma-separated)",
    )
    parser.add_argument(
        "--not-model", action="append", default=[], metavar="ID[,ID...]",
        help="Exclude by model id or name",
    )
    parser.add_argument(
        "--not-provider", action="append", default=[], metavar="NAME",
        help="Exclude by provider",
    )
    parser.add_argument(
        "--not-instance", action="append", default=[], metavar="ID",
        help="Exclude by instance id",
    )
    parser.add_argument(
        "--not-task", action="append", default=[], metavar="ID",
        help="Exclude by task id",
    )
    parser.add_argument(
        "--not-strategy", action="append", default=[], metavar="NAME",
        help="Exclude by strategy",
    )
    parser.add_argument(
        "--not-format", action="append", default=[], metavar="NAME",
        help="Exclude by context format",
    )
    parser.add_argument(
        "--not-repetition", action="append", default=[], metavar="N",
        help="Exclude by repetition index",
    )
    parser.add_argument(
        "--trial", metavar="ID[,ID...]|-",
        help="Filter by explicit trial IDs (comma-separated, or '-' to read from stdin)",
    )
    parser.add_argument(
        "--trial-file", metavar="PATH",
        help="Filter by trial IDs listed in a file (one per line)",
    )
    if include_status:
        parser.add_argument(
            "--status", action="append", default=[], metavar="STATUS[,STATUS...]",
            help="Filter by run status (repeatable, comma-separated)",
        )
        parser.add_argument(
            "--not-status", action="append", default=[], metavar="STATUS",
            help="Exclude by run status",
        )


def _parse_multi_str(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    for v in values:
        result.extend(s.strip() for s in v.split(",") if s.strip())
    return tuple(result)


def _parse_multi_int(values: list[str]) -> tuple[int, ...]:
    result: list[int] = []
    for v in values:
        for s in v.split(","):
            s = s.strip()
            if s:
                result.append(int(s))
    return tuple(result)


def _resolve_trial_ids(args: argparse.Namespace) -> tuple[str, ...]:
    ids_arg: str | None = getattr(args, "trial", None)
    ids_file_arg: str | None = getattr(args, "trial_file", None)
    ids: list[str] = []
    if ids_arg == "-":
        ids.extend(load_ids_from_stdin())
    elif ids_arg:
        ids.extend(s.strip() for s in ids_arg.split(",") if s.strip())
    if ids_file_arg:
        ids.extend(load_ids_from_file(ids_file_arg))
    return tuple(ids)


def _selector_from_args(args: argparse.Namespace, *, include_status: bool = False) -> RunSelector:
    return RunSelector(
        model=_parse_multi_str(getattr(args, "model", []) or []),
        provider=_parse_multi_str(getattr(args, "provider", []) or []),
        instance=_parse_multi_str(getattr(args, "instance", []) or []),
        task=_parse_multi_str(getattr(args, "task", []) or []),
        strategy=_parse_multi_str(getattr(args, "strategy", []) or []),
        format=_parse_multi_str(getattr(args, "format", []) or []),
        repetition=_parse_multi_int(getattr(args, "repetition", []) or []),
        status=_parse_multi_str(getattr(args, "status", []) or []) if include_status else (),
        trial_id=_resolve_trial_ids(args),
        not_model=_parse_multi_str(getattr(args, "not_model", []) or []),
        not_provider=_parse_multi_str(getattr(args, "not_provider", []) or []),
        not_instance=_parse_multi_str(getattr(args, "not_instance", []) or []),
        not_task=_parse_multi_str(getattr(args, "not_task", []) or []),
        not_strategy=_parse_multi_str(getattr(args, "not_strategy", []) or []),
        not_format=_parse_multi_str(getattr(args, "not_format", []) or []),
        not_repetition=_parse_multi_int(getattr(args, "not_repetition", []) or []),
        not_status=_parse_multi_str(getattr(args, "not_status", []) or []) if include_status else (),
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctxbench", description="CTXBench benchmark CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── ctxbench dataset ───────────────────────────────────────────────────
    dataset_parser = subparsers.add_parser(
        "dataset", help="Dataset management"
    )
    dataset_sub = dataset_parser.add_subparsers(dest="dataset_command", required=True)
    fetch_parser = dataset_sub.add_parser(
        "fetch", help="Materialize a dataset into the local cache"
    )
    fetch_source_group = fetch_parser.add_mutually_exclusive_group(required=True)
    fetch_source_group.add_argument("--descriptor-url", help="Remote dataset descriptor URL")
    fetch_source_group.add_argument("--descriptor-file", help="Local dataset descriptor path")
    fetch_source_group.add_argument("--dataset-url", help="Remote .tar.gz dataset archive URL")
    fetch_source_group.add_argument("--dataset-file", help="Local .tar.gz dataset archive path")
    fetch_source_group.add_argument("--dataset-dir", help="Local unpacked dataset directory")
    fetch_parser.add_argument("--id", dest="dataset_id", help="Expected dataset identity for opaque archive sources")
    fetch_parser.add_argument("--version", help="Expected datasetVersion for opaque archive sources")
    fetch_parser.add_argument("--sha256", help="Trusted SHA-256 for dataset archive content")
    fetch_parser.add_argument("--sha256-url", help="URL containing trusted SHA-256 for a remote archive")
    fetch_parser.add_argument("--sha256-file", help="Local file containing trusted SHA-256 for a local archive")
    fetch_parser.add_argument("--force", action="store_true", help="Replace conflicting cached materialization after validation")
    fetch_parser.add_argument("--cache-dir", help="Override dataset cache root for this command")
    fetch_parser.set_defaults(func=fetch_command_from_args)
    inspect_parser = dataset_sub.add_parser(
        "inspect", help="Inspect a local or cached dataset reference"
    )
    inspect_parser.add_argument("dataset_ref", help="Dataset reference path or <dataset-id>@<version>")
    inspect_parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON output")
    inspect_parser.add_argument("--cache-dir", help="Override dataset cache root for this command")
    inspect_parser.set_defaults(func=inspect_command_from_args)

    # ── ctxbench plan ──────────────────────────────────────────────────────
    plan_parser = subparsers.add_parser(
        "plan", help="Expand an experiment into trials.jsonl"
    )
    plan_parser.add_argument("path", help="Path to the experiment JSON file")
    plan_parser.add_argument(
        "--output", metavar="DIR",
        help="Override output directory (default: experiment.output/<id>/)",
    )
    plan_parser.add_argument("--cache-dir", help="Override dataset cache root for this command")
    plan_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    plan_parser.add_argument("--progress", action="store_true", help="Show progress bar")
    plan_parser.set_defaults(
        func=lambda args: plan_command(
            args.path,
            output=args.output,
            cache_dir=args.cache_dir,
            verbose=args.verbose,
            progress=args.progress,
        )
    )

    # ── ctxbench execute ───────────────────────────────────────────────────
    execute_parser = subparsers.add_parser(
        "execute", help="Execute trials and collect responses"
    )
    execute_parser.add_argument(
        "trials", nargs="?", default=None,
        help="Path to trials.jsonl (default: ./trials.jsonl)",
    )
    execute_parser.add_argument(
        "--force", action="store_true",
        help="Re-execute even when responses already exist",
    )
    _add_selector_args(execute_parser)
    execute_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    execute_parser.add_argument("--progress", action="store_true", help="Show progress bar")
    execute_parser.set_defaults(
        func=lambda args: execute_command(
            args.trials,
            force=args.force,
            verbose=args.verbose,
            progress=args.progress,
            selector=_selector_from_args(args),
        )
    )

    # ── ctxbench eval ──────────────────────────────────────────────────────
    eval_parser = subparsers.add_parser(
        "eval", help="Evaluate responses using a judge model"
    )
    eval_parser.add_argument(
        "responses", nargs="?", default=None,
        help="Path to responses.jsonl (default: ./responses.jsonl)",
    )
    eval_parser.add_argument(
        "--force", action="store_true",
        help="Re-evaluate even when evaluation results already exist",
    )
    eval_parser.add_argument(
        "--judge", action="append", default=[], metavar="ID",
        help="Select judges by id, model, or provider (repeatable)",
    )
    eval_parser.add_argument(
        "--not-judge", action="append", default=[], metavar="ID",
        help="Exclude judges by id, model, or provider (repeatable)",
    )
    eval_parser.add_argument(
        "--batch", action="store_true",
        help="Submit evaluation using provider batch API",
    )
    eval_parser.add_argument(
        "--batch-id", metavar="ID",
        help="Resume or collect an existing provider batch (implies --batch)",
    )
    eval_parser.add_argument(
        "--wait", action="store_true",
        help="Wait for batch to complete (requires --batch)",
    )
    eval_parser.add_argument(
        "--poll-interval", type=int, default=60, metavar="SECONDS",
        help="Polling interval when using --batch --wait (default: 60)",
    )
    eval_parser.add_argument(
        "--continue-on-error", action="store_true",
        help="Continue evaluating after an item error",
    )
    _add_selector_args(eval_parser, include_status=True)
    eval_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    eval_parser.add_argument("--progress", action="store_true", help="Show progress bar")
    eval_parser.set_defaults(
        func=lambda args: eval_command(
            args.responses,
            force=args.force,
            judge=tuple(args.judge),
            not_judge=tuple(getattr(args, "not_judge", []) or []),
            batch=args.batch,
            batch_id=args.batch_id,
            wait=args.wait,
            poll_interval=args.poll_interval,
            continue_on_error=args.continue_on_error,
            verbose=args.verbose,
            progress=args.progress,
            selector=_selector_from_args(args, include_status=True),
        )
    )

    # ── ctxbench export ────────────────────────────────────────────────────
    export_parser = subparsers.add_parser(
        "export", help="Export evaluations to a derived format"
    )
    export_parser.add_argument(
        "evals", nargs="?", default=None,
        help="Path to evals.jsonl (default: ./evals.jsonl)",
    )
    export_parser.add_argument(
        "--to", default="csv", choices=["csv"], dest="export_format",
        help="Output format (default: csv)",
    )
    export_parser.add_argument(
        "--output", metavar="PATH",
        help="Output file path (default: results.csv next to evals.jsonl)",
    )
    export_parser.add_argument(
        "--by", action="append", default=[], metavar="KEY=VALUE",
        help=(
            "Filter by key=value pair (repeatable). "
            "Valid keys: model, strategy, format, instance"
        ),
    )
    export_parser.add_argument(
        "--id", metavar="TRIAL_ID", dest="run_id",
        help="Show detailed information for a single trial ID",
    )
    _add_selector_args(export_parser, include_status=True)
    export_parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    export_parser.set_defaults(
        func=lambda args: export_command(
            args.evals,
            format=args.export_format,
            output=args.output,
            verbose=args.verbose,
            selector=_selector_from_args(args, include_status=True),
            by=args.by or [],
            run_id=getattr(args, "run_id", None),
        )
    )

    # ── ctxbench status ────────────────────────────────────────────────────
    status_parser = subparsers.add_parser(
        "status", help="Show experiment progress summary"
    )
    status_parser.add_argument(
        "output_dir", nargs="?", default=None,
        help="Experiment output directory (default: current directory)",
    )
    status_parser.add_argument(
        "--by", metavar="FIELD", choices=["model", "strategy", "instance", "task", "judge"],
        help="Break down counts by field",
    )
    status_parser.set_defaults(
        func=lambda args: status_command(args.output_dir, by=getattr(args, "by", None))
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        PhaseLogger(stream=sys.stderr).error("STATUS", "cli.interrupted", "Execution interrupted", code=130)
        return 130
    except Exception as exc:
        PhaseLogger(stream=sys.stderr).error("STATUS", "cli.failed", str(exc), code=1)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
