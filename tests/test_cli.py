import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ctxbench.cli import _selector_from_args, build_parser, main


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_cli_parser_uses_ctxbench_prog_name():
    parser = build_parser()

    assert parser.prog == "ctxbench"
    help_output = parser.format_help()
    assert "usage: ctxbench" in help_output
    assert "CTXBench benchmark CLI" in help_output


def test_public_cli_exposes_execute_command_in_help():
    parser = build_parser()

    help_output = parser.format_help()
    assert "dataset" in help_output
    assert "execute" in help_output
    assert "plan" in help_output
    assert "eval" in help_output
    assert "export" in help_output
    assert "metrics" in help_output
    assert "status" in help_output


def test_public_cli_registers_only_target_subcommands():
    parser = build_parser()

    subparser_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparser_action.choices) == {"dataset", "plan", "execute", "eval", "export", "metrics", "status"}


def test_metrics_help_exposes_artifact_options(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["metrics", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usage: ctxbench metrics" in out
    assert "--output" in out
    assert "--group-by" in out
    assert "--execution-status" in out
    assert "--evaluation-status" in out
    assert "--force" in out


def test_execute_help_uses_target_public_terms(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["execute", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "usage: ctxbench execute" in out
    assert "Path to trials.jsonl" in out
    assert "responses already exist" in out


def test_execute_help_uses_target_selector_flags(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["execute", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--task" in out
    assert "--repetition" in out
    assert "--trial" in out


def test_execute_parser_maps_target_selector_flags():
    parser = build_parser()

    args = parser.parse_args(
        [
            "execute",
            "--task", "q_year,q_summary",
            "--repetition", "1,2",
            "--trial", "run-a,run-b",
            "--not-task", "q_skip",
            "--not-repetition", "3",
        ]
    )
    selector = _selector_from_args(args)

    assert selector.task == ("q_year", "q_summary")
    assert selector.repetition == (1, 2)
    assert selector.trial_id == ("run-a", "run-b")
    assert selector.not_task == ("q_skip",)
    assert selector.not_repetition == (3,)


def test_pyproject_exposes_ctxbench_script_only():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]

    assert scripts["ctxbench"] == "ctxbench.cli:main"
    assert set(scripts) == {"ctxbench"}


def test_flake_exposes_ctxbench_binary_and_app():
    flake = (REPO_ROOT / "flake.nix").read_text(encoding="utf-8")

    assert 'name = "ctxbench";' in flake
    assert '"$out/bin/ctxbench"' in flake
    assert 'program = "${ctxbenchPkg}/bin/ctxbench";' in flake
    assert '--add-flags "ctxbench.cli"' in flake


def test_plan_writes_trials_jsonl_with_target_fields(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"

    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0

    trials_path = output_dir / "trials.jsonl"
    assert trials_path.exists()
    assert {path.name for path in output_dir.glob("*.jsonl")} == {"trials.jsonl"}

    rows = [json.loads(line) for line in trials_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    first = rows[0]
    assert {"trialId", "taskId"} <= set(first)
    assert first["metadata"]["taskId"] in {"q_year", "q_summary"}
    assert {"canonicalId", "taskId", "instanceId", "provider", "modelId", "modelName", "strategy", "format", "repeatIndex"} <= set(first["metadata"])


def test_execute_writes_responses_jsonl_with_target_fields(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"

    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0
    assert main(["execute", str(output_dir / "trials.jsonl")]) == 0

    responses_path = output_dir / "responses.jsonl"
    assert responses_path.exists()
    assert {path.name for path in output_dir.glob("*.jsonl")} == {"responses.jsonl", "trials.jsonl"}

    rows = [json.loads(line) for line in responses_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows
    first = rows[0]
    assert {"trialId", "taskId", "response"} <= set(first)
    assert first["metadata"]["taskId"] in {"q_year", "q_summary"}
    assert {"canonicalId", "taskId", "instanceId", "provider", "modelId", "modelName", "strategy", "format", "repeatIndex"} <= set(first["metadata"])


def test_plan_verbose_emits_structured_logs_to_stderr(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"

    assert main(["plan", str(experiment_path), "--output", str(output_dir), "--verbose"]) == 0

    captured = capsys.readouterr()
    assert "Planned " in captured.out
    assert "phase=PLAN eventName=experiment.loaded" in captured.err
    assert "phase=PLAN eventName=trial.prepared" in captured.err


def test_execute_verbose_emits_trial_context_to_stderr(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"
    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0
    capsys.readouterr()

    assert main(["execute", str(output_dir / "trials.jsonl"), "--verbose", "--task", "q_year"]) == 0

    captured = capsys.readouterr()
    assert "Processed 1 trial(s)" in captured.out
    assert "phase=EXECUTE eventName=trial.response.started" in captured.err
    assert "phase=EXECUTE eventName=trial.response.completed" in captured.err
    assert "trialId=" in captured.err
    assert "taskId=q_year" in captured.err
    assert "modelId=mock" in captured.err
    assert "modelName=mock" in captured.err
    assert "strategy=inline" in captured.err
    assert "format=json" in captured.err
    assert "repeatIndex=1" in captured.err


def test_execute_non_verbose_suppresses_info_logs(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"
    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0
    capsys.readouterr()

    assert main(["execute", str(output_dir / "trials.jsonl"), "--task", "q_year"]) == 0

    captured = capsys.readouterr()
    assert "Processed 1 trial(s)" in captured.out
    assert "phase=EXECUTE eventName=" not in captured.err


def test_eval_missing_context_skip_emits_structured_warning(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    output_dir = tmp_path / "planned"
    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0
    assert main(["execute", str(output_dir / "trials.jsonl"), "--task", "q_year"]) == 0
    blocks_path = tmp_path / "dataset" / "context" / "cv_demo" / "blocks.json"
    blocks_path.write_text(json.dumps({}), encoding="utf-8")
    capsys.readouterr()

    assert main(["eval", str(output_dir / "responses.jsonl"), "--task", "q_year"]) == 0

    captured = capsys.readouterr()
    assert "[WARN] phase=EVAL eventName=evaluation.job.skipped" in captured.err
    assert "trialId=" in captured.err
    assert "taskId=q_year" in captured.err
    assert "missingBlocks=summary" in captured.err


def test_export_filter_failure_uses_structured_stderr_error(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    output_dir = tmp_path / "planned"
    assert main(["plan", str(experiment_path), "--output", str(output_dir)]) == 0
    assert main(["execute", str(output_dir / "trials.jsonl"), "--task", "q_year"]) == 0
    capsys.readouterr()

    assert main(["export", str(output_dir / "evals.jsonl"), "--by", "bad"]) == 1

    captured = capsys.readouterr()
    assert "[ERROR]" not in captured.out
    assert "[ERROR] phase=EXPORT eventName=export.failed" in captured.err
    assert "Invalid --by value" in captured.err


def write_mock_experiment(path: Path, *, evaluation_enabled: bool = True) -> Path:
    dataset_root = path.parent / "dataset"
    instance_dir = dataset_root / "context" / "cv_demo"
    instance_dir.mkdir(parents=True, exist_ok=True)

    (dataset_root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "version": "0.1.0",
                "tasks": [
                    {
                        "id": "q_year",
                        "statement": "In which year did the researcher obtain their PhD?",
                        "tags": ["objective", "simple"],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary"],
                    },
                    {
                        "id": "q_summary",
                        "statement": "Summarize the main research areas for {researcher_name}.",
                        "tags": ["subjective", "simple"],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary", "research"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "version": "0.1.0",
                "instances": [
                    {
                        "instanceId": "cv_demo",
                        "contextBlocks": "context/cv_demo/blocks.json",
                        "tasks": [
                            {"id": "q_year"},
                            {
                                "id": "q_summary",
                                "parameters": {"researcher_name": "CV Demo"},
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(
        json.dumps(
            {
                "answers": {"q_year": 2018},
                "summary": {"text": "Researcher in software engineering."},
                "research": {"areas": ["software engineering", "distributed systems"]},
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "raw.html").write_text("ANSWER[q_year]: 2018\n", encoding="utf-8")
    (instance_dir / "clean.html").write_text("ANSWER[q_year]: 2018\n", encoding="utf-8")
    (instance_dir / "blocks.json").write_text(
        json.dumps(
            {
                "summary": "Researcher in software engineering.",
                "research": "Works with distributed systems.",
            }
        ),
        encoding="utf-8",
    )

    path.write_text(
        json.dumps(
            {
                "id": "exp_mock_v2",
                "output": "outputs",
                "dataset": str(dataset_root.resolve()),
                "scope": {"instances": ["cv_demo"], "tasks": ["q_year", "q_summary"]},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["inline"],
                    "format": ["json"],
                },
                "params": {"common": {"temperature": 0}},
                "evaluation": {
                    "enabled": evaluation_enabled,
                    "judges": [{"provider": "mock", "model": "mock", "temperature": 0}],
                },
                "trace": {
                    "enabled": True,
                    "writeFiles": True,
                    "save_raw_response": True,
                    "save_tool_calls": True,
                    "save_usage": True,
                    "save_errors": True,
                },
                "execution": {"repeats": 1},
                "artifacts": {
                    "writeJsonl": True,
                    "writeIndividualJson": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def add_mock_instance(dataset_root: Path, instance_id: str, *, researcher_name: str) -> None:
    source_instance_dir = dataset_root / "context" / "cv_demo"
    instance_dir = dataset_root / "context" / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)

    parsed_payload = json.loads((source_instance_dir / "parsed.json").read_text(encoding="utf-8"))
    (instance_dir / "parsed.json").write_text(json.dumps(parsed_payload), encoding="utf-8")
    (instance_dir / "raw.html").write_text((source_instance_dir / "raw.html").read_text(encoding="utf-8"), encoding="utf-8")
    (instance_dir / "clean.html").write_text((source_instance_dir / "clean.html").read_text(encoding="utf-8"), encoding="utf-8")
    (instance_dir / "blocks.json").write_text((source_instance_dir / "blocks.json").read_text(encoding="utf-8"), encoding="utf-8")

    task_instances_path = dataset_root / "tasks.instance.json"
    questions_instance_payload = json.loads(task_instances_path.read_text(encoding="utf-8"))
    questions_instance_payload["instances"].append(
        {
            "instanceId": instance_id,
            "contextBlocks": f"context/{instance_id}/blocks.json",
            "tasks": [
                {"id": "q_year"},
                {
                    "id": "q_summary",
                    "parameters": {"researcher_name": researcher_name},
                },
            ],
        }
    )
    task_instances_path.write_text(json.dumps(questions_instance_payload), encoding="utf-8")


def _jsonl_rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _plan_to_root(experiment_path: Path, output_root: Path) -> Path:
    assert main(["plan", str(experiment_path), "--output", str(output_root)]) == 0
    trials_path = output_root / "trials.jsonl"
    assert trials_path.exists()
    assert (output_root / "manifest.json").exists()
    return trials_path


def _execute_trials(trials_path: Path, *extra_args: str) -> Path:
    assert main(["execute", str(trials_path), *extra_args]) == 0
    responses_path = trials_path.parent / "responses.jsonl"
    assert responses_path.exists()
    return responses_path


def test_plan_writes_trials_with_scope_and_target_fields(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json")
    output_root = tmp_path / "planned"

    trials_path = _plan_to_root(experiment_path, output_root)

    rows = _jsonl_rows(trials_path)
    assert len(rows) == 2
    first = rows[0]
    assert first["taskId"] in {"q_year", "q_summary"}
    assert first["instanceId"] == "cv_demo"
    assert first["modelId"] == "mock"
    assert first["validationType"] == "judge"
    assert first["contextBlocks"] in (["summary"], ["summary", "research"])
    assert "dataset" in first
    summary = next(row for row in rows if row["taskId"] == "q_summary")
    assert summary["taskStatement"] == "Summarize the main research areas for CV Demo."
    assert summary["parameters"] == {"researcher_name": "CV Demo"}


def test_plan_rejects_duplicate_model_ids(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json")
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["factors"]["model"] = [
        {"id": "same", "provider": "mock", "name": "mock-a"},
        {"id": "same", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["plan", str(experiment_path)]) == 1


def test_plan_includes_tasks_without_instance_override(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json")
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    task_instances_path = Path(payload["dataset"]) / "tasks.instance.json"
    question_instances = json.loads(task_instances_path.read_text(encoding="utf-8"))
    question_instances["instances"][0]["tasks"] = [
        {
            "id": "q_summary",
            "parameters": {"researcher_name": "CV Demo"},
        }
    ]
    task_instances_path.write_text(json.dumps(question_instances), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "planned")

    rows = _jsonl_rows(trials_path)
    assert len(rows) == 2
    assert {row["taskId"] for row in rows} == {"q_year", "q_summary"}
    year = next(row for row in rows if row["taskId"] == "q_year")
    assert year["taskStatement"] == "In which year did the researcher obtain their PhD?"
    assert year["parameters"] == {}


def test_plan_warns_and_uses_empty_string_for_missing_template_parameter(tmp_path, capsys):
    dataset_root = tmp_path / "dataset"
    instance_dir = dataset_root / "context" / "cv_demo"
    instance_dir.mkdir(parents=True, exist_ok=True)
    (dataset_root / "tasks.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "version": "0.1.0",
                "tasks": [
                    {
                        "id": "q_missing",
                        "statement": "Summarize the work of {researcher_name}.",
                        "tags": ["subjective"],
                        "validation": {"type": "judge"},
                        "contextBlocks": ["summary"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (dataset_root / "tasks.instance.json").write_text(
        json.dumps(
            {
                "datasetId": "mock-v2",
                "version": "0.1.0",
                "instances": [
                    {
                        "instanceId": "cv_demo",
                        "contextBlocks": "context/cv_demo/blocks.json",
                        "tasks": [{"id": "q_missing"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (instance_dir / "parsed.json").write_text(json.dumps({"summary": {"text": "Research summary"}}), encoding="utf-8")
    (instance_dir / "raw.html").write_text("Research summary\n", encoding="utf-8")
    (instance_dir / "clean.html").write_text("Research summary\n", encoding="utf-8")
    (instance_dir / "blocks.json").write_text(json.dumps({"summary": "Research summary"}), encoding="utf-8")
    experiment_path = tmp_path / "experiment.json"
    experiment_path.write_text(
        json.dumps(
            {
                "id": "exp_missing_template",
                "output": "outputs",
                "dataset": str(dataset_root.resolve()),
                "scope": {"instances": ["cv_demo"], "tasks": ["q_missing"]},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["inline"],
                    "format": ["json"],
                },
                "evaluation": {"enabled": False},
                "trace": {"enabled": False, "writeFiles": True},
                "artifacts": {
                    "writeJsonl": True,
                    "writeIndividualJson": True,
                },
            }
        ),
        encoding="utf-8",
    )

    trials_path = _plan_to_root(experiment_path, tmp_path / "planned")

    payload = _jsonl_rows(trials_path)[0]
    captured = capsys.readouterr()
    assert "Missing task parameter" in captured.err
    assert payload["taskStatement"] == "Summarize the work of ."
    assert payload["parameters"] == {}


def test_plan_ignores_format_for_tool_based_strategies(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json")
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")
    payload["factors"]["strategy"] = ["inline", "local_function", "local_mcp", "remote_mcp"]
    payload["factors"]["format"] = ["json", "html"]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "planned")

    rows = _jsonl_rows(trials_path)
    assert len(rows) == 20
    inline_rows = [row for row in rows if row["strategy"] == "inline"]
    assert len(inline_rows) == 8
    assert {row["format"] for row in inline_rows} == {"json", "html"}
    for strategy_name in ("local_function", "local_mcp", "remote_mcp"):
        strategy_rows = [row for row in rows if row["strategy"] == strategy_name]
        assert len(strategy_rows) == 4
        assert {row["format"] for row in strategy_rows} == {"json"}


def test_execute_force_reexecutes_and_overwrites_responses(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    trials_path = _plan_to_root(experiment_path, tmp_path / "planned")
    responses_path = _execute_trials(trials_path)

    first_payload = next(row for row in _jsonl_rows(responses_path) if row["taskId"] == "q_year")
    assert first_payload["response"] == "2018"

    parsed_path = tmp_path / "dataset" / "context" / "cv_demo" / "parsed.json"
    parsed_payload = json.loads(parsed_path.read_text(encoding="utf-8"))
    parsed_payload["answers"]["q_year"] = 2020
    parsed_path.write_text(json.dumps(parsed_payload), encoding="utf-8")

    _execute_trials(trials_path, "--force")
    second_payload = next(row for row in _jsonl_rows(responses_path) if row["taskId"] == "q_year")
    assert second_payload["response"] == "2020"


def test_execute_writes_responses_inside_plan_output_root(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    expanded_root = tmp_path / "expanded"

    trials_path = _plan_to_root(experiment_path, expanded_root)
    responses_path = _execute_trials(trials_path)

    assert responses_path == expanded_root / "responses.jsonl"


def test_execute_selector_filters_by_model_id(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path, "--model", "m1")

    rows = _jsonl_rows(responses_path)
    assert len(rows) == 4
    assert {row["modelId"] for row in rows} == {"m1"}
    assert {row["model"] for row in rows} == {"mock-a"}


def test_execute_selector_filters_by_model_name(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path, "--model", "mock-b")

    rows = _jsonl_rows(responses_path)
    assert len(rows) == 4
    assert {row["modelId"] for row in rows} == {"m2"}
    assert {row["model"] for row in rows} == {"mock-b"}


def test_execute_selector_excludes_instance_for_selected_model(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path, "--model", "m1", "--not-instance", "cv_demo")

    rows = _jsonl_rows(responses_path)
    assert len(rows) == 2
    assert {row["modelId"] for row in rows} == {"m1"}
    assert {row["instanceId"] for row in rows} == {"cv_alt"}
    assert {row["model"] for row in rows} == {"mock-a"}


def test_execute_force_selector_reexecutes_only_selected_model(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    parsed_path = tmp_path / "dataset" / "context" / "cv_demo" / "parsed.json"
    parsed_payload = json.loads(parsed_path.read_text(encoding="utf-8"))
    parsed_payload["answers"]["q_year"] = 2020
    parsed_path.write_text(json.dumps(parsed_payload), encoding="utf-8")

    _execute_trials(trials_path, "--model", "m1", "--force")
    rows = _jsonl_rows(responses_path)
    year_rows = [row for row in rows if row["taskId"] == "q_year" and row["instanceId"] == "cv_demo"]
    assert next(row for row in year_rows if row["modelId"] == "m1")["response"] == "2020"
    assert next(row for row in year_rows if row["modelId"] == "m2")["response"] == "2018"


def test_eval_selector_excludes_instance_for_selected_model(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["scope"]["instances"] = ["cv_demo", "cv_alt"]
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    add_mock_instance(Path(payload["dataset"]), "cv_alt", researcher_name="CV Alt")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        return (
            {
                "correctness": {"rating": "meets", "justification": "ok"},
                "completeness": {"rating": "meets", "justification": "ok"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path), "--model", "m1", "--not-instance", "cv_demo"]) == 0
    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2
    assert {row["instanceId"] for row in rows} == {"cv_alt"}
    response_rows = _jsonl_rows(responses_path)
    expected_trial_ids = {
        row["trialId"]
        for row in response_rows
        if row["modelId"] == "m1" and row["instanceId"] == "cv_alt"
    }
    assert {row["trialId"] for row in rows} == expected_trial_ids


def test_default_artifacts_use_jsonl_as_canonical_source(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload.pop("artifacts", None)
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    assert {path.name for path in trials_path.parent.glob("*.jsonl")} == {"trials.jsonl"}

    responses_path = _execute_trials(trials_path)
    assert responses_path.exists()
    assert {path.name for path in trials_path.parent.glob("*.jsonl")} == {"responses.jsonl", "trials.jsonl"}

    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        return (
            {
                "correctness": {"rating": "meets", "justification": "ok"},
                "completeness": {"rating": "meets", "justification": "ok"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path)]) == 0
    evals_path = trials_path.parent / "evals.jsonl"
    assert evals_path.exists()
    rows = _jsonl_rows(evals_path)
    assert rows
    assert rows[0]["outcome"]["correctness"]["rating"] == "meets"
    assert rows[0]["outcome"]["completeness"]["rating"] == "meets"
    judge_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    assert judge_votes
    assert {row["provider"] for row in judge_votes} == {"mock"}


def test_eval_writes_qualitative_outputs_and_summary(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        return (
            {
                "correctness": {"rating": "meets", "justification": f"Consistent with research section according to {config.model}."},
                "completeness": {"rating": "partially meets", "justification": f"Covers the main areas but remains short according to {config.model}."},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider=config.provider, model=config.model),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path)]) == 0

    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2
    year = next(row for row in rows if row["taskId"] == "q_year")
    judge = next(row for row in rows if row["taskId"] == "q_summary")
    assert year["outcome"]["correctness"]["rating"] == "meets"
    assert year["outcome"]["completeness"]["rating"] == "partial"
    assert judge["outcome"]["correctness"]["rating"] == "meets"
    assert judge["outcome"]["completeness"]["rating"] == "partial"
    judge_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    assert len(judge_votes) == 2
    summary = json.loads((trials_path.parent / "evals-summary.json").read_text(encoding="utf-8"))
    assert len(summary["tasks"]) == 2
    judge_summary = next(item for item in summary["tasks"] if item["taskId"] == "q_summary")
    assert judge_summary["taskId"] == "q_summary"
    assert judge_summary["trialId"]


def test_eval_selector_filters_by_model_id(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["factors"]["model"] = [
        {"id": "m1", "provider": "mock", "name": "mock-a"},
        {"id": "m2", "provider": "mock", "name": "mock-b"},
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        return (
            {
                "correctness": {"rating": "meets", "justification": "ok"},
                "completeness": {"rating": "meets", "justification": "ok"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path), "--model", "m1"]) == 0
    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2
    response_rows = _jsonl_rows(responses_path)
    selected_trial_ids = {row["trialId"] for row in response_rows if row["modelId"] == "m1"}
    assert {row["trialId"] for row in rows} == selected_trial_ids


def test_eval_selector_filters_by_judge_id(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "mock",
            "model": "judge-a",
            "temperature": 0,
            "params": {"id": "juiz-gpt"},
        },
        {
            "provider": "mock",
            "model": "judge-b",
            "temperature": 0,
            "params": {"id": "juiz-claude"},
        },
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    seen: list[tuple[str, str, dict[str, object]]] = []

    def fake_judge_request(**kwargs):
        config = kwargs["config"]
        seen.append((config.provider, config.model, dict(config.params)))
        return (
            {
                "correctness": {"rating": "meets", "justification": "ok"},
                "completeness": {"rating": "meets", "justification": "ok"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider=config.provider, model=config.model),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path), "--judge", "juiz-claude"]) == 0
    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2
    assert seen == [("mock", "judge-b", {"id": "juiz-claude"})] * 2
    judge_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    assert {row["model"] for row in judge_votes} == {"judge-b"}
    assert len(judge_votes) == 2


def test_eval_wait_requires_batch(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    assert main(["eval", str(responses_path), "--wait"]) == 1
    assert "--wait requires --batch." in capsys.readouterr().err


def test_eval_batch_custom_id_matches_anthropic_constraints(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "temperature": 0,
            "params": {"id": "juiz:claude/test"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.commands import eval as eval_module

    custom_ids: list[str] = []

    def fake_submit_evaluation_batch(**kwargs):
        custom_ids.extend(job.custom_id for job in kwargs["jobs"])
        return {
            "kind": "evaluation_batch",
            "batchId": "msgbatch_test",
            "processingStatus": "in_progress",
            "requestCount": len(kwargs["jobs"]),
        }

    monkeypatch.setattr(eval_module, "submit_evaluation_batch", fake_submit_evaluation_batch)

    assert main(["eval", str(responses_path), "--judge", "juiz:claude/test", "--batch"]) == 0
    assert custom_ids
    assert all(len(value) <= 64 for value in custom_ids)
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value) for value in custom_ids)


def test_eval_batch_wait_persists_results(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "temperature": 0,
            "params": {"id": "juiz-claude"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import evaluation_from_judge_payload
    from ctxbench.benchmark.models import EvaluationJudgeInfo, EvaluationTrace
    from ctxbench.commands import eval as eval_module

    def fake_submit_evaluation_batch(**kwargs):
        return {
            "kind": "evaluation_batch",
            "batchId": "msgbatch_test",
            "processingStatus": "in_progress",
            "requestCount": len(kwargs["jobs"]),
        }

    def fake_retrieve_evaluation_batch(**kwargs):
        evaluations = [
            evaluation_from_judge_payload(
                job,
                payload={
                    "correctness": {"rating": "meets", "justification": "ok"},
                    "completeness": {"rating": "meets", "justification": "ok"},
                },
                judge_info=EvaluationJudgeInfo(
                    used=True,
                    role="judge",
                    provider=job.judge.provider,
                    model=job.judge.model,
                    inputTokens=10,
                    outputTokens=2,
                ),
                trace=EvaluationTrace(aiTrace={"batch": {"customId": job.custom_id}}),
            )
            for job in kwargs["jobs"]
        ]
        return {
            "kind": "evaluation_batch",
            "batchId": kwargs["batch_id"],
            "processingStatus": "ended",
        }, evaluations

    monkeypatch.setattr(eval_module, "submit_evaluation_batch", fake_submit_evaluation_batch)
    monkeypatch.setattr(eval_module, "retrieve_evaluation_batch", fake_retrieve_evaluation_batch)

    assert main(["eval", str(responses_path), "--judge", "juiz-claude", "--batch", "--wait"]) == 0
    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2
    judge_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    assert {row["model"] for row in judge_votes} == {"claude-sonnet-4-6"}
    assert {row["outcome"]["correctness"]["rating"] for row in rows} == {"meets"}


def test_eval_batch_retrieves_openai_results(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0,
            "params": {"id": "juiz-gpt"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import build_evaluation_jobs
    from ctxbench.benchmark.evaluation_batch import retrieve_evaluation_batch
    from ctxbench.commands.eval import _load_judges, _load_responses

    jobs = build_evaluation_jobs(
        _load_responses(responses_path),
        judges=_load_judges(trials_path.parent),
    )

    class FakeOpenAIClient:
        def retrieve(self, batch_id):
            return {"id": batch_id, "status": "completed", "output_file_id": "file_test"}

        def results(self, batch_id, batch=None):
            return [
                {
                    "custom_id": job.custom_id,
                    "response": {
                        "status_code": 200,
                        "body": {
                            "output": [
                                {
                                    "content": [
                                        {
                                            "text": json.dumps(
                                                {
                                                    "correctness": {"rating": "meets", "justification": "ok"},
                                                    "completeness": {"rating": "meets", "justification": "ok"},
                                                }
                                            )
                                        }
                                    ]
                                }
                            ],
                            "usage": {"input_tokens": 11, "output_tokens": 3},
                        },
                    },
                    "error": None,
                }
                for job in jobs
            ]

    manifest, evaluations = retrieve_evaluation_batch(
        batch_id="batch_test",
        jobs=jobs,
        source_root=trials_path.parent,
        client=FakeOpenAIClient(),
    )

    assert manifest["status"] == "completed"
    assert manifest["completedTrialCount"] == 2
    assert len(manifest["requests"]) == 2
    first_request = manifest["requests"][0]
    assert set(first_request) == {"customId", "trialId", "taskId", "instanceId"}
    assert first_request["trialId"]
    assert first_request["taskId"] in {"q_year", "q_summary"}
    assert len(evaluations) == 2
    assert {item.items[0].evaluationJudgeProvider for item in evaluations} == {"openai"}
    assert {item.items[0].details["outcome"]["correctness"]["rating"] for item in evaluations} == {"meets"}
    assert {item.items[0].evaluationInputTokens for item in evaluations} == {11}


def test_submit_evaluation_batch_writes_target_manifest_fields(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0,
            "params": {"id": "juiz-gpt"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import build_evaluation_jobs
    from ctxbench.benchmark.evaluation_batch import submit_evaluation_batch
    from ctxbench.commands.eval import _load_judges, _load_responses

    jobs = build_evaluation_jobs(
        _load_responses(responses_path),
        judges=_load_judges(trials_path.parent),
    )

    class FakeOpenAIClient:
        def submit(self, jobs):
            return {
                "id": "batch_test",
                "status": "validating",
                "output_file_id": "file_test",
            }

    manifest = submit_evaluation_batch(
        jobs=jobs,
        source_root=trials_path.parent,
        client=FakeOpenAIClient(),
    )

    assert manifest["batchId"] == "batch_test"
    assert manifest["status"] == "submitted"
    assert manifest["requestCount"] == 2
    assert len(manifest["requests"]) == 2
    first_request = manifest["requests"][0]
    assert set(first_request) == {"customId", "trialId", "taskId", "instanceId"}
    assert first_request["trialId"]
    assert first_request["taskId"] in {"q_year", "q_summary"}


def test_eval_repoqa_scorer_does_not_require_judges(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"trace": {"writeFiles": False}, "evaluation": {"enabled": True}}),
        encoding="utf-8",
    )
    response = {
        "trialId": "repoqa-1",
        "experimentId": "exp-repoqa",
        "dataset": {
            "id": "ctxbench/repoqa",
            "version": "local",
            "origin": str(root / "dataset"),
            "materializedPath": str(root / "dataset"),
        },
        "taskId": "q_repoqa",
        "taskStatement": "Find the target function.",
        "instanceId": "inst-1",
        "provider": "mock",
        "modelId": "mock",
        "model": "mock",
        "strategy": "inline",
        "format": "code",
        "repeatIndex": 1,
        "status": "success",
        "response": "",
        "timing": {
            "startedAt": "2026-01-01T00:00:00Z",
            "finishedAt": "2026-01-01T00:00:01Z",
            "durationMs": 1000,
        },
        "usage": {},
        "metricsSummary": {},
        "validationType": "repoqa-scorer",
        "validationConfig": {"threshold": 0.75, "ignoreComments": True},
        "metadata": {
            "canonicalId": "repoqa-1",
            "taskId": "q_repoqa",
            "instanceId": "inst-1",
            "provider": "mock",
            "modelId": "mock",
            "modelName": "mock",
            "strategy": "inline",
            "format": "code",
            "repeatIndex": 1,
            "validationType": "repoqa-scorer",
            "validationConfig": {"threshold": 0.75, "ignoreComments": True},
        },
    }
    (root / "responses.jsonl").write_text(json.dumps(response) + "\n", encoding="utf-8")

    assert main(["eval", str(root / "responses.jsonl")]) == 0

    rows = _jsonl_rows(root / "evals.jsonl")
    assert rows[0]["evaluationMethod"] == "repoqa-scorer"
    assert rows[0]["details"]["repoqa"]["threshold"] == 0.75
    assert rows[0]["details"]["repoqa"]["ignoreComments"] is True
    assert not (root / "judge_votes.jsonl").exists()
    assert (root / "evals-summary.json").exists()


def test_eval_repoqa_scorer_scores_non_empty_response_without_judges(tmp_path, monkeypatch):
    import ctxbench.adapters.repoqa.evaluation as repoqa_eval

    root = tmp_path / "run"
    dataset_root = root / "dataset"
    instance_dir = dataset_root / "context" / "inst-1"
    raw_dir = dataset_root / "raw"
    root.mkdir()
    instance_dir.mkdir(parents=True)
    raw_dir.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"trace": {"writeFiles": False}, "evaluation": {"enabled": True}}),
        encoding="utf-8",
    )
    (instance_dir / "native_task.json").write_text(
        json.dumps({"language": "python", "repo": "owner/repo", "name": "target_func"}),
        encoding="utf-8",
    )
    (raw_dir / "repoqa.json").write_text(
        json.dumps({"python": [{"repo": "owner/repo", "content": {}, "needles": []}]}),
        encoding="utf-8",
    )
    runner = tmp_path / "repoqa_python"
    helper = tmp_path / "score_response.py"
    runner.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    helper.write_text("# helper\n", encoding="utf-8")

    response = {
        "trialId": "repoqa-1",
        "experimentId": "exp-repoqa",
        "dataset": {
            "id": "ctxbench/repoqa",
            "version": "local",
            "origin": str(dataset_root),
            "materializedPath": str(dataset_root),
        },
        "taskId": "q_repoqa",
        "taskStatement": "Find the target function.",
        "instanceId": "inst-1",
        "provider": "mock",
        "modelId": "mock",
        "model": "mock",
        "strategy": "inline",
        "format": "code",
        "repeatIndex": 1,
        "status": "success",
        "response": "def target_func(): pass",
        "timing": {
            "startedAt": "2026-01-01T00:00:00Z",
            "finishedAt": "2026-01-01T00:00:01Z",
            "durationMs": 1000,
        },
        "usage": {},
        "metricsSummary": {},
        "validationType": "repoqa-scorer",
        "validationConfig": {"threshold": 0.75, "ignoreComments": True},
        "metadata": {
            "canonicalId": "repoqa-1",
            "taskId": "q_repoqa",
            "instanceId": "inst-1",
            "provider": "mock",
            "modelId": "mock",
            "modelName": "mock",
            "strategy": "inline",
            "format": "code",
            "repeatIndex": 1,
            "validationType": "repoqa-scorer",
            "validationConfig": {"threshold": 0.75, "ignoreComments": True},
        },
    }
    (root / "responses.jsonl").write_text(json.dumps(response) + "\n", encoding="utf-8")

    def fake_run(args, *, input, text, capture_output, check):
        request = json.loads(input)
        assert args == [str(runner), str(helper)]
        assert request["native_task"]["name"] == "target_func"
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "verdict": "best_match",
                    "bestTarget": "target_func",
                    "bestSimilarScore": 0.86,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(repoqa_eval, "_load_direct_needle_evaluator", lambda: None)
    monkeypatch.setattr(repoqa_eval, "_repoqa_runner_path", lambda: runner)
    monkeypatch.setattr(repoqa_eval, "_repoqa_helper_path", lambda: helper)
    monkeypatch.setattr(repoqa_eval.subprocess, "run", fake_run)

    assert main(["eval", str(root / "responses.jsonl")]) == 0

    rows = _jsonl_rows(root / "evals.jsonl")
    assert rows[0]["evaluationMethod"] == "repoqa-scorer"
    assert rows[0]["details"]["repoqa"]["bestTarget"] == "target_func"
    assert rows[0]["details"]["repoqa"]["bestSimilarScore"] == 0.86
    assert rows[0]["details"]["repoqa"]["passed"] is True
    assert not (root / "judge_votes.jsonl").exists()


def test_eval_rejects_batch_for_repoqa_scorer(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"evaluation": {"enabled": True}}), encoding="utf-8")
    response = {
        "trialId": "repoqa-1",
        "experimentId": "exp-repoqa",
        "dataset": {"id": "ctxbench/repoqa", "version": "local", "origin": str(root)},
        "taskId": "q_repoqa",
        "taskStatement": "Find the target function.",
        "instanceId": "inst-1",
        "provider": "mock",
        "modelId": "mock",
        "model": "mock",
        "strategy": "inline",
        "format": "code",
        "repeatIndex": 1,
        "status": "success",
        "response": "",
        "timing": {
            "startedAt": "2026-01-01T00:00:00Z",
            "finishedAt": "2026-01-01T00:00:01Z",
            "durationMs": 1000,
        },
        "validationType": "repoqa-scorer",
        "metadata": {
            "canonicalId": "repoqa-1",
            "taskId": "q_repoqa",
            "instanceId": "inst-1",
            "provider": "mock",
            "strategy": "inline",
            "format": "code",
            "repeatIndex": 1,
            "validationType": "repoqa-scorer",
        },
    }
    (root / "responses.jsonl").write_text(json.dumps(response) + "\n", encoding="utf-8")

    assert main(["eval", str(root / "responses.jsonl"), "--batch"]) == 1


def test_eval_batch_retrieves_openai_error_results(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0,
            "params": {"id": "juiz-gpt"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import build_evaluation_jobs
    from ctxbench.benchmark.evaluation_batch import retrieve_evaluation_batch
    from ctxbench.commands.eval import _load_judges, _load_responses

    jobs = build_evaluation_jobs(
        _load_responses(responses_path),
        judges=_load_judges(trials_path.parent),
    )

    class FakeOpenAIClient:
        def retrieve(self, batch_id):
            return {
                "id": batch_id,
                "status": "completed",
                "output_file_id": None,
                "error_file_id": "file_errors",
            }

        def results(self, batch_id, batch=None):
            return [
                {
                    "custom_id": job.custom_id,
                    "response": None,
                    "error": {
                        "code": "invalid_request_error",
                        "message": "The request body was invalid.",
                    },
                }
                for job in jobs
            ]

    manifest, evaluations = retrieve_evaluation_batch(
        batch_id="batch_test",
        jobs=jobs,
        source_root=trials_path.parent,
        client=FakeOpenAIClient(),
    )

    assert manifest["status"] == "completed"
    assert manifest["errorFileId"] == "file_errors"
    assert len(evaluations) == 2
    assert {item.items[0].evaluationJudgeProvider for item in evaluations} == {"openai"}
    assert {item.items[0].details["error"] for item in evaluations} == {"Judge did not return valid JSON."}
    assert {item.items[0].evaluationTrace.error for item in evaluations} == {"Batch request errored."}


def test_eval_batch_openai_submit_uploads_pathlike_jsonl(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "openai",
            "model": "gpt-5.5",
            "temperature": 0,
            "params": {"id": "juiz-gpt"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import build_evaluation_jobs
    from ctxbench.benchmark.evaluation_batch import OpenAIEvaluationBatchClient
    from ctxbench.commands.eval import _load_judges, _load_responses

    jobs = build_evaluation_jobs(
        _load_responses(responses_path),
        judges=_load_judges(trials_path.parent),
    )

    class FakeFiles:
        uploaded_payloads: list[dict[str, object]] = []

        def create(self, *, file, purpose):
            assert isinstance(file, Path)
            assert purpose == "batch"
            rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
            assert rows
            assert {row["url"] for row in rows} == {"/v1/responses"}
            assert {row["method"] for row in rows} == {"POST"}
            self.uploaded_payloads = rows
            return type("Uploaded", (), {"id": "file_test"})()

    class FakeBatches:
        def create(self, **kwargs):
            assert kwargs["input_file_id"] == "file_test"
            assert kwargs["endpoint"] == "/v1/responses"
            assert "temperature" not in kwargs
            return {"id": "batch_test", "status": "validating"}

    client = OpenAIEvaluationBatchClient.__new__(OpenAIEvaluationBatchClient)
    client._client = type("FakeOpenAI", (), {"files": FakeFiles(), "batches": FakeBatches()})()

    batch = client.submit(jobs)

    assert batch["id"] == "batch_test"


def test_eval_batch_retrieves_gemini_results(tmp_path):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=True)
    payload = json.loads(experiment_path.read_text(encoding="utf-8"))
    payload["evaluation"]["judges"] = [
        {
            "provider": "google",
            "model": "gemini-3.1-flash-lite-preview",
            "temperature": 0,
            "params": {"id": "juiz-gemini"},
        }
    ]
    experiment_path.write_text(json.dumps(payload), encoding="utf-8")
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark.evaluation import build_evaluation_jobs
    from ctxbench.benchmark.evaluation_batch import retrieve_evaluation_batch
    from ctxbench.commands.eval import _load_judges, _load_responses

    jobs = build_evaluation_jobs(
        _load_responses(responses_path),
        judges=_load_judges(trials_path.parent),
    )

    class FakeGeminiClient:
        def retrieve(self, batch_id):
            return {"name": batch_id, "state": "JOB_STATE_SUCCEEDED"}

        def results(self, batch_id, batch=None):
            return [
                {
                    "metadata": {"custom_id": job.custom_id},
                    "response": {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": json.dumps(
                                                {
                                                    "correctness": {"rating": "partially meets", "justification": "ok"},
                                                    "completeness": {"rating": "meets", "justification": "ok"},
                                                }
                                            )
                                        }
                                    ]
                                }
                            }
                        ],
                        "usageMetadata": {"promptTokenCount": 13, "candidatesTokenCount": 5},
                    },
                }
                for job in jobs
            ]

    manifest, evaluations = retrieve_evaluation_batch(
        batch_id="batches/test",
        jobs=jobs,
        source_root=trials_path.parent,
        client=FakeGeminiClient(),
    )

    assert manifest["status"] == "completed"
    assert len(evaluations) == 2
    assert {item.items[0].evaluationJudgeProvider for item in evaluations} == {"google"}
    assert {item.items[0].details["outcome"]["correctness"]["rating"] for item in evaluations} == {"partial"}
    assert {item.items[0].evaluationInputTokens for item in evaluations} == {13}


def test_eval_allows_tasks_without_instance_override(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    dataset_root = Path(json.loads(experiment_path.read_text(encoding="utf-8"))["dataset"])
    task_instances_path = dataset_root / "tasks.instance.json"
    payload = json.loads(task_instances_path.read_text(encoding="utf-8"))
    payload["instances"][0]["tasks"] = [
        {"id": "q_summary", "parameters": {"researcher_name": "CV Demo"}}
    ]
    task_instances_path.write_text(json.dumps(payload), encoding="utf-8")

    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    def fake_judge_request(**kwargs):
        return (
            {
                "correctness": {"rating": "meets", "justification": "ok"},
                "completeness": {"rating": "meets", "justification": "ok"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path)]) == 0

    rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(rows) == 2


def test_eval_force_rewrites_existing_evaluation(tmp_path, monkeypatch):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    trials_path = _plan_to_root(experiment_path, tmp_path / "expanded")
    responses_path = _execute_trials(trials_path)

    from ctxbench.benchmark import evaluation as evaluation_module

    state = {"version": 0}

    def fake_judge_request(**kwargs):
        state["version"] += 1
        return (
            {
                "correctness": {"rating": "meets", "justification": f"judge-v{state['version']}"},
                "completeness": {"rating": "meets", "justification": f"judge-v{state['version']}"},
            },
            evaluation_module.EvaluationJudgeInfo(used=True, role="judge", provider="mock", model="mock"),
            evaluation_module.EvaluationTrace(),
        )

    monkeypatch.setattr(evaluation_module, "_judge_request", fake_judge_request)

    assert main(["eval", str(responses_path)]) == 0

    judge_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    first_payload = next(row for row in judge_votes if row["taskId"] == "q_summary")
    assert first_payload["criterias"]["correctness"]["justification"] == "judge-v1"

    state["version"] = 9
    assert main(["eval", str(responses_path), "--force"]) == 0

    second_votes = _jsonl_rows(trials_path.parent / "judge_votes.jsonl")
    second_payload = next(row for row in second_votes if row["taskId"] == "q_summary")
    assert second_payload["criterias"]["correctness"]["justification"] == "judge-v10"
    second_rows = _jsonl_rows(trials_path.parent / "evals.jsonl")
    assert len(second_rows) == 2


def test_eval_rejects_trials_jsonl_with_clear_error(tmp_path, capsys):
    experiment_path = write_mock_experiment(tmp_path / "experiment.json", evaluation_enabled=False)
    trials_path = _plan_to_root(experiment_path, tmp_path / "planned")

    exit_code = main(["eval", str(trials_path)])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Pass responses.jsonl, not trials.jsonl." in err
