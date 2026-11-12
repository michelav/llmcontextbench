"""Named, deterministic runtime disturbances scoped to one runtime component."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from time import sleep
from typing import Callable


class RuntimeComponent(StrEnum):
    LOCAL_FUNCTION = "local_function"
    LOCAL_MCP = "local_mcp"
    REMOTE_MCP = "remote_mcp"


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

        def decorate(runtime):
            return ToolRuntimeDisturbance(
                runtime,
                name=self.name,
                component=self.component,
                delay_ms=self.delay_ms,
                failure_rate=self.failure_rate,
                failure_seed=self.seed + sequence,
                sleeper=sleeper,
            )

        return decorate


class ToolRuntimeDisturbance:
    """Apply seeded delay/failure effects to tool operations for a specific component."""

    def __init__(self, runtime, *, name: str, component: RuntimeComponent, delay_ms: int = 0,
                 failure_rate: float = 0.0, failure_seed: int = 0, sleeper=sleep) -> None:
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
        self.sleeper = sleeper
        self.call_index = 0

    def list_tools(self):
        return self.runtime.list_tools()

    def call_tool(self, name, arguments):
        if self.delay_ms:
            self.sleeper(self.delay_ms / 1000)
        call_index = self.call_index
        self.call_index += 1
        if self.failure_rate:
            digest = sha256(f"{self.failure_seed}:{call_index}:{name}".encode("utf-8")).digest()
            draw = int.from_bytes(digest[:8], "big") / (2**64)
            if draw < self.failure_rate:
                raise RuntimeError(f"Injected disturbance {self.name} on {self.component.value}")
        return self.runtime.call_tool(name, arguments)

    def close(self):
        self.runtime.close()
