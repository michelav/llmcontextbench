"""Request-blind policy contracts and reference resolution."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import random
import sys
from typing import Any, ClassVar, Mapping, Protocol, Sequence
from hashlib import sha256

from ctxbench.core.fingerprint import digest, file_digest


JSON = None | bool | int | float | str | list["JSON"] | dict[str, "JSON"]


class PolicyContractError(ValueError):
    """A policy failed validation or violated the request-blind decision contract."""


@dataclass(frozen=True, slots=True)
class CandidateRef:
    candidate_id: str
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Decision:
    candidate_id: str
    reason: str
    memo: Mapping[str, JSON] | None = None


@dataclass(frozen=True, slots=True)
class CandidateState:
    candidate_id: str
    observation_count: int
    selections: int
    last_status: str | None


class SystemState(Protocol):
    decision_index: int
    completed_requests: int
    memo: Mapping[str, JSON] | None

    def candidate(self, candidate_id: str) -> CandidateState: ...
    def rng(self) -> random.Random: ...


class PrefixSystemState:
    """Immutable policy view over prior outcomes with no request data attached."""

    __slots__ = ("decision_index", "completed_requests", "memo", "_counts", "_last", "_rng")

    def __init__(self, *, decision_index: int, observations: Sequence[Mapping[str, Any]],
                 memo: Mapping[str, JSON] | None, seed: int, decision_id: str):
        self.decision_index = decision_index
        self.completed_requests = len(observations)
        self.memo = dict(memo) if memo is not None else None
        self._counts: dict[str, int] = {}
        self._last: dict[str, str | None] = {}
        # Only candidate IDs and terminal status enter the policy view.
        for observation in observations:
            candidate_id = str(observation["candidateId"])
            self._counts[candidate_id] = self._counts.get(candidate_id, 0) + 1
            self._last[candidate_id] = str(observation["status"])
        derived_seed = int(sha256(f"{seed}:{decision_id}".encode()).hexdigest()[:16], 16)
        self._rng = random.Random(derived_seed)

    def candidate(self, candidate_id: str) -> CandidateState:
        return CandidateState(candidate_id, self._counts.get(candidate_id, 0),
                              self._counts.get(candidate_id, 0), self._last.get(candidate_id))

    def rng(self) -> random.Random:
        return self._rng


class Policy(Protocol):
    id: ClassVar[str]
    version: ClassVar[str]

    def __init__(self, **params: JSON) -> None: ...
    def decide(self, candidates: Sequence[CandidateRef], state: SystemState) -> Decision: ...


@dataclass(frozen=True, slots=True)
class PolicyReference:
    ref: str
    params: Mapping[str, JSON]
    policy_id: str
    version: str
    source_digest: str
    sources: tuple[str, ...] = ()


@contextmanager
def plugin_import_paths(paths: Sequence[str | Path]):
    added = [str(Path(path).expanduser().resolve()) for path in paths]
    old = list(sys.path)
    try:
        for path in reversed(added):
            if path not in sys.path:
                sys.path.insert(0, path)
        yield
    finally:
        sys.path[:] = old


def _builtin_classes() -> dict[str, type]:
    from ctxbench.adaptive.policies.random import RandomPolicy
    from ctxbench.adaptive.policies.round_robin import RoundRobinPolicy
    from ctxbench.adaptive.policies.static import StaticPolicy
    return {policy.id: policy for policy in (StaticPolicy, RandomPolicy, RoundRobinPolicy)}


BUILTIN = _builtin_classes


def resolve_policy(ref: str, params: Mapping[str, JSON], *, base_dir: Path | None = None,
                   plugin_paths: Sequence[str | Path] = (),
                   sources: Sequence[str] = ()) -> tuple[PolicyReference, Policy]:
    """Import a policy and digest its source.

    ``sources`` are extra files covered by the digest. With ``base_dir`` (planning) relative
    entries resolve against the definition directory; without it (execution, replay) they are
    the entries recorded in the plan, relative to the policy module's directory. The returned
    reference records them in that second form, so a run stays valid when the plug-in directory
    and the run directory move.
    """
    with plugin_import_paths(plugin_paths):
        if ":" not in ref:
            cls = _builtin_classes().get(ref)
            if cls is None:
                raise PolicyContractError(f"Unknown built-in policy {ref!r}")
            source_files = [Path(inspect.getsourcefile(cls) or "").resolve()]
        else:
            module_name, class_name = ref.split(":", 1)
            if not module_name or not class_name:
                raise PolicyContractError("External policy reference must use 'module:ClassName'")
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            if not inspect.isclass(cls):
                raise PolicyContractError(f"Policy class not found: {ref}")
            source_file = inspect.getsourcefile(cls) or getattr(module, "__file__", None)
            if not source_file:
                raise PolicyContractError(f"Could not locate source for policy {ref}")
            source_files = [Path(source_file).resolve()]
        module_dir = source_files[0].parent
        for source in sources:
            source_path = Path(source).expanduser()
            if not source_path.is_absolute():
                source_path = (base_dir if base_dir is not None else module_dir) / source_path
            source_files.append(source_path.resolve())
        source_files = list(dict.fromkeys(source_files))
        missing = [path for path in source_files if not path.is_file()]
        if missing:
            raise PolicyContractError(f"Policy source file does not exist: {missing[0]}")
        if not getattr(cls, "id", None) or not getattr(cls, "version", None) or not callable(getattr(cls, "decide", None)):
            raise PolicyContractError(f"Policy {ref!r} must define id, version, and decide")
        source_digest = digest([(path.name, file_digest(path)) for path in source_files])
        try:
            instance = cls(**dict(params))
        except Exception as exc:
            raise PolicyContractError(f"Invalid parameters for policy {ref!r}: {exc}") from exc
        recorded = tuple(Path(os.path.relpath(path, module_dir)).as_posix() for path in source_files[1:])
        return PolicyReference(ref, dict(params), str(cls.id), str(cls.version), source_digest,
                               recorded), instance


def verify_policy(reference: PolicyReference, *,
                  plugin_paths: Sequence[str | Path] = ()) -> Policy:
    resolved, policy = resolve_policy(reference.ref, reference.params,
                                      plugin_paths=plugin_paths, sources=reference.sources)
    if (resolved.policy_id, resolved.version, resolved.source_digest) != (
            reference.policy_id, reference.version, reference.source_digest):
        raise PolicyContractError("Policy source changed since planning; create a fresh adaptive plan.")
    return policy


def validate_decision(decision: Any, candidate_ids: set[str]) -> Decision:
    if not isinstance(decision, Decision):
        raise PolicyContractError("Policy must return a Decision")
    if decision.candidate_id not in candidate_ids:
        raise PolicyContractError(f"Policy selected unknown candidate {decision.candidate_id!r}")
    if not isinstance(decision.reason, str) or not decision.reason.strip():
        raise PolicyContractError("Policy decision requires a non-empty reason")
    if decision.memo is not None:
        try:
            serialized = json.dumps(decision.memo, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise PolicyContractError("Policy memo must contain JSON values") from exc
        if len(serialized.encode("utf-8")) > 16 * 1024:
            raise PolicyContractError("Policy memo exceeds 16 KiB")
    return decision
