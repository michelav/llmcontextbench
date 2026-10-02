from __future__ import annotations

from dataclasses import dataclass

from .types import Candidate, Decision, Estimate, EstimateKey, PerformanceEstimate, PolicyState, Provenance, RequestFeatures


@dataclass(frozen=True)
class PolicyConfig:
    latency_objective_ms: float
    cooldown_requests: int = 5
    material_improvement: float = 0.10

    def __post_init__(self) -> None:
        if self.latency_objective_ms < 0 or self.cooldown_requests < 0:
            raise ValueError("latency objective and cooldown must be nonnegative")
        if not 0 <= self.material_improvement < 1:
            raise ValueError("material_improvement must be in [0, 1)")


class RouterPolicy:
    """Deterministic selector; it consumes only candidates and permitted features."""

    def __init__(self, state: PolicyState, config: PolicyConfig, *, adaptive: bool = False,
                 probes: bool = True):
        self.state = state
        self.config = config
        self.adaptive = adaptive
        self.probes = probes

    def decide(self, features: RequestFeatures, candidates: tuple[Candidate, ...]) -> Decision:
        eligible = tuple(c.configuration_id for c in candidates if c.eligible)
        estimates = {
            cid: self.state.estimates.get(
                EstimateKey(cid, features.size_bin), self.state.calibration.get(
                    EstimateKey(cid, features.size_bin), _unavailable_estimate()
                )
            ) for cid in eligible
        }
        if not eligible:
            return Decision(features.sequence_index, features, (), estimates, None, "no_eligible_candidate", False, False)

        chosen, reason, criterion = self._best(eligible, estimates)
        incumbent_eligible = self.state.incumbent in eligible
        cooldown = bool(incumbent_eligible and self.state.last_switch_sequence is not None
                        and features.sequence_index - self.state.last_switch_sequence <= self.config.cooldown_requests)
        if incumbent_eligible and chosen != self.state.incumbent:
            if cooldown:
                chosen, reason = self.state.incumbent, "incumbent_cooldown"
            elif not self._materially_better(chosen, self.state.incumbent, estimates, criterion):
                chosen, reason = self.state.incumbent, "incumbent_retained_below_threshold"
        elif not incumbent_eligible and self.state.incumbent is not None:
            reason = "incumbent_ineligible"

        probe = self.probes and features.sequence_index in {10, 20, 30, 40, 50, 60}
        if probe:
            alternatives = [cid for cid in eligible if cid != chosen]
            if alternatives:
                chosen = sorted(alternatives, key=lambda cid: (cid != "inline", cid))[0]
                reason = "scheduled_probe"
                self.state.probe_count += 1
        if self.state.incumbent != chosen:
            self.state.incumbent = chosen
            self.state.last_switch_sequence = features.sequence_index
        return Decision(features.sequence_index, features, eligible, estimates, chosen, reason, probe, cooldown)

    def _best(self, eligible: tuple[str, ...], estimates: dict[str, PerformanceEstimate]) -> tuple[str, str, str]:
        meets = [cid for cid in eligible if _value(estimates[cid].latency_ms) is not None
                 and _value(estimates[cid].latency_ms) <= self.config.latency_objective_ms]
        if meets:
            chosen = min(meets, key=lambda cid: (_missing_last(estimates[cid].total_tokens), cid != "inline", cid))
            return chosen, "lowest_estimated_tokens_within_latency_objective", "tokens"
        chosen = min(eligible, key=lambda cid: (_missing_last(estimates[cid].latency_ms), cid != "inline", cid))
        return chosen, "lowest_estimated_latency_objective_missed", "latency"

    def _materially_better(self, candidate: str, incumbent: str,
                           estimates: dict[str, PerformanceEstimate], criterion: str) -> bool:
        estimate = lambda cid: estimates[cid].total_tokens if criterion == "tokens" else estimates[cid].latency_ms
        new, old = _value(estimate(candidate)), _value(estimate(incumbent))
        if new is None:
            return False
        if old is None:
            return True
        return new <= old * (1 - self.config.material_improvement)


class AdaptivePolicy(RouterPolicy):
    def __init__(self, state: PolicyState, config: PolicyConfig):
        super().__init__(state, config, adaptive=True, probes=True)


class FixedPolicy:
    """Fixed configuration arm. It records observations but never probes or updates."""

    def __init__(self, state: PolicyState, configuration_id: str):
        self.state = state
        self.configuration_id = configuration_id

    def decide(self, features: RequestFeatures, candidates: tuple[Candidate, ...]) -> Decision:
        eligible = tuple(c.configuration_id for c in candidates if c.eligible)
        selected = self.configuration_id if self.configuration_id in eligible else None
        reason = "fixed_arm" if selected else "fixed_configuration_ineligible"
        return Decision(features.sequence_index, features, eligible, {}, selected, reason, False, False)


def _value(estimate: Estimate) -> float | None:
    return estimate.value


def _missing_last(estimate: Estimate) -> tuple[bool, float]:
    return (estimate.value is None, estimate.value if estimate.value is not None else float("inf"))


def _unavailable_estimate() -> PerformanceEstimate:
    missing = Estimate(None, Provenance.UNAVAILABLE, 0)
    return PerformanceEstimate(missing, missing)
