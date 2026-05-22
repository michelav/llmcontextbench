from __future__ import annotations

import hashlib
import re
from typing import Protocol


class TrialIdentity(Protocol):
    trialId: str
    experimentId: str
    taskId: str
    instanceId: str
    provider: str
    modelName: str | None
    strategy: str
    format: str
    repeatIndex: int


def sanitize_experiment_id(experiment_id: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", experiment_id).strip("_")
    return sanitized or "experiment"


def canonical_trial_identity(
    experiment_id: str,
    task_id: str,
    instance_id: str,
    provider: str,
    model_name: str,
    strategy: str,
    format_name: str,
    repetition: int,
) -> str:
    return "|".join(
        [
            experiment_id or "",
            task_id or "",
            instance_id or "",
            provider or "",
            model_name or "",
            strategy or "",
            format_name or "",
            str(repetition),
        ]
    )


def canonical_identity_from_trial(trial: TrialIdentity) -> str:
    return canonical_trial_identity(
        experiment_id=trial.experimentId,
        task_id=trial.taskId,
        instance_id=trial.instanceId,
        provider=trial.provider,
        model_name=trial.modelName or "",
        strategy=trial.strategy,
        format_name=trial.format,
        repetition=trial.repeatIndex,
    )


def build_short_ids(identities: list[str], min_length: int = 10) -> list[str]:
    if not identities:
        return []
    digests = [hashlib.sha256(identity.encode("utf-8")).hexdigest() for identity in identities]
    for length in range(min_length, len(digests[0]) + 1):
        short_ids = [digest[:length] for digest in digests]
        if len(short_ids) == len(set(short_ids)):
            return short_ids
    return digests


def run_id_from_identity(identity: str, min_length: int = 10) -> str:
    return build_short_ids([identity], min_length=min_length)[0]


def artifact_filename(prefix: str, experiment_id: str, trial_id: str) -> str:
    return f"{prefix}_{sanitize_experiment_id(experiment_id)}_{trial_id}.json"


def trialspec_filename(experiment_id: str, trial_id: str) -> str:
    return artifact_filename("rs", experiment_id, trial_id)


def response_filename(experiment_id: str, trial_id: str) -> str:
    return artifact_filename("rr", experiment_id, trial_id)


def evaluation_filename(experiment_id: str, trial_id: str) -> str:
    return artifact_filename("re", experiment_id, trial_id)


# Backward-compatible aliases for remaining internal legacy callers.
RunIdentity = TrialIdentity
canonical_run_identity = canonical_trial_identity
canonical_identity_from_run = canonical_identity_from_trial
runspec_filename = trialspec_filename
runresult_filename = response_filename
evalresult_filename = evaluation_filename
