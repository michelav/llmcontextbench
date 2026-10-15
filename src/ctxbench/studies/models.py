"""Authored definitions. Scientific thresholds have no implicit defaults."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

PositiveInt = Annotated[StrictInt, Field(gt=0)]


class Definition(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Split(Definition):
    seed: StrictInt
    calibrationTargetsPerLanguage: PositiveInt


class Baseline(Definition):
    schemaVersion: Literal[1] = 1
    experiment: str
    split: Split
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


Policy = Annotated[FixedPolicy | RouterPolicy | BudgetPolicy | ReliabilityPolicy | CascadePolicy,
                   Field(discriminator='type')]


class Delay(Definition):
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


class Study(Definition):
    schemaVersion: Literal[1] = 1
    baseline: str
    configurations: list[str] | None = None
    seeds: list[StrictInt] = Field(min_length=1)
    repeats: PositiveInt
    policies: dict[str, Policy] = Field(min_length=1)
    scenarios: dict[str, list[Delay]] = Field(min_length=1)
    comparisons: list[tuple[str, str]] = Field(default_factory=list)
    latencyLimitMs: Annotated[float, Field(gt=0)] | None = None
    tokenBudget: PositiveInt | None = None
    minimumCalibrationPassRate: Annotated[float, Field(ge=0, le=1)] | None = None

    @model_validator(mode='after')
    def validate_controls(self):
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError('duplicate study seeds')
        if self.configurations is not None and (not self.configurations or len(set(self.configurations)) != len(self.configurations)):
            raise ValueError('duplicate or empty configuration subset')
        if any(not name for name in (*self.policies, *self.scenarios)):
            raise ValueError('policy and scenario names must be nonempty')
        if any(p.type in ('router', 'reliability') for p in self.policies.values()) and self.latencyLimitMs is None:
            raise ValueError('routing requires latencyLimitMs')
        if any(p.type == 'budget' for p in self.policies.values()) != (self.tokenBudget is not None):
            raise ValueError('tokenBudget requires a budget policy and vice versa')
        if self.minimumCalibrationPassRate is not None and self.tokenBudget is None:
            raise ValueError('minimumCalibrationPassRate requires tokenBudget')
        if any(a not in self.policies or b not in self.policies or a == b for a, b in self.comparisons):
            raise ValueError('comparison references missing or identical policy')
        return self
