from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

pytest_plugins = ("tests.fixtures.lattes_provider_free.conftest",)

from ctxbench.commands.dataset import fetch_command, inspect_command
from ctxbench.commands.eval import eval_command
from ctxbench.commands.execute import execute_command
from ctxbench.commands.export import export_command
from ctxbench.commands.plan import plan_command
from ctxbench.util.jsonl import read_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "lattes_provider_free"
DATASET_ROOT = FIXTURE_ROOT / "dataset"
EXPERIMENT_PATH = FIXTURE_ROOT / "experiment.json"
DATASET_ID = "ctxbench/lattes"
DATASET_VERSION = "2026-04-28"
pytestmark = [pytest.mark.workflow, pytest.mark.e2e]


def test_lattes_provider_free_conformance(
    provider_free_lattes_runtime: dict[str, object],
    tmp_path: Path,
    capsys,
) -> None:
    fetch_command(
        DATASET_ID,
        str(DATASET_ROOT),
        DATASET_VERSION,
        cache_dir=tmp_path / "cache",
    )

    inspect_command(
        f"{DATASET_ID}@{DATASET_VERSION}",
        json_output=False,
        cache_dir=tmp_path / "cache",
    )
    inspect_output = capsys.readouterr().out
    assert f"identity: {DATASET_ID}" in inspect_output
    assert f"version: {DATASET_VERSION}" in inspect_output
    assert "conformant: True" in inspect_output

    output_root = tmp_path / "planned"
    assert plan_command(
        str(EXPERIMENT_PATH),
        output=str(output_root),
        cache_dir=tmp_path / "cache",
    ) == 0

    trials = read_jsonl(output_root / "trials.jsonl")
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    assert trials
    assert manifest["dataset"]["id"] == DATASET_ID
    assert manifest["dataset"]["version"] == DATASET_VERSION

    assert execute_command(str(output_root / "trials.jsonl")) == 0
    responses = read_jsonl(output_root / "responses.jsonl")
    assert responses
    assert responses[0]["dataset"]["id"] == DATASET_ID
    assert responses[0]["response"]

    assert eval_command(str(output_root / "responses.jsonl")) == 0
    evals = read_jsonl(output_root / "evals.jsonl")
    votes = read_jsonl(output_root / "judge_votes.jsonl")
    assert evals
    assert votes
    assert evals[0]["dataset"]["id"] == DATASET_ID
    assert evals[0]["outcome"]["correctness"]["rating"] == "meets"

    assert export_command(str(output_root / "evals.jsonl")) == 0
    with (output_root / "results.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["dataset_id"] == DATASET_ID
    assert rows[0]["dataset_version"] == DATASET_VERSION

    responder = provider_free_lattes_runtime["responder"]
    judge = provider_free_lattes_runtime["judge"]
    assert getattr(responder, "calls")
    assert getattr(judge, "calls")
