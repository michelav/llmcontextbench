"""Typed adaptive experiment definition and v4 validation."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ctxbench.core.definitions import resolve_definition, resolve_definition_data
from ctxbench.runtime.disturbances import DisturbanceSpec
from ctxbench.workload.builder import Workload


ADAPTIVE_DEFINITION_VERSION = 4


@dataclass(frozen=True, slots=True)
class WorkloadRequest:
    task_id: str
    instance_id: str
    request_id: str | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def to_definition(self) -> dict[str, Any]:
        result = {"taskId": self.task_id, "instanceId": self.instance_id}
        if self.request_id is not None:
            result["requestId"] = self.request_id
        if self.labels:
            result["labels"] = dict(self.labels)
        return result


def _builder_value(value: Any) -> Any:
    return value.to_definition() if hasattr(value, "to_definition") else value


def _validate_builder(section: str, value: Mapping[str, Any]) -> None:
    from jsonschema import Draft202012Validator

    schema = adaptive_definition_schema()["properties"][section]
    if section in {"models", "configurations", "candidates"}:
        schema = schema["additionalProperties"]
    elif section in {"goals", "signals", "disturbances"}:
        schema = schema["items"]
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        error = sorted(errors, key=lambda item: list(item.absolute_path))[0]
        location = ".".join(str(item) for item in error.absolute_path)
        field_name = f"{section}.{location}" if location else section
        raise ValueError(f"Invalid adaptive definition at {field_name}: {error.message}")


def _normalise_section(section: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Fill defaults and apply a section's normaliser.

    This is the one normalisation rule for a section: definition files, mappings passed to
    ``AdaptiveExperiment`` and section builders all go through it, so equal inputs give equal
    stored mappings. It assumes the value already passed the section's schema fragment.
    """
    result = deepcopy(dict(value))
    if section == "models":
        result["modelParams"] = result.get("modelParams") or {}
    elif section == "policy":
        result["params"] = result.get("params") or {}
    elif section == "window":
        result["mode"] = result.get("mode", "sliding")
    elif section == "goals":
        result["scope"] = result.get("scope", "system")
        if isinstance(result.get("window"), Mapping):
            result["window"] = _normalise_section("window", result["window"])
    elif section == "acceptance":
        result = {"minimumResponseLength": result.get("minimumResponseLength", 0)}
    elif section == "disturbances":
        try:
            result = DisturbanceSpec.from_definition(result).to_definition()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid adaptive disturbance definition: {exc}") from exc
    elif section == "workload" and "generator" in result:
        generator = result["generator"]
        generator.setdefault("tasks", [])
        generator.setdefault("instances", [])
        generator.setdefault("sampling", "with_replacement")
        generator.setdefault("labelFeatures", [])
        result = {"generator": generator}
    return result


def _normalise_mapping(section: str, value: Any) -> Any:
    """Normalise a mapping given in code; invalid values are left for schema validation at plan."""
    if not isinstance(value, Mapping):
        return value
    try:
        return _normalise_section(section, value)
    except (AttributeError, KeyError, TypeError, ValueError):
        return value


class _SectionBuilder:
    section: str

    def __post_init__(self) -> None:
        self.to_definition()

    def _validate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Validate through the file schema fragment and normaliser; return the stored mapping."""
        _validate_builder(self.section, value)
        return _normalise_section(self.section, value)


@dataclass(frozen=True, slots=True)
class Model(_SectionBuilder):
    provider: str
    name: str
    model_params: Mapping[str, Any] = field(default_factory=dict)
    section = "models"

    def to_definition(self) -> dict[str, Any]:
        value = {"provider": self.provider, "name": self.name, "modelParams": dict(self.model_params)}
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Model":
        return cls(value["provider"], value["name"], value.get("modelParams") or {})


@dataclass(frozen=True, slots=True)
class Configuration(_SectionBuilder):
    strategy: str
    representation: str
    surface: str
    section = "configurations"

    def to_definition(self) -> dict[str, Any]:
        value = {"strategy": self.strategy, "representation": self.representation, "surface": self.surface}
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Configuration":
        return cls(value["strategy"], value["representation"], value["surface"])


@dataclass(frozen=True, slots=True)
class Candidate(_SectionBuilder):
    id: str
    model: str
    configuration: str
    labels: Mapping[str, str] = field(default_factory=dict)
    section = "candidates"

    def to_definition(self) -> dict[str, Any]:
        value: dict[str, Any] = {"id": self.id, "model": self.model, "configuration": self.configuration}
        if self.labels:
            value["labels"] = dict(self.labels)
        self._validate({key: val for key, val in value.items() if key != "id"})
        return value

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Candidate":
        return cls(value["id"], value["model"], value["configuration"], value.get("labels") or {})


@dataclass(frozen=True, slots=True)
class PolicyRef(_SectionBuilder):
    ref: str
    params: Mapping[str, Any] = field(default_factory=dict)
    sources: tuple[str, ...] = ()
    section = "policy"

    def to_definition(self) -> dict[str, Any]:
        value = {"ref": self.ref, "params": dict(self.params)}
        if self.sources:
            value["sources"] = list(self.sources)
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "PolicyRef":
        return cls(value["ref"], value.get("params") or {}, tuple(value.get("sources") or ()))


@dataclass(frozen=True, slots=True)
class Window(_SectionBuilder):
    requests: int | None = None
    all: bool = False
    mode: str = "sliding"
    section = "window"

    def to_definition(self) -> dict[str, Any]:
        value: dict[str, Any] = {}
        if self.requests is not None:
            value["requests"] = self.requests
        if self.all:
            value["all"] = True
        value["mode"] = self.mode
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Window":
        return cls(value.get("requests"), bool(value.get("all", False)), value.get("mode", "sliding"))


@dataclass(frozen=True, slots=True)
class Goal(_SectionBuilder):
    id: str
    signal: str
    statistic: str
    upper: float | None = None
    lower: float | None = None
    scope: str = "system"
    window: Mapping[str, Any] | Window | None = None
    section = "goals"

    def to_definition(self) -> dict[str, Any]:
        value = {"id": self.id, "signal": self.signal, "statistic": self.statistic, "scope": self.scope}
        if self.upper is not None:
            value["upper"] = self.upper
        if self.lower is not None:
            value["lower"] = self.lower
        if self.window is not None:
            value["window"] = _builder_value(self.window)
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Goal":
        return cls(value["id"], value["signal"], value["statistic"], value.get("upper"), value.get("lower"),
                   value.get("scope", "system"), value.get("window"))


@dataclass(frozen=True, slots=True)
class Acceptance(_SectionBuilder):
    minimum_response_length: int = 0
    section = "acceptance"

    def to_definition(self) -> dict[str, Any]:
        value = {"minimumResponseLength": self.minimum_response_length}
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Acceptance":
        return cls(value.get("minimumResponseLength", 0))


@dataclass(frozen=True, slots=True)
class SignalRef(_SectionBuilder):
    id: str
    assessor: str
    sources: tuple[str, ...] = ()
    section = "signals"

    def to_definition(self) -> dict[str, Any]:
        value = {"id": self.id, "assessor": self.assessor}
        if self.sources:
            value["sources"] = list(self.sources)
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "SignalRef":
        return cls(value["id"], value["assessor"], tuple(value.get("sources") or ()))


@dataclass(frozen=True, slots=True)
class Disturbance(_SectionBuilder):
    name: str
    component: str
    kind: str
    first_sequence: int
    last_sequence: int | None = None
    seed: int = 0
    delay_ms: int | None = None
    failure_rate: float | None = None
    candidates: tuple[str, ...] = ()
    version: str = "1"
    section = "disturbances"

    def to_definition(self) -> dict[str, Any]:
        value = {"name": self.name, "version": self.version, "component": self.component, "kind": self.kind,
                 "firstSequence": self.first_sequence, "seed": self.seed}
        if self.last_sequence is not None:
            value["lastSequence"] = self.last_sequence
        if self.delay_ms is not None:
            value["delayMs"] = self.delay_ms
        if self.failure_rate is not None:
            value["failureRate"] = self.failure_rate
        if self.candidates:
            value["candidates"] = list(self.candidates)
        return self._validate(value)

    @classmethod
    def from_definition(cls, value: Mapping[str, Any]) -> "Disturbance":
        return cls(value["name"], value["component"], value["kind"], value.get("firstSequence", 1),
                   value.get("lastSequence"), value.get("seed", 0), value.get("delayMs"),
                   value.get("failureRate"), tuple(value.get("candidates") or ()), value.get("version", "1"))


@dataclass(frozen=True, slots=True)
class Scenario:
    workload: Workload
    disturbances: tuple[Disturbance | Mapping[str, Any], ...] = ()

    def to_sections(self) -> dict[str, Any]:
        return {"workload": self.workload.to_definition(),
                "disturbances": [_builder_value(item) for item in self.disturbances]}


@dataclass(frozen=True, slots=True)
class AdaptiveExperiment:
    """Parsed adaptive definition; this is the same model used by file and object planning."""

    id: str
    dataset: str | Mapping[str, Any]
    models: Mapping[str, Mapping[str, Any]]
    surfaces: Mapping[str, Mapping[str, Any]]
    configurations: Mapping[str, Mapping[str, Any]]
    candidates: Mapping[str, Mapping[str, Any]]
    workload: Mapping[str, Any] | Workload | tuple[WorkloadRequest, ...]
    policy: Mapping[str, Any] | PolicyRef
    window: Mapping[str, Any] | Window
    seed: int = 0
    output: str = "outputs"
    labels: Mapping[str, str] = field(default_factory=dict)
    task_params: Mapping[str, Any] = field(default_factory=dict)
    execution_options: Mapping[str, Any] = field(default_factory=dict)
    acceptance: Mapping[str, Any] | Acceptance = field(default_factory=dict)
    signals: tuple[Mapping[str, Any] | SignalRef, ...] = ()
    goals: tuple[Mapping[str, Any] | Goal, ...] = ()
    disturbances: tuple[Mapping[str, Any] | Disturbance, ...] = ()
    evaluation: Mapping[str, Any] = field(default_factory=dict)
    trace: Mapping[str, Any] = field(default_factory=dict)
    allow_mixed_models: bool = False
    base_dir: Path = field(default_factory=Path.cwd)
    resolved_definition: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def keyed(section: str, values: Mapping[str, Any], builder_type: type) -> dict[str, Any]:
            return {key: _builder_value(value) if isinstance(value, builder_type) else value
                    for key, value in values.items()}

        object.__setattr__(self, "models", {key: _normalise_mapping("models", value)
                                            for key, value in keyed("models", self.models, Model).items()})
        object.__setattr__(self, "configurations", keyed("configurations", self.configurations, Configuration))
        candidate_values = self.candidates
        if isinstance(candidate_values, Mapping):
            candidates = {}
            for key, value in candidate_values.items():
                normalized = _builder_value(value) if isinstance(value, Candidate) else value
                if isinstance(normalized, Mapping) and "id" in normalized:
                    normalized = {field: item for field, item in normalized.items() if field != "id"}
                candidates[key] = normalized
        else:
            candidates = {candidate.id: {key: value for key, value in candidate.to_definition().items() if key != "id"}
                          for candidate in candidate_values}
        object.__setattr__(self, "candidates", candidates)
        if isinstance(self.workload, Workload):
            workload = self.workload.to_definition()
        elif isinstance(self.workload, Mapping):
            workload = dict(self.workload)
        else:
            workload = Workload.explicit(self.workload).to_definition()
        # Builders are already normalised; mappings are normalised by the same per-section rule,
        # so a builder and the equivalent mapping give equal experiments.
        object.__setattr__(self, "workload", _normalise_mapping("workload", workload))
        object.__setattr__(self, "policy", _normalise_mapping("policy", _builder_value(self.policy)))
        object.__setattr__(self, "window", _normalise_mapping("window", _builder_value(self.window)))
        object.__setattr__(self, "acceptance", _normalise_mapping("acceptance", _builder_value(self.acceptance)))
        object.__setattr__(self, "signals", tuple(_builder_value(item) for item in self.signals))
        object.__setattr__(self, "goals", tuple(_normalise_mapping("goals", _builder_value(item))
                                                for item in self.goals))
        object.__setattr__(self, "disturbances", tuple(_normalise_mapping("disturbances", _builder_value(item))
                                                       for item in self.disturbances))


def adaptive_definition_schema() -> dict[str, Any]:
    """Strict Python schema for the initial explicit-workload v4 contract."""
    label_map = {"type": "object", "additionalProperties": {"type": "string"}}
    assessor = {"type": "object", "additionalProperties": False,
                "required": ["id", "assessor"],
                "properties": {"id": {"type": "string", "minLength": 1},
                               "assessor": {"type": "string", "minLength": 1},
                               "sources": {"type": "array", "items": {"type": "string", "minLength": 1}}}}
    goal = {"type": "object", "additionalProperties": False,
            "required": ["id", "signal", "statistic"],
            "properties": {"id": {"type": "string", "minLength": 1},
                           "signal": {"type": "string", "minLength": 1},
                           "statistic": {"type": "string", "minLength": 1},
                           "upper": {"type": "number"}, "lower": {"type": "number"},
                           "scope": {"type": "string"}, "window": {"type": "object"}},
            "oneOf": [{"required": ["upper"], "not": {"required": ["lower"]}},
                      {"required": ["lower"], "not": {"required": ["upper"]}}]}
    disturbance = {"type": "object", "additionalProperties": False,
                   "required": ["name", "version", "component", "kind"],
                   "properties": {"name": {"type": "string", "minLength": 1},
                                  "version": {"type": "string", "minLength": 1},
                                  "component": {"enum": ["local_function", "local_mcp", "remote_mcp", "model"]},
                                  "kind": {"enum": ["delay", "failure", "delay_and_failure"]},
                                  "delayMs": {"type": "integer", "minimum": 0},
                                  "failureRate": {"type": "number", "minimum": 0, "maximum": 1},
                                  "firstSequence": {"type": "integer", "minimum": 1},
                                  "lastSequence": {"type": "integer", "minimum": 1},
                                  "seed": {"type": "integer"},
                                  "candidates": {"type": "array", "items": {"type": "string", "minLength": 1}}},
                   "allOf": [
                       {"if": {"properties": {"kind": {"const": "delay"}}, "required": ["kind"]},
                        "then": {"required": ["delayMs"]}},
                       {"if": {"properties": {"kind": {"const": "failure"}}, "required": ["kind"]},
                        "then": {"required": ["failureRate"]}},
                       {"if": {"properties": {"kind": {"const": "delay_and_failure"}}, "required": ["kind"]},
                        "then": {"anyOf": [{"required": ["delayMs"]}, {"required": ["failureRate"]}]}}
                   ]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["workflowKind", "schemaVersion", "id", "dataset", "models", "surfaces",
                     "configurations", "candidates", "workload", "policy", "window"],
        "properties": {
            "workflowKind": {"const": "adaptive"}, "schemaVersion": {"const": ADAPTIVE_DEFINITION_VERSION},
            "id": {"type": "string", "minLength": 1}, "output": {"type": "string", "minLength": 1},
            "seed": {"type": "integer"}, "labels": label_map,
            "allowMixedModels": {"type": "boolean"},
            "dataset": {"oneOf": [
                {"type": "string", "minLength": 1},
                {"type": "object", "additionalProperties": False,
                 "properties": {"id": {"type": "string"}, "version": {"type": "string"},
                                "root": {"type": "string"}, "origin": {"type": "string"}},
                 "anyOf": [{"required": ["root"]}, {"required": ["id", "version"]}]},
            ]},
            "models": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["provider", "name"],
                "properties": {"provider": {"type": "string", "minLength": 1},
                               "name": {"type": "string", "minLength": 1},
                               "modelParams": {"type": "object"}}}},
            "surfaces": {"type": "object", "minProperties": 1, "additionalProperties": {
                "oneOf": [
                    {"type": "object", "additionalProperties": False,
                     "properties": {"type": {"const": "full_context"}}},
                    {"type": "object", "additionalProperties": False,
                     "required": ["type", "operations"],
                     "properties": {"type": {"const": "operations"},
                                    "operations": {"type": "array", "minItems": 1,
                                                   "items": {"type": "string", "minLength": 1}}}},
                ]}},
            "configurations": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False,
                "required": ["strategy", "representation", "surface"],
                "properties": {"strategy": {"enum": ["inline", "local_function", "local_mcp", "remote_mcp"]},
                               "representation": {"type": "string", "minLength": 1},
                               "surface": {"type": "string", "minLength": 1}}}},
            "candidates": {"type": "object", "minProperties": 1, "additionalProperties": {
                "type": "object", "additionalProperties": False, "required": ["model", "configuration"],
                "properties": {"model": {"type": "string", "minLength": 1},
                               "configuration": {"type": "string", "minLength": 1},
                               "labels": label_map}}},
            "taskParams": {"type": "object"},
            "execution": {"type": "object", "additionalProperties": False,
                          "properties": {"options": {"type": "object"}}},
            "workload": {"type": "object", "oneOf": [
                {"required": ["requests"], "not": {"required": ["generator"]},
                 "additionalProperties": False,
                 "properties": {"requests": {"type": "array", "minItems": 1, "items": {
                     "type": "object", "additionalProperties": False,
                     "required": ["taskId", "instanceId"],
                     "properties": {"requestId": {"type": "string", "minLength": 1},
                                    "taskId": {"type": "string", "minLength": 1},
                                    "instanceId": {"type": "string", "minLength": 1},
                                    "labels": label_map}}}}},
                {"required": ["generator"], "not": {"required": ["requests"]},
                 "additionalProperties": False,
                 "properties": {"generator": {"type": "object", "additionalProperties": False,
                     "required": ["seed", "segments"], "properties": {
                         "seed": {"type": "integer"},
                         "tasks": {"type": "array", "items": {"type": "string", "minLength": 1}},
                         "instances": {"type": "array", "items": {"type": "string", "minLength": 1}},
                         "sampling": {"enum": ["with_replacement", "without_replacement"]},
                         "labelFeatures": {"type": "array", "items": {"type": "string", "minLength": 1}},
                         "segments": {"type": "array", "minItems": 1, "items": {
                             "type": "object", "additionalProperties": False, "required": ["size"],
                             "properties": {"size": {"type": "integer", "minimum": 1},
                                            "where": {"type": "object"}}}}}}}}]},
            "policy": {"type": "object", "additionalProperties": False, "required": ["ref"],
                       "properties": {"ref": {"type": "string", "minLength": 1},
                                      "params": {"type": "object"},
                                      "sources": {"type": "array", "items": {"type": "string", "minLength": 1}}}},
            "window": {"type": "object", "additionalProperties": False,
                       "properties": {"requests": {"type": "integer", "minimum": 1},
                                      "all": {"const": True}, "mode": {"enum": ["sliding", "fixed"]}},
                       "oneOf": [
                {"required": ["requests"], "not": {"required": ["all"]},
                 "properties": {"requests": {"type": "integer", "minimum": 1},
                                "mode": {"enum": ["sliding", "fixed"]}}},
                {"required": ["all"], "not": {"required": ["requests"]},
                 "properties": {"all": {"const": True}, "mode": {"enum": ["sliding", "fixed"]}}}]},
            "signals": {"type": "array", "items": assessor},
            "acceptance": {"type": "object", "additionalProperties": False,
                           "properties": {"minimumResponseLength": {"type": "integer", "minimum": 0}}},
            "goals": {"type": "array", "items": goal},
            "disturbances": {"type": "array", "items": disturbance},
            "evaluation": {"type": "object", "additionalProperties": False,
                            "properties": {"enabled": {"type": "boolean"},
                                           "judges": {"type": "array"}}},
            "trace": {"type": "object", "additionalProperties": False,
                      "properties": {"enabled": {"type": "boolean"},
                                     "writeFiles": {"type": "boolean"}}},
        },
    }


def experiment_definition(experiment: AdaptiveExperiment) -> dict[str, Any]:
    """Return the v4 definition mapping that describes an experiment object."""
    def plain(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(item) for item in value]
        return value

    return {
        "workflowKind": "adaptive", "schemaVersion": ADAPTIVE_DEFINITION_VERSION,
        "id": experiment.id, "output": experiment.output, "seed": experiment.seed,
        "labels": plain(experiment.labels), "allowMixedModels": experiment.allow_mixed_models,
        "dataset": plain(experiment.dataset), "models": plain(experiment.models),
        "surfaces": plain(experiment.surfaces), "configurations": plain(experiment.configurations),
        "candidates": plain(experiment.candidates), "taskParams": plain(experiment.task_params),
        "execution": {"options": plain(experiment.execution_options)},
        "workload": plain(experiment.workload), "policy": plain(experiment.policy),
        "window": plain(experiment.window), "signals": plain(experiment.signals),
        "acceptance": plain(experiment.acceptance), "goals": plain(experiment.goals),
        "disturbances": plain(experiment.disturbances), "evaluation": plain(experiment.evaluation),
        "trace": plain(experiment.trace),
    }


def load_adaptive_experiment(source: str | Path | Mapping[str, Any] | AdaptiveExperiment, *,
                             base_dir: str | Path | None = None) -> AdaptiveExperiment:
    """Parse and validate a definition file, mapping, or experiment object.

    An experiment object is validated through the same schema as a file: its fields are the
    authority, so one built or modified in a script is planned exactly as written.
    """
    if isinstance(source, AdaptiveExperiment):
        return load_adaptive_experiment(experiment_definition(source), base_dir=base_dir or source.base_dir)
    if isinstance(source, Mapping):
        actual_base = Path(base_dir or Path.cwd()).resolve()
        resolved = resolve_definition_data(dict(source), base_dir=actual_base)
    else:
        path = Path(source).expanduser().resolve()
        actual_base = path.parent
        resolved = resolve_definition(path)
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(adaptive_definition_schema()).iter_errors(resolved),
                    key=lambda err: list(err.absolute_path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"Invalid adaptive definition at {location}: {first.message}")
    normalized_disturbances = [_normalise_section("disturbances", row)
                               for row in resolved.get("disturbances", [])]
    resolved = {
        **resolved,
        "output": resolved.get("output", "outputs"),
        "seed": resolved.get("seed", 0),
        "labels": deepcopy(resolved.get("labels") or {}),
        "allowMixedModels": resolved.get("allowMixedModels", False),
        "taskParams": deepcopy(resolved.get("taskParams") or {}),
        "execution": {"options": deepcopy((resolved.get("execution") or {}).get("options") or {})},
        "acceptance": _normalise_section("acceptance", resolved.get("acceptance") or {}),
        "signals": deepcopy(resolved.get("signals") or []),
        "goals": deepcopy(resolved.get("goals") or []),
        "disturbances": normalized_disturbances,
        "evaluation": deepcopy(resolved.get("evaluation") or {}),
        "trace": deepcopy(resolved.get("trace") or {}),
    }
    resolved["models"] = {key: _normalise_section("models", value) for key, value in resolved["models"].items()}
    resolved["policy"] = _normalise_section("policy", resolved["policy"])
    resolved["window"] = _normalise_section("window", resolved["window"])
    resolved["goals"] = [_normalise_section("goals", row) for row in resolved["goals"]]
    resolved["workload"] = _normalise_section("workload", resolved["workload"])
    return AdaptiveExperiment(
        id=resolved["id"], dataset=resolved["dataset"], models=deepcopy(resolved["models"]),
        surfaces=deepcopy(resolved["surfaces"]), configurations=deepcopy(resolved["configurations"]),
        candidates=deepcopy(resolved["candidates"]), workload=deepcopy(resolved["workload"]),
        policy=deepcopy(resolved["policy"]), window=deepcopy(resolved["window"]),
        seed=resolved.get("seed", 0), output=resolved.get("output", "outputs"),
        labels=deepcopy(resolved.get("labels") or {}), task_params=deepcopy(resolved.get("taskParams") or {}),
        execution_options=deepcopy((resolved.get("execution") or {}).get("options") or {}),
        acceptance=deepcopy(resolved.get("acceptance") or {}),
        signals=tuple(deepcopy(resolved.get("signals") or [])), goals=tuple(deepcopy(resolved.get("goals") or [])),
        disturbances=tuple(deepcopy(resolved.get("disturbances") or [])),
        evaluation=deepcopy(resolved.get("evaluation") or {}), trace=deepcopy(resolved.get("trace") or {}),
        allow_mixed_models=resolved.get("allowMixedModels", False), base_dir=actual_base,
        resolved_definition=deepcopy(resolved),
    )


__all__ = ["ADAPTIVE_DEFINITION_VERSION", "AdaptiveExperiment", "WorkloadRequest", "Model", "Configuration",
           "Candidate", "PolicyRef", "Window", "Goal", "Acceptance", "SignalRef", "Disturbance", "Scenario",
           "adaptive_definition_schema", "experiment_definition", "load_adaptive_experiment"]
