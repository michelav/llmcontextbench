"""Named, deterministic runtime disturbances scoped to one runtime component."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from time import sleep
from typing import Callable

from ctxbench.ai.failures import tag_failure
from ctxbench.ai.models.base import ModelAdapter, ModelInput, ModelResponse


class RuntimeComponent(StrEnum):
    LOCAL_FUNCTION = "local_function"
    LOCAL_MCP = "local_mcp"
    REMOTE_MCP = "remote_mcp"
    MODEL = "model"


class DisturbanceKind(StrEnum):
    DELAY = "delay"
    FAILURE = "failure"
    DELAY_AND_FAILURE = "delay_and_failure"


@dataclass(frozen=True, slots=True)
class DisturbanceSpec:
    name: str
    version: str
    component: RuntimeComponent
    kind: DisturbanceKind
    first_sequence: int
    last_sequence: int | None
    seed: int
    delay_ms: int = 0
    failure_rate: float = 0.0
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError("disturbance name and version must be nonempty")
        object.__setattr__(self, "component", RuntimeComponent(self.component))
        object.__setattr__(self, "kind", DisturbanceKind(self.kind))
        if (type(self.first_sequence) is not int or self.first_sequence < 1
                or (self.last_sequence is not None and
                    (type(self.last_sequence) is not int or self.last_sequence < self.first_sequence))):
            raise ValueError("invalid disturbance sequence range")
        if type(self.seed) is not int or type(self.delay_ms) is not int or self.delay_ms < 0:
            raise ValueError("disturbance seed and delay must be integers; delay is nonnegative")
        if (isinstance(self.failure_rate, bool) or not isinstance(self.failure_rate, (int, float))
                or not isfinite(self.failure_rate) or not 0 <= self.failure_rate <= 1):
            raise ValueError("disturbance failure_rate must be between zero and one")
        if len(set(self.candidate_ids)) != len(self.candidate_ids) or any(not v for v in self.candidate_ids):
            raise ValueError("disturbance candidate IDs must be unique and nonempty")
        if self.kind == DisturbanceKind.DELAY and self.failure_rate:
            raise ValueError("delay-only disturbance cannot set a failure rate")
        if self.kind == DisturbanceKind.FAILURE and self.delay_ms:
            raise ValueError("failure-only disturbance cannot set a delay")
        if self.kind == DisturbanceKind.DELAY and self.delay_ms == 0:
            raise ValueError("delay disturbance must declare a nonzero delay")
        if self.kind == DisturbanceKind.FAILURE and self.failure_rate == 0:
            raise ValueError("failure disturbance must declare a nonzero failure rate")
        if self.kind == DisturbanceKind.DELAY_AND_FAILURE and not (self.delay_ms or self.failure_rate):
            raise ValueError("delay_and_failure must declare a nonzero effect")

    def applies_to(self, component: RuntimeComponent | str, sequence: int, candidate_id: str) -> bool:
        if RuntimeComponent(component) != self.component or sequence < self.first_sequence:
            return False
        if self.last_sequence is not None and sequence > self.last_sequence:
            return False
        return not self.candidate_ids or candidate_id in self.candidate_ids

    @classmethod
    def from_definition(cls, raw):
        """Parse the public camel-case definition shape into the runtime contract."""
        spec = cls(
            name=raw["name"], version=raw["version"], component=raw["component"], kind=raw["kind"],
            first_sequence=raw.get("firstSequence", 1), last_sequence=raw.get("lastSequence"),
            seed=raw.get("seed", 0), delay_ms=raw.get("delayMs", 0),
            failure_rate=raw.get("failureRate", 0), candidate_ids=tuple(raw.get("candidates", ())),
        )
        return spec

    def to_definition(self):
        value = {"name": self.name, "version": self.version, "component": self.component.value,
                 "kind": self.kind.value, "firstSequence": self.first_sequence, "seed": self.seed}
        if self.last_sequence is not None:
            value["lastSequence"] = self.last_sequence
        if self.delay_ms:
            value["delayMs"] = self.delay_ms
        if self.failure_rate:
            value["failureRate"] = self.failure_rate
        if self.candidate_ids:
            value["candidates"] = list(self.candidate_ids)
        return value

    def decorator(
        self,
        *,
        component: RuntimeComponent | str,
        sequence: int,
        candidate_id: str,
        sleeper: Callable[[float], object] = sleep,
    ):
        if not self.applies_to(component, sequence, candidate_id):
            return None

        wrappers = []

        def decorate(runtime):
            wrapper_type = ModelRuntimeDisturbance if self.component == RuntimeComponent.MODEL else ToolRuntimeDisturbance
            wrapper = wrapper_type(
                runtime, name=self.name, component=self.component,
                delay_ms=self.delay_ms, failure_rate=self.failure_rate,
                failure_seed=self.seed, sequence=sequence, sleeper=sleeper,
            )
            wrappers.append(wrapper)
            return wrapper

        decorate.effect_records = lambda: [wrapper.effect_record(self.name, self.version) for wrapper in wrappers]

        return decorate


def build_runtime_disturbances(definitions, *, component_sequence: int, candidate_id: str, sleeper=sleep):
    """Build candidate-scoped runtime interceptors and a snapshot of their applied effects.

    Several disturbances on one component are stacked in declared order, the first innermost.
    """
    interceptors = {}
    factories = []
    for raw in definitions:
        spec = raw if isinstance(raw, DisturbanceSpec) else DisturbanceSpec.from_definition(raw)
        factory = spec.decorator(component=spec.component, sequence=component_sequence,
                                 candidate_id=candidate_id, sleeper=sleeper)
        if factory is None:
            continue
        previous = interceptors.get(spec.component.value)
        if previous is None:
            interceptors[spec.component.value] = factory
        else:
            interceptors[spec.component.value] = (
                lambda runtime, first=previous, second=factory: second(first(runtime)))
        factories.append(factory)

    def effects():
        return [row for factory in factories for row in factory.effect_records()]

    return interceptors, effects


def _failure_draw(disturbance: str, failure_seed: int, sequence: int, call_index: int,
                  operation: str) -> float:
    """Uniform draw in [0, 1) for one call.

    Every input is a separate field of the hashed key, so two disturbances never share a draw
    sequence because their seeds, sequence positions or names happen to combine alike.
    """
    key = "\x1f".join((disturbance, str(failure_seed), str(sequence), str(call_index), operation))
    return int.from_bytes(sha256(key.encode("utf-8")).digest()[:8], "big") / (2**64)


class ToolRuntimeDisturbance:
    """Apply seeded delay/failure effects to tool operations for a specific component."""

    def __init__(self, runtime, *, name: str, component: RuntimeComponent, delay_ms: int = 0,
                 failure_rate: float = 0.0, failure_seed: int = 0, sequence: int = 0, sleeper=sleep) -> None:
        if component not in {RuntimeComponent.LOCAL_FUNCTION, RuntimeComponent.LOCAL_MCP, RuntimeComponent.REMOTE_MCP}:
            raise ValueError("tool runtime disturbance requires a tool component")
        if (isinstance(delay_ms, bool) or not isinstance(delay_ms, (int, float))
                or not isfinite(delay_ms) or delay_ms < 0
                or isinstance(failure_rate, bool) or not isinstance(failure_rate, (int, float))
                or not isfinite(failure_rate) or not 0 <= failure_rate <= 1):
            raise ValueError("invalid tool runtime disturbance effect")
        if type(failure_seed) is not int or not name:
            raise ValueError("tool runtime disturbance requires a name and integer seed")
        self.runtime = runtime
        self.name = name
        self.component = component
        self.delay_ms = delay_ms
        self.failure_rate = failure_rate
        self.failure_seed = failure_seed
        self.sequence = sequence
        self.sleeper = sleeper
        self.call_index = 0
        self.applied_delay_ms = 0
        self.injected_failures = 0

    def list_tools(self):
        return self.runtime.list_tools()

    def call_tool(self, name, arguments):
        if self.delay_ms:
            self.sleeper(self.delay_ms / 1000)
            self.applied_delay_ms += int(self.delay_ms)
        call_index = self.call_index
        self.call_index += 1
        if self.failure_rate:
            if _failure_draw(self.name, self.failure_seed, self.sequence, call_index, name) < self.failure_rate:
                self.injected_failures += 1
                error = RuntimeError(f"Injected disturbance {self.name} on {self.component.value}")
                tag_failure(error, "injected_disturbance")
                raise error
        return self.runtime.call_tool(name, arguments)

    def effect_record(self, name: str, version: str):
        return {"name": name, "version": version, "appliedDelayMs": self.applied_delay_ms,
                "injectedFailures": self.injected_failures}

    def close(self):
        self.runtime.close()


class ModelRuntimeDisturbance:
    """Apply deterministic delay/failure effects to per-call model generation."""

    def __init__(self, model: ModelAdapter, *, name: str, component: RuntimeComponent,
                 delay_ms: int = 0, failure_rate: float = 0.0, failure_seed: int = 0, sequence: int = 0, sleeper=sleep):
        if component != RuntimeComponent.MODEL:
            raise ValueError("model runtime disturbance requires the model component")
        self.model = model
        self.name = name
        self.component = component
        self.delay_ms = delay_ms
        self.failure_rate = failure_rate
        self.failure_seed = failure_seed
        self.sequence = sequence
        self.sleeper = sleeper
        self.call_index = 0
        self.applied_delay_ms = 0
        self.injected_failures = 0

    def __getattr__(self, name):
        return getattr(self.model, name)

    def failure_category(self, exc):
        return self.model.failure_category(exc)

    def generate(self, model_input: ModelInput, request, trace=None) -> ModelResponse:
        if self.delay_ms:
            self.sleeper(self.delay_ms / 1000)
            self.applied_delay_ms += int(self.delay_ms)
        call_index = self.call_index
        self.call_index += 1
        if self.failure_rate:
            if _failure_draw(self.name, self.failure_seed, self.sequence, call_index, "model") < self.failure_rate:
                self.injected_failures += 1
                error = RuntimeError(f"Injected disturbance {self.name} on model")
                tag_failure(error, "injected_disturbance")
                raise error
        return self.model.generate(model_input, request, trace=trace)

    def effect_record(self, name: str, version: str):
        return {"name": name, "version": version, "appliedDelayMs": self.applied_delay_ms,
                "injectedFailures": self.injected_failures}
