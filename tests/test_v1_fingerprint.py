import json
from pathlib import Path

import pytest

from ctxbench.commands.plan import plan_command
from ctxbench.commands.execute import execute_command
from ctxbench.benchmark.provisioning import validate_manifest
from ctxbench.benchmark.fingerprint import verify_snapshot
from ctxbench.benchmark.execution_records import attempts_for_trial, begin_attempt, finish_attempt
from tests.test_v1_definitions import definition


def planned(tmp_path):
    path = tmp_path / 'definition.json'
    path.write_text(json.dumps(definition()))
    root = tmp_path / 'run'
    plan_command(str(path), str(root), cache_dir=tmp_path / 'cache')
    return path, root


def test_frozen_plan_ignores_source_edits_and_has_full_ids(tmp_path, capsys):
    path, root = planned(tmp_path)
    path.write_text('{}')
    manifest = validate_manifest(root)
    assert manifest['schemaVersion'] == 3
    assert manifest['provisioningArtifactVersion'] == 4
    assert manifest['executionRecordVersion'] == 1
    trials = [json.loads(line) for line in (root / 'trials.jsonl').read_text().splitlines()]
    assert all(len(row['trialId']) == 64 for row in trials)
    assert execute_command(str(root / 'trials.jsonl')) == 0
    trial_id = trials[0]['trialId']
    assert execute_command(str(root / 'trials.jsonl')) == 0
    attempts = attempts_for_trial(root, trial_id)
    assert len(attempts) == 1
    failed_record = begin_attempt(root, trial_id=trial_id, experiment_id=manifest['experimentId'],
                                  execution_fingerprint=manifest['executionFingerprint'])
    failed_result = dict(attempts[0]['result'], status='error', errorMessage='recorded failure')
    finish_attempt(root, failed_record, failed_result)
    assert execute_command(str(root / 'trials.jsonl')) == 0
    assert len(attempts_for_trial(root, trial_id)) == 2

    begin_attempt(root, trial_id=trial_id, experiment_id=manifest['experimentId'],
                  execution_fingerprint=manifest['executionFingerprint'])
    with pytest.raises(ValueError, match='uncertain started attempts'):
        execute_command(str(root / 'trials.jsonl'))
    from ctxbench.commands.status import status_command
    assert status_command(str(root)) == 0
    status_output = capsys.readouterr().out
    execute_row = next(line.split() for line in status_output.splitlines() if line.startswith("execute"))
    assert execute_row == ["execute", str(len(trials)), str(len(trials) - 1), "0", "1", "0"]
    assert execute_command(str(root / 'trials.jsonl'), retry_uncertain=True) == 0
    attempts = attempts_for_trial(root, trial_id)
    assert [item['state'] for item in attempts] == ['succeeded', 'failed', 'started', 'succeeded']
    assert len({item['attemptId'] for item in attempts}) == 4


def test_tampered_snapshot_rejected(tmp_path):
    _, root = planned(tmp_path)
    (root / 'resolved.json').write_text('{}')
    with pytest.raises(ValueError, match='Frozen plan changed'):
        validate_manifest(root)


def test_implementation_change_rejected_only_for_execution(tmp_path, monkeypatch):
    _, root = planned(tmp_path)
    monkeypatch.setattr('ctxbench.benchmark.fingerprint.implementation_digest', lambda: 'changed')
    manifest = validate_manifest(root)
    verify_snapshot(root, manifest)
    with pytest.raises(ValueError, match='implementation changed'):
        execute_command(str(root / 'trials.jsonl'))


def test_dataset_change_rejected(tmp_path, monkeypatch):
    _, root = planned(tmp_path)
    monkeypatch.setattr('ctxbench.benchmark.fingerprint.tree_digest', lambda _: 'changed')
    with pytest.raises(ValueError, match='dataset changed'):
        execute_command(str(root / 'trials.jsonl'))


def test_unknown_artifact_version_rejected(tmp_path):
    _, root = planned(tmp_path)
    path = root / 'manifest.json'
    data = json.loads(path.read_text()); data['provisioningArtifactVersion'] = 999
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='previous benchmark version'):
        validate_manifest(root)
