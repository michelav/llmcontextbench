from __future__ import annotations

import re

from ctxbench.util.artifacts import canonical_trial_identity


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return normalized or "item"


def trialspec_id(
    experiment_id: str,
    task_id: str,
    context_id: str,
    provider: str,
    model_name: str,
    strategy: str,
    representation: str,
    repetition: int,
    *,
    configuration_id: str,
) -> str:
    return canonical_trial_identity(
        experiment_id=experiment_id,
        task_id=task_id,
        instance_id=context_id,
        provider=provider,
        model_name=model_name,
        strategy=strategy,
        representation=representation,
        repetition=repetition,
        configuration_id=configuration_id,
    )


runspec_id = trialspec_id
