from __future__ import annotations

from typing import Sequence

from ctxbench.adaptive.policy import CandidateRef, Decision, SystemState


class StaticPolicy:
    id = "static"
    version = "1"

    def __init__(self, *, candidate: str):
        if not isinstance(candidate, str) or not candidate:
            raise ValueError("candidate must be a non-empty candidate ID")
        self.candidate = candidate

    def decide(self, candidates: Sequence[CandidateRef], state: SystemState) -> Decision:
        del state
        return Decision(self.candidate, "static candidate")

    def candidate_targets(self) -> tuple[str, ...]:
        return (self.candidate,)
