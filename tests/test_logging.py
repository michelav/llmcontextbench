from __future__ import annotations

from io import StringIO
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ctxbench.util.logging import PhaseLogger, ProgressTracker


def test_structured_event_field_rendering() -> None:
    stream = StringIO()
    logger = PhaseLogger(verbose=True, stream=stream)

    logger.info(
        "EXECUTE",
        "trial.response.completed",
        "Response generated",
        trialId="trial 1",
        modelName='gpt "mini"',
        tags=["alpha", "beta"],
        cached=True,
        omitted_none=None,
        omitted_empty="",
        omitted_list=[],
        omitted_dict={},
    )

    line = stream.getvalue().strip()
    assert line.startswith("[INFO] phase=EXECUTE eventName=trial.response.completed ")
    assert 'trialId="trial 1"' in line
    assert 'modelName="gpt \\"mini\\""' in line
    assert "tags=alpha,beta" in line
    assert "cached=true" in line
    assert "omitted_none" not in line
    assert "omitted_empty" not in line
    assert "omitted_list" not in line
    assert "omitted_dict" not in line


def test_structured_event_severity_gating() -> None:
    stream = StringIO()
    logger = PhaseLogger(verbose=False, stream=stream)

    logger.debug("PLAN", "debug.event", "debug")
    logger.info("PLAN", "info.event", "info")
    logger.warn("PLAN", "warn.event", "warn")
    logger.error("PLAN", "error.event", "error")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[WARN] phase=PLAN eventName=warn.event")
    assert lines[1].startswith("[ERROR] phase=PLAN eventName=error.event")


def test_structured_event_clears_and_redraws_progress() -> None:
    stream = StringIO()
    progress = ProgressTracker(total=2, enabled=True, stream=stream)
    logger = PhaseLogger(verbose=True, progress=progress, stream=stream)
    progress.start()

    logger.info("EXECUTE", "trial.response.started", "Generating response", trialId="trial-1")

    output = stream.getvalue()
    assert "\r" in output
    assert "[INFO] phase=EXECUTE eventName=trial.response.started trialId=trial-1 Generating response" in output
    assert output.rstrip().endswith("0/2")
