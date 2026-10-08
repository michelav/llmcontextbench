from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .types import (
    INLINE_CONFIGURATION, Candidate, Decision, Estimate, EstimateKey, Observation,
    PerformanceEstimate, PolicyState, RequestFeatures, unavailable_estimate,
    validate_candidates,
)


@dataclass(frozen=True)
class PolicyConfig:
    latency_objective_ms: float
    cooldown_requests: int = 5
    material_improvement: float = 0.10

    def __post_init__(self) -> None:
        if not isfinite(self.latency_objective_ms) or self.latency_objective_ms < 0 or type(self.cooldown_requests) is not int or self.cooldown_requests < 0:
            raise ValueError("latency objective and cooldown must be finite and nonnegative")
        if not 0 <= self.material_improvement < 1:
            raise ValueError("material_improvement must be in [0, 1)")


class RouterPolicy:
    """Frozen router: runtime observations are recorded but estimates stay fixed."""

    def __init__(self, state: PolicyState, config: PolicyConfig, *, probes: bool = True):
        self.state = state
        self.config = config
        self.probes = probes

    def observe(self, observation: Observation) -> None:
        self.state.record(observation)

    def decide(self, features: RequestFeatures, candidates: tuple[Candidate, ...]) -> Decision:
        validate_candidates(candidates)
        eligible = tuple(c.configuration_id for c in candidates if c.eligible)
        estimates = {
            cid: self.state.estimates.get(
                EstimateKey(cid, features.size_bin), self.state.calibration.get(
                    EstimateKey(cid, features.size_bin), unavailable_estimate()))
            for cid in eligible
        }
        if not eligible:
            return Decision(features.sequence_index, features, (), estimates, None,
                            "no_eligible_candidate", False, False, candidates=candidates)

        incumbent = self.state.incumbent
        incumbent_eligible = incumbent in eligible
        cooldown = bool(incumbent_eligible and self.state.last_switch_sequence is not None
                        and features.sequence_index - self.state.last_switch_sequence <= self.config.cooldown_requests)
        all_missing = all(estimates[cid].latency_ms.value is None for cid in eligible)
        chosen, reason, criterion = self._best(eligible, estimates)
        if all_missing and incumbent_eligible:
            chosen, reason = incumbent, "objective_attainment_unknown"
        if incumbent_eligible and chosen != incumbent:
            objective_priority = self._meets(estimates[chosen]) and not self._meets(estimates[incumbent])
            if cooldown:
                chosen, reason = incumbent, "incumbent_cooldown"
            elif not objective_priority and not self._materially_better(chosen, incumbent, estimates, criterion):
                chosen, reason = incumbent, "incumbent_retained_below_threshold"
            elif objective_priority:
                reason = "objective_priority"
        elif not incumbent_eligible and incumbent is not None:
            reason = "incumbent_ineligible"

        # Commit only the normal routing decision; probe execution is transient.
        if self.state.incumbent != chosen:
            self.state.incumbent = chosen
            self.state.last_switch_sequence = features.sequence_index
        normal = chosen
        probe = False
        if self.probes and features.sequence_index in {10, 20, 30, 40, 50, 60}:
            alternatives = [cid for cid in eligible if cid != normal]
            if alternatives:
                chosen = min(alternatives, key=_tie_key)
                reason, probe = "scheduled_probe", True
                self.state.probe_count += 1
        latency = estimates[chosen].latency_ms.value
        attainment = "unknown" if latency is None else ("met" if self._meets(estimates[chosen]) else "missed")
        return Decision(features.sequence_index, features, eligible, estimates, chosen, reason,
                        probe, cooldown, normal, attainment, candidates)

    def _meets(self, estimate: PerformanceEstimate) -> bool:
        value = estimate.latency_ms.value
        return value is not None and value <= self.config.latency_objective_ms

    def _best(self, eligible: tuple[str, ...], estimates: dict[str, PerformanceEstimate]) -> tuple[str, str, str]:
        meets = [cid for cid in eligible if self._meets(estimates[cid])]
        if meets:
            chosen = min(meets, key=lambda cid: (_missing_last(estimates[cid].total_tokens), _tie_key(cid)))
            return chosen, "lowest_estimated_tokens_within_latency_objective", "tokens"
        chosen = min(eligible, key=lambda cid: (_missing_last(estimates[cid].latency_ms), _tie_key(cid)))
        reason = "objective_attainment_unknown" if estimates[chosen].latency_ms.value is None else "lowest_estimated_latency_objective_missed"
        return chosen, reason, "latency"

    def _materially_better(self, candidate: str, incumbent: str,
                           estimates: dict[str, PerformanceEstimate], criterion: str) -> bool:
        def value(cid: str) -> float | None:
            return (estimates[cid].total_tokens if criterion == "tokens" else estimates[cid].latency_ms).value
        new, old = value(candidate), value(incumbent)
        if new is None:
            return False
        if old is None:
            return True
        return new < old and new <= old * (1 - self.config.material_improvement)


class AdaptivePolicy(RouterPolicy):
    def observe(self, observation: Observation) -> None:
        self.state.record(observation)
        self.state.update(EstimateKey(observation.configuration_id, observation.size_bin))


class FixedPolicy:
    """Fixed arm: record observations, never update estimates or substitute actions."""

    def __init__(self, state: PolicyState, configuration_id: str):
        self.state = state
        self.configuration_id = configuration_id

    def observe(self, observation: Observation) -> None:
        self.state.record(observation)

    def decide(self, features: RequestFeatures, candidates: tuple[Candidate, ...]) -> Decision:
        validate_candidates(candidates)
        eligible = tuple(c.configuration_id for c in candidates if c.eligible)
        selected = self.configuration_id if self.configuration_id in eligible else None
        reason = "fixed_arm" if selected else "fixed_configuration_ineligible"
        return Decision(features.sequence_index, features, eligible, {}, selected, reason,
                        False, False, selected, candidates=candidates)


def _tie_key(cid: str) -> tuple[bool, str]:
    return cid != INLINE_CONFIGURATION, cid


def _missing_last(estimate: Estimate) -> tuple[bool, float]:
    return estimate.value is None, estimate.value if estimate.value is not None else float("inf")
