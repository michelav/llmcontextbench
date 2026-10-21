"""Authored definitions. Scientific thresholds have no implicit defaults."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StrictInt, Tag, model_validator

PositiveInt = Annotated[StrictInt, Field(gt=0)]


class Definition(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Split(Definition):
    seed: StrictInt
    calibrationTargetsPerLanguage: PositiveInt


class InstanceSplit(Definition):
    """Explicit instance lists (JSON files relative to the definition).

    Calibration entries are instance IDs or {"instance": ID, "weight": w}; weights make the frozen
    estimates weighted means (for strata sampled away from their natural shares). A target's
    instances must all fall on one side.
    """
    calibrationInstances: str
    evaluationInstances: str


class Baseline(Definition):
    schemaVersion: Literal[1] = 1
    experiment: str
    split: Split | InstanceSplit
    sizeProfile: Literal['standard', 'long64'] | None = None
    seeds: list[StrictInt] = Field(min_length=1)
    repeats: PositiveInt
    contextLimit: PositiveInt
    outputReservation: PositiveInt

    @model_validator(mode='after')
    def validate_matrix(self):
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError('duplicate seeds')
        if self.outputReservation >= self.contextLimit:
            raise ValueError('output reservation must be below context limit')
        if (self.sizeProfile is None) == isinstance(self.split, InstanceSplit):
            raise ValueError('sizeProfile is required with an instance split, and only with it')
        return self

class FixedPolicy(Definition):
    type: Literal['fixed']
    configuration: str


class RouterPolicy(Definition):
    type: Literal['router']
    adaptive: bool
    probeInterval: PositiveInt = 10
    cooldownRequests: Annotated[StrictInt, Field(ge=0)] = 5
    updateWindow: PositiveInt = 5
    materialImprovement: Annotated[float, Field(ge=0, lt=1)] = 0.10
    incumbentScope: Literal['global', 'bin'] = 'global'
    estimator: Literal['per-bin-mean', 'pooled-ratio'] = 'per-bin-mean'
    minimumObservations: PositiveInt = 3
    estimateTtlRequests: PositiveInt | None = None
    probeMode: Literal['round-robin', 'targeted'] = 'round-robin'
    avoidedProbeInterval: PositiveInt | None = None
    latencyQuantile: Literal[0.5, 0.75, 0.9, 0.95] | None = None
    switchOnObjectiveMiss: bool = False

    @model_validator(mode='after')
    def validate_probing(self):
        if (self.probeMode == 'targeted') != (self.avoidedProbeInterval is not None):
            raise ValueError('targeted probing requires avoidedProbeInterval, and only targeted probing uses it')
        if self.minimumObservations > self.updateWindow:
            raise ValueError('minimumObservations cannot exceed updateWindow')
        return self


class BudgetPolicy(Definition):
    type: Literal['budget']
    probeInterval: PositiveInt = 10
    unknownUsage: Literal['stop', 'bounded'] = 'stop'
    forecast: Literal['lookahead', 'expected'] = 'lookahead'
    mode: Literal['incumbent', 'pace'] = 'incumbent'


class ReliabilityPolicy(Definition):
    type: Literal['reliability']
    failureClasses: list[Literal['operation', 'transport', 'provider', 'tool-use', 'step-limit', 'unknown']] = Field(min_length=1)
    window: PositiveInt
    minimumObservations: PositiveInt
    failureRateThreshold: Annotated[float, Field(gt=0, le=1)]
    cooldownRequests: PositiveInt
    probeInterval: PositiveInt = 10
    resetOnRecovery: bool = False
    incumbentScope: Literal['global', 'bin'] = 'global'

    @model_validator(mode='after')
    def validate_failure_window(self):
        if self.minimumObservations > self.window or len(set(self.failureClasses)) != len(self.failureClasses):
            raise ValueError('invalid reliability window or repeated failure class')
        return self


FailureClass = Literal['operation', 'transport', 'provider', 'tool-use', 'step-limit', 'unknown']


class CascadePolicy(Definition):
    """Primary configuration with a bounded within-request fallback on observed failures."""
    type: Literal['cascade']
    primary: str
    fallbacks: list[str] = Field(min_length=1, max_length=1)
    triggerFailureClasses: list[FailureClass] = Field(default_factory=lambda: ['step-limit', 'tool-use'], min_length=1)
    primaryMaxSteps: PositiveInt | None = None
    memory: Literal['none', 'source'] = 'none'

    @model_validator(mode='after')
    def validate_chain(self):
        if self.primary in self.fallbacks or len(set(self.fallbacks)) != len(self.fallbacks):
            raise ValueError('cascade fallbacks must be distinct from the primary and each other')
        if len(set(self.triggerFailureClasses)) != len(self.triggerFailureClasses):
            raise ValueError('repeated cascade trigger failure class')
        return self


class RequestRange(Definition):
    firstRequest: PositiveInt
    lastRequest: PositiveInt

    @model_validator(mode='after')
    def validate_range(self):
        if self.lastRequest < self.firstRequest:
            raise ValueError('lastRequest precedes firstRequest')
        return self


class SchedulePhase(RequestRange):
    configurationBySize: dict[str, str] = Field(min_length=1)


class SchedulePolicy(Definition):
    """Phase oracle: knows the disturbance schedule by design; an upper bound, not deployable."""
    type: Literal['schedule']
    default: dict[str, str] = Field(min_length=1)
    phases: list[SchedulePhase] = Field(default_factory=list)


class RandomPolicy(Definition):
    type: Literal['random-eligible']
    seed: StrictInt


class BlindRouterPolicy(Definition):
    """Router that never reads request features (size bin, size, target).

    It keeps its incumbent while the incumbent's recent cost fits the objective (latency limit
    and the trailing token-rate budget), and leaves when it no longer fits. It returns to a
    faster configuration only through a probe whose own observation fits.
    """
    type: Literal['blind-router']
    adaptive: bool
    estimateWindow: PositiveInt = 2
    probeTriggers: list[Literal['periodic', 'signal']] = Field(default_factory=list)
    probeInterval: PositiveInt = 10
    probeBackoff: bool = False
    signalWindow: PositiveInt = 8
    signalTokens: PositiveInt | None = None
    budgetGuard: bool = False
    # Utility objective only (study latencyCostTokensPerSecond); unset keeps earlier episode identities.
    materialImprovement: Annotated[float, Field(ge=0, lt=1)] | None = None
    minimumObservations: PositiveInt | None = None
    estimateTtlRequests: PositiveInt | None = None

    @model_validator(mode='after')
    def validate_probing(self):
        if len(set(self.probeTriggers)) != len(self.probeTriggers):
            raise ValueError('repeated probe trigger')
        if ('signal' in self.probeTriggers) != (self.signalTokens is not None):
            raise ValueError('the signal trigger requires signalTokens, and only it uses them')
        if not self.adaptive and (self.probeTriggers or self.budgetGuard):
            raise ValueError('a non-adaptive blind router does not probe')
        return self


Policy = Annotated[FixedPolicy | RouterPolicy | BudgetPolicy | ReliabilityPolicy | CascadePolicy
                   | SchedulePolicy | RandomPolicy | BlindRouterPolicy, Field(discriminator='type')]


class TokenRateBudget(Definition):
    """Mean tokens per request over the trailing `window` served requests must stay within `perRequest`."""
    perRequest: PositiveInt
    window: PositiveInt


class WorkloadPhase(Definition):
    """Requests up to `lastRequest` draw their size from `sizeWeights` (size bins or sizes such as `64k`)."""
    lastRequest: PositiveInt
    sizeWeights: dict[str, Annotated[float, Field(gt=0)]] = Field(min_length=1)
    disturbance: bool = False


class WorkloadShape(Definition):
    """Replay-only synthetic workload: each position draws a held-out request of the phase's sizes."""
    phases: list[WorkloadPhase] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_phases(self):
        ends = [phase.lastRequest for phase in self.phases]
        if ends != sorted(set(ends)):
            raise ValueError('workload phases must end at strictly increasing requests')
        return self


class OrderPhase(Definition):
    """Positions up to `lastRequest` take, in seeded random order, unused requests of these sizes."""
    lastRequest: PositiveInt
    sizes: list[str] = Field(min_length=1)
    disturbance: bool = False


class WorkloadOrder(Definition):
    """A reordering of the study's requests: every request appears exactly once.

    `sizes` are size bins (`small`, `medium`, `large`) or nominal sizes (`2k` ... `64k`).
    """
    phases: list[OrderPhase] = Field(min_length=1)

    @model_validator(mode='after')
    def validate_phases(self):
        ends = [phase.lastRequest for phase in self.phases]
        if ends != sorted(set(ends)):
            raise ValueError('workload phases must end at strictly increasing requests')
        return self


class PhaseOracle(Definition):
    """Derived after collection: `disturbance` in workload disturbance phases, `normal` elsewhere."""
    type: Literal['phase-oracle']
    normal: str
    disturbance: str


class BudgetOracle(Definition):
    """Derived after collection: per request, the sequence that knows every outcome in advance and
    minimises budget excess, then deadline misses, then total latency (exact search over the window)."""
    type: Literal['budget-oracle']


DerivedArm = Annotated[SchedulePolicy | PhaseOracle | BudgetOracle, Field(discriminator='type')]


class Delay(Definition):
    kind: Literal['delay'] = 'delay'
    configuration: str
    scope: Literal['request', 'tool-call']
    delayMs: PositiveInt
    firstRequest: PositiveInt
    lastRequest: PositiveInt

    @model_validator(mode='after')
    def validate_range(self):
        if self.lastRequest < self.firstRequest:
            raise ValueError('delay lastRequest precedes firstRequest')
        return self


class Fault(RequestRange):
    """Each local-MCP tool call fails with this probability (seeded per request position and call)."""
    kind: Literal['fault']
    configuration: str
    toolErrorRate: Annotated[float, Field(gt=0, le=1)]
    seed: StrictInt


class TokenQuota(RequestRange):
    """Harness-simulated provider quota over the trailing 60 s of wall time, for every configuration."""
    kind: Literal['token-quota']
    tokensPerMinute: PositiveInt


def _effect_kind(value):
    return value.get('kind', 'delay') if isinstance(value, dict) else getattr(value, 'kind', 'delay')


Effect = Annotated[Union[Annotated[Delay, Tag('delay')], Annotated[Fault, Tag('fault')],
                         Annotated[TokenQuota, Tag('token-quota')]], Discriminator(_effect_kind)]


class Study(Definition):
    schemaVersion: Literal[1] = 1
    baseline: str
    configurations: list[str] | None = None
    targets: list[str] | None = Field(default=None, min_length=1)
    seeds: list[StrictInt] = Field(min_length=1)
    repeats: PositiveInt
    policies: dict[str, Policy] = Field(min_length=1)
    scenarios: dict[str, list[Effect]] = Field(min_length=1)
    comparisons: list[tuple[str, str]] = Field(default_factory=list)
    latencyLimitMs: Annotated[float, Field(gt=0)] | None = None
    # Price of one second of latency in tokens (lambda): routers minimize tokens + lambda * latency in seconds.
    latencyCostTokensPerSecond: Annotated[float, Field(gt=0)] | None = None
    tokenBudget: PositiveInt | None = None
    tokenRateBudget: TokenRateBudget | None = None
    workloads: dict[str, WorkloadOrder] = Field(default_factory=dict)
    # Explicit workloads (JSON relative to the definition): {scenario: {seed: [evaluation instance IDs]}},
    # for every scenario and each seed it runs; replaces the target-ordered workload.
    workloadFile: str | None = None
    # Disturbance phase per scenario (marks phases for the phase oracle and the analysis).
    disturbances: dict[str, RequestRange] = Field(default_factory=dict)
    # Size bins a scenario's normal stream draws from: pooled calibration estimates use only these.
    calibrationSizes: dict[str, list[str]] = Field(default_factory=dict)
    # Optional seed subset per scenario (e.g. burst placements assigned to seeds); others run every seed.
    scenarioSeeds: dict[str, list[StrictInt]] = Field(default_factory=dict)
    derivedArms: dict[str, DerivedArm] = Field(default_factory=dict)
    minimumCalibrationPassRate: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode='after')
    def validate_controls(self):
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError('duplicate study seeds')
        if self.configurations is not None and (not self.configurations or len(set(self.configurations)) != len(self.configurations)):
            raise ValueError('duplicate or empty configuration subset')
        if self.targets is not None and len(set(self.targets)) != len(self.targets):
            raise ValueError('duplicate study target')
        if any(not name for name in (*self.policies, *self.scenarios)):
            raise ValueError('policy and scenario names must be nonempty')
        if self.latencyCostTokensPerSecond is not None and (self.latencyLimitMs is not None or self.tokenRateBudget is not None):
            raise ValueError('a latency cost is the objective on its own, not with latencyLimitMs or tokenRateBudget')
        if any(p.type in ('router', 'reliability') for p in self.policies.values()) and self.latencyLimitMs is None:
            raise ValueError('routing requires latencyLimitMs')
        if (any(p.type == 'blind-router' for p in self.policies.values()) and self.latencyLimitMs is None
                and self.tokenRateBudget is None and self.latencyCostTokensPerSecond is None):
            raise ValueError('a blind router requires latencyLimitMs, tokenRateBudget or latencyCostTokensPerSecond')
        utility_fields = ('materialImprovement', 'minimumObservations', 'estimateTtlRequests')
        if self.latencyCostTokensPerSecond is None and any(
                p.type == 'blind-router' and getattr(p, f) is not None for p in self.policies.values() for f in utility_fields):
            raise ValueError('materialImprovement, minimumObservations and estimateTtlRequests apply to the latency-cost objective only')
        if any(p.type == 'blind-router' and p.minimumObservations is not None and p.minimumObservations > p.estimateWindow
               for p in self.policies.values()):
            raise ValueError('minimumObservations cannot exceed estimateWindow')
        if any(name not in self.scenarios for name in self.workloads):
            raise ValueError('workload orders must name defined scenarios')
        if self.workloadFile is not None and (self.workloads or self.targets is not None):
            raise ValueError('an explicit workload file excludes workload orders and a target subset')
        if any(name not in self.scenarios for name in (*self.disturbances, *self.calibrationSizes)):
            raise ValueError('disturbances and calibration sizes must name defined scenarios')
        if set(self.disturbances) & set(self.workloads):
            raise ValueError('a workload order already marks its disturbance phases')
        if any(not sizes or len(set(sizes)) != len(sizes) for sizes in self.calibrationSizes.values()):
            raise ValueError('calibration sizes must be nonempty and duplicate-free')
        for name, seeds in self.scenarioSeeds.items():
            if name not in self.scenarios:
                raise ValueError('scenario seeds must name defined scenarios')
            if not seeds or len(set(seeds)) != len(seeds) or not set(seeds) <= set(self.seeds):
                raise ValueError('scenario seeds must be a nonempty, duplicate-free subset of seeds')
        if any(p.type == 'budget' for p in self.policies.values()) != (self.tokenBudget is not None):
            raise ValueError('tokenBudget requires a budget policy and vice versa')
        if self.minimumCalibrationPassRate is not None and self.tokenBudget is None:
            raise ValueError('minimumCalibrationPassRate requires tokenBudget')
        if set(self.derivedArms) & set(self.policies):
            raise ValueError('derived arm names must differ from policy names')
        if any(a.type == 'budget-oracle' for a in self.derivedArms.values()) and self.tokenRateBudget is None:
            raise ValueError('a budget oracle requires tokenRateBudget')
        arms = {*self.policies, *self.derivedArms}
        if any(a not in arms or b not in arms or a == b for a, b in self.comparisons):
            raise ValueError('comparison references missing or identical policy')
        return self
