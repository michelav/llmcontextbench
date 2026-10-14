"""Derive the long64 inline disturbance from a frozen calibration baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from ctxbench.adaptive.recovery import sealed_read
from ctxbench.studies.models import Study
from ctxbench.studies.study import verify_frozen

INLINE = "inline-code-full"
MARGIN_MS = 1000
ROUND_TO_MS = 1000


def select_delay(estimates: dict, configurations: list[str], latency_limit_ms: float) -> tuple[int, list[dict]]:
    """Cross both the limit and the fastest alternative's mean in every bin."""
    if INLINE not in configurations or len(configurations) < 2:
        raise ValueError("latency study requires inline and another configuration")
    bins = sorted(estimates[INLINE])
    if not bins:
        raise ValueError("frozen baseline has no size-bin estimates")
    evidence = []
    for size in bins:
        means = {}
        for cid in configurations:
            row = estimates.get(cid, {}).get(size)
            value = row.get("latencyMs") if row else None
            if (row is None or row.get("successes", 0) < 1 or value is None
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"missing successful latency calibration: {cid}/{size}")
            means[cid] = value
        alternative = min((cid for cid in configurations if cid != INLINE), key=lambda cid: means[cid])
        threshold = max(latency_limit_ms, means[alternative])
        evidence.append({"sizeBin": size, "inlineMeanMs": means[INLINE],
                         "fastestAlternative": alternative,
                         "alternativeMeanMs": means[alternative],
                         "thresholdMs": threshold,
                         "minimumDelayMs": max(0, threshold - means[INLINE] + MARGIN_MS)})
    delay = max(ROUND_TO_MS, math.ceil(max(row["minimumDelayMs"] for row in evidence) / ROUND_TO_MS) * ROUND_TO_MS)
    return delay, evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    definition_path = args.definition.resolve()
    output_path = args.output.resolve()
    selection_path = output_path.with_suffix(".selection.json")
    if output_path.exists() or selection_path.exists():
        parser.error("output or selection record already exists; use a fresh path")
    source = json.loads(definition_path.read_text())
    study = Study.model_validate(source)
    if study.scenarios.get("stationary") != [] or len(study.scenarios.get("inline-delay", [])) != 1:
        parser.error("definition must contain stationary and one inline-delay treatment")
    treatment = study.scenarios["inline-delay"][0]
    if treatment.configuration != INLINE or treatment.scope != "request":
        parser.error("inline-delay must be a request-level inline treatment")
    frozen_path = (definition_path.parent / study.baseline).resolve()
    frozen = sealed_read(frozen_path)
    verify_frozen(frozen, frozen_path)
    configurations = study.configurations or frozen["plan"]["configurations"]
    delay, evidence = select_delay(frozen["estimates"], configurations, study.latencyLimitMs)
    source["baseline"] = os.path.relpath(frozen_path, output_path.parent)
    source["scenarios"]["inline-delay"][0]["delayMs"] = delay
    Study.model_validate(source)
    selection = {"method": "baseline-bin-mean-crossover-v1", "frozenBaseline": str(frozen_path),
                 "frozenSha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                 "latencyLimitMs": study.latencyLimitMs, "marginMs": MARGIN_MS,
                 "roundToMs": ROUND_TO_MS, "delayMs": delay, "bins": evidence}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(source, indent=2) + "\n")
    selection_path.write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps({"definition": str(output_path), "selection": str(selection_path),
                      "delayMs": delay}, indent=2))


if __name__ == "__main__":
    main()
