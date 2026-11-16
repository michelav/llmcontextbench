"""Provider-free replay helpers for adaptive contract tests."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from ctxbench.adaptive.artifacts import adaptive_plan_from_payload, validate_workflow_manifest
from ctxbench.adaptive.policy import (
    CandidateRef, PrefixSystemState, resolve_policy, validate_decision,
)
from ctxbench.adaptive.workflow import _load_request_records
from ctxbench.util.fs import load_json


def verify_replay(root: str | Path, *, plugin_paths: Sequence[str | Path] = ()) -> list[dict[str, Any]]:
    """Recompute persisted decisions from their causal prefixes without writing or invoking providers."""
    artifact_root = Path(root)
    manifest = validate_workflow_manifest(artifact_root)
    plan = adaptive_plan_from_payload(load_json(artifact_root / "adaptive-plan.json"),
                                      dataset=manifest["dataset"])
    records = _load_request_records(artifact_root)
    observations: list[dict[str, Any]] = []
    memo = None
    differences: list[dict[str, Any]] = []
    for request in plan.requests:
        record = records.get(request.request_id)
        if record is None or not record.get("attempts"):
            continue
        saved = record["attempts"][0].get("decision")
        if not isinstance(saved, dict):
            differences.append({"requestId": request.request_id, "expected": None,
                                "actual": "missing decision"})
            continue
        reference, policy = resolve_policy(
            plan.policy.ref, plan.policy.params,
            plugin_paths=plugin_paths, sources=plan.policy.sources,
        )
        if (reference.policy_id, reference.version, reference.source_digest) != (
            plan.policy.policy_id, plan.policy.version, plan.policy.source_digest
        ):
            raise ValueError("Policy source changed since planning; replay requires the planned policy source.")
        state = PrefixSystemState(
            decision_index=request.sequence_index, observations=observations, memo=memo,
            seed=plan.seed, decision_id=f"{request.request_id}:d1",
        )
        candidates = tuple(CandidateRef(row.candidate_id, row.labels) for row in plan.candidates)
        try:
            actual = validate_decision(policy.decide(candidates, state),
                                       {row.candidate_id for row in plan.candidates})
            actual_data = {"candidateId": actual.candidate_id, "reason": actual.reason,
                           "memo": dict(actual.memo) if actual.memo is not None else None}
        except Exception as exc:
            actual_data = {"error": f"{type(exc).__name__}: {exc}"}
        expected_data = {key: saved.get(key) for key in ("candidateId", "reason", "memo")}
        if actual_data != expected_data:
            differences.append({"requestId": request.request_id,
                                "expected": expected_data, "actual": actual_data})
        observation = (record["attempts"][0].get("observation") or {})
        if record.get("state") in {"delivered", "failed"}:
            observations.append({"candidateId": saved.get("candidateId"),
                                 "status": observation.get("status", "error")})
            memo = saved.get("memo")
    return differences


__all__ = ["verify_replay"]
