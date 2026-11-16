from __future__ import annotations

from typing import Sequence

from ctxbench.adaptive.policy import CandidateRef, Decision, SystemState


class RoundRobinPolicy:
    id = "round_robin"
    version = "1"

    def __init__(self, *, candidates: Sequence[str] | None = None):
        if candidates is not None and (
            isinstance(candidates, str) or not candidates
            or any(not isinstance(item, str) or not item for item in candidates)
            or len(set(candidates)) != len(candidates)
        ):
            raise ValueError("candidates must be a non-empty list of unique candidate IDs")
        self.candidate_ids = tuple(candidates) if candidates is not None else None

    def decide(self, candidates: Sequence[CandidateRef], state: SystemState) -> Decision:
        available = {item.candidate_id for item in candidates}
        ids = ([item.candidate_id for item in candidates] if self.candidate_ids is None
               else [item for item in self.candidate_ids if item in available])
        if not ids:
            raise ValueError("round_robin candidate subset does not intersect the catalogue")
        position = int((state.memo or {}).get("position", 0))
        selected = ids[position % len(ids)]
        return Decision(selected, "round robin", {"position": position + 1})
