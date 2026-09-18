from __future__ import annotations

import json

from ctxbench.util.artifacts import (
    canonical_trial_identity,
    evaluation_filename,
    response_filename,
    trialspec_filename,
)
from ctxbench.util.ids import trialspec_id


def test_canonical_trial_identity_uses_target_task_and_repetition_terms():
    identity = canonical_trial_identity(
        experiment_id="exp-1",
        task_id="q_year",
        instance_id="cv-demo",
        provider="mock",
        model_name="mock-a",
        strategy="inline",
        representation="json",
        configuration_id="test-config",
        repetition=2,
    )

    assert json.loads(identity)["configuration"] == {"strategy": "inline", "representation": "json"}
    assert json.loads(identity)["configurationId"] == "test-config"


def test_trialspec_id_uses_target_identity_builder():
    identity = trialspec_id(
        experiment_id="exp-1",
        task_id="q_summary",
        context_id="cv-demo",
        provider="mock",
        model_name="mock-a",
        strategy="remote_mcp",
        representation="json",
        configuration_id="test-config",
        repetition=1,
    )

    assert json.loads(identity)["configuration"] == {"strategy": "remote_mcp", "representation": "json"}


def test_target_filename_helpers_preserve_existing_prefixes():
    assert trialspec_filename("exp demo", "trial-1") == "rs_exp_demo_trial-1.json"
    assert response_filename("exp demo", "trial-1") == "rr_exp_demo_trial-1.json"
    assert evaluation_filename("exp demo", "trial-1") == "re_exp_demo_trial-1.json"
