from __future__ import annotations

import pytest

from ctxbench.benchmark.execution_records import (
    attempts_for_trial,
    begin_attempt,
    execution_lock,
    rebuild_responses,
)
from ctxbench.util.jsonl import write_jsonl


def test_execution_lock_rejects_a_second_writer(tmp_path):
    with execution_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another execution writer"):
            with execution_lock(tmp_path):
                pass


def test_corrupt_attempt_record_is_not_silently_ignored(tmp_path):
    record = begin_attempt(
        tmp_path,
        trial_id="trial-1",
        experiment_id="experiment-1",
        execution_fingerprint="fingerprint",
    )
    # Locate the hashed directory without duplicating the path-key algorithm in the test.
    path = next((tmp_path / "execution-records").glob("*/attempt-000001.json"))
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid execution record"):
        attempts_for_trial(tmp_path, record["trialId"])


def test_rebuild_rejects_attempts_from_a_different_fingerprint(tmp_path):
    write_jsonl(tmp_path / "trials.jsonl", [{"trialId": "trial-1", "experimentId": "experiment-1"}])
    begin_attempt(
        tmp_path,
        trial_id="trial-1",
        experiment_id="experiment-1",
        execution_fingerprint="planned-fingerprint",
    )

    with pytest.raises(ValueError, match="Execution fingerprint mismatch"):
        rebuild_responses(tmp_path, execution_fingerprint="different-fingerprint")
