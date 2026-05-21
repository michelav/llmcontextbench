from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctxbench.cli import build_parser, main


@pytest.mark.legacy_rejection
@pytest.mark.parametrize("command", ["query", "exec"])
def test_legacy_query_and_exec_commands_are_rejected(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([command])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert f"'{command}'" in err


@pytest.mark.legacy_rejection
@pytest.mark.parametrize("flag", ["--question", "--repeat", "--ids"])
def test_legacy_selector_flags_are_rejected(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["execute", flag, "value"])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err
    assert flag in err


@pytest.mark.legacy_rejection
def test_experiment_config_with_legacy_mcp_strategy_is_rejected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    experiment_path = tmp_path / "experiment.json"
    experiment_path.write_text(
        json.dumps(
            {
                "id": "exp_bad_mcp",
                "dataset": str(tmp_path / "dataset"),
                "scope": {"instances": ["cv_demo"], "tasks": ["q_year"]},
                "factors": {
                    "model": [{"provider": "mock", "name": "mock"}],
                    "strategy": ["mcp"],
                    "format": ["json"],
                },
                "execution": {"repeats": 1},
            }
        ),
        encoding="utf-8",
    )

    assert main(["plan", str(experiment_path)]) == 1

    err = capsys.readouterr().err
    assert "Invalid experiment" in err
    assert "unknown strategy: mcp" in err
