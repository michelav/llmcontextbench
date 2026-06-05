from __future__ import annotations

from typing import Any

from ctxbench.util.logging import PhaseLogger


_RATING_SCORES = {"meets": 1.0, "partial": 0.5, "misses": 0.0}
_warned_ratings: set[str] = set()
_warned_methods: set[str] = set()


def normalize_primary(evaluation: dict[str, Any] | None, logger: PhaseLogger) -> tuple[str | None, bool | None, float | None]:
    if not evaluation:
        return None, None, None
    method = evaluation.get("evaluationMethod")
    if method == "judge":
        outcome = evaluation.get("outcome") if isinstance(evaluation.get("outcome"), dict) else {}
        correctness = outcome.get("correctness") if isinstance(outcome.get("correctness"), dict) else {}
        completeness = outcome.get("completeness") if isinstance(outcome.get("completeness"), dict) else {}
        c_rating = correctness.get("rating")
        k_rating = completeness.get("rating")
        scores = [_rating_score(c_rating, logger), _rating_score(k_rating, logger)]
        score = sum(scores) / 2.0 if all(item is not None for item in scores) else None
        success = (c_rating == "meets" and k_rating == "meets") if c_rating is not None and k_rating is not None else None
        return "judge_meets", success, score
    if method == "repoqa-scorer":
        details = evaluation.get("details") if isinstance(evaluation.get("details"), dict) else {}
        outcome = details.get("outcome") if isinstance(details.get("outcome"), dict) else {}
        repoqa = details.get("repoqa") if isinstance(details.get("repoqa"), dict) else {}
        passed = outcome.get("passed")
        return (
            "pass",
            passed if isinstance(passed, bool) else None,
            _number(repoqa.get("bestSimilarScore")),
        )
    if method is not None and str(method) not in _warned_methods:
        _warned_methods.add(str(method))
        logger.warn("METRICS", "metrics.evaluation_method.unknown", "Unknown evaluation method", evaluationMethod=method)
    return None, None, None


def _rating_score(value: Any, logger: PhaseLogger) -> float | None:
    if value in _RATING_SCORES:
        return _RATING_SCORES[value]
    if value is not None and str(value) not in _warned_ratings:
        _warned_ratings.add(str(value))
        logger.warn("METRICS", "metrics.judge_rating.unknown", "Unknown judge rating", rating=value)
    return None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

