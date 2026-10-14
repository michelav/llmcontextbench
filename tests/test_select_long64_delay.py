import pytest

from tools.repoqa.select_long64_delay import select_delay


def test_delay_crosses_limit_and_fastest_alternative_in_every_bin():
    estimates = {
        "inline-code-full": {
            "small": {"latencyMs": 3000, "successes": 4},
            "medium": {"latencyMs": 3200, "successes": 4},
            "large": {"latencyMs": 3300, "successes": 4},
        },
        "local-mcp-default": {
            "small": {"latencyMs": 6400, "successes": 4},
            "medium": {"latencyMs": 6500, "successes": 4},
            "large": {"latencyMs": 6900, "successes": 4},
        },
        "local-mcp-lean": {
            "small": {"latencyMs": 8100, "successes": 3},
            "medium": {"latencyMs": 8000, "successes": 3},
            "large": {"latencyMs": 7500, "successes": 3},
        },
    }
    delay, evidence = select_delay(estimates, list(estimates), 6000)
    assert delay == 5000
    assert len(evidence) == 3
    assert all(row["inlineMeanMs"] + delay >= row["thresholdMs"] + 1000 for row in evidence)


def test_delay_rejects_missing_successful_calibration():
    estimates = {
        "inline-code-full": {"small": {"latencyMs": 3000, "successes": 1}},
        "local-mcp-default": {"small": {"latencyMs": None, "successes": 0}},
    }
    with pytest.raises(ValueError, match="missing successful latency calibration"):
        select_delay(estimates, list(estimates), 6000)
