from __future__ import annotations

import hashlib
import json
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
    representation: str
    surface: str
    configurationId: str
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
    representation: str,
    repetition: int,
    *,
    configuration_id: str,
    surface: str = "",
) -> str:
    configuration = {"strategy": strategy, "representation": representation}
    if surface:
        configuration["surface"] = surface
    return json.dumps({
        "identityVersion": 2,
        "experimentId": experiment_id,
        "taskId": task_id,
        "instanceId": instance_id,
        "provider": provider,
        "modelName": model_name,
        "configurationId": configuration_id,
        "configuration": configuration,
        "repeatIndex": repetition,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)



def canonical_identity_from_trial(trial: TrialIdentity) -> str:
    return canonical_trial_identity(
        experiment_id=trial.experimentId,
        task_id=trial.taskId,
        instance_id=trial.instanceId,
        provider=trial.provider,
        model_name=trial.modelName or "",
        strategy=trial.strategy,
        representation=trial.representation,
        surface=trial.surface,
        configuration_id=trial.configurationId,
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
