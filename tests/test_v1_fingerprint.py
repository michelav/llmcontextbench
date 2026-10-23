import json
from pathlib import Path

import pytest

from ctxbench.commands.plan import plan_command
from ctxbench.commands.execute import execute_command
from ctxbench.benchmark.provisioning import validate_manifest
from ctxbench.benchmark.fingerprint import verify_snapshot
from tests.test_v1_definitions import definition


def planned(tmp_path):
    path = tmp_path / 'definition.json'
    path.write_text(json.dumps(definition()))
    root = tmp_path / 'run'
    plan_command(str(path), str(root), cache_dir=tmp_path / 'cache')
    return path, root


def test_frozen_plan_ignores_source_edits_and_has_full_ids(tmp_path):
    path, root = planned(tmp_path)
    path.write_text('{}')
    manifest = validate_manifest(root)
    assert manifest['schemaVersion'] == 3
    trials = [json.loads(line) for line in (root / 'trials.jsonl').read_text().splitlines()]
    assert all(len(row['trialId']) == 64 for row in trials)
    assert execute_command(str(root / 'trials.jsonl')) == 0


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
