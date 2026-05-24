from __future__ import annotations

import json
import sys
from typing import Any

from repoqa.compute_score import needle_evaluator


def _read_request() -> dict[str, Any]:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("RepoQA scorer request must be a JSON object.")
    return payload


def main() -> int:
    request = _read_request()
    native_task = request["native_task"]
    verdict, best_target, best_similarity = needle_evaluator(
        request["response"],
        str(native_task["name"]),
        request["repo_info"],
        str(native_task["language"]),
        bool(request["ignore_comments"]),
    )
    json.dump(
        {
            "verdict": str(getattr(verdict, "value", verdict)),
            "bestTarget": best_target,
            "bestSimilarScore": float(best_similarity or 0.0),
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
