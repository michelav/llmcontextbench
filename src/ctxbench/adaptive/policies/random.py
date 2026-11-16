from __future__ import annotations

from typing import Sequence

from ctxbench.adaptive.policy import CandidateRef, Decision, SystemState


class RandomPolicy:
    id = "random"
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
        options = [item.candidate_id for item in candidates
                   if self.candidate_ids is None or item.candidate_id in self.candidate_ids]
        if not options:
            raise ValueError("random policy candidate subset does not intersect the catalogue")
        selected = state.rng().choice(options)
        return Decision(selected, "seeded random choice")
