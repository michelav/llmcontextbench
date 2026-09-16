import runpy
from pathlib import Path

import pytest


@pytest.fixture
def exporter():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/repoqa/export_repoqa_outputs.py'))


def test_repoqa_export_keeps_arbitrary_configuration_ids_distinct(exporter):
    labels = []
    for configuration_id in ('a__b', 'a_b'):
        response = {'trialId': 'trial', 'modelId': 'mock', 'configurationId': configuration_id, 'strategy': 'local_function', 'representation': 'json'}
        row = exporter['build_repoqa_output_row'](native_task={'repo': 'fixture'}, response=response, response_text='code')
        assert row['ctxbench']['configurationId'] == configuration_id
        assert row['ctxbench']['representation'] == 'json'
        labels.append(exporter['group_label'](row))
    assert labels[0] != labels[1]


def test_repoqa_export_selectors_and_legacy_rejection(exporter, tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ['export', '--responses', str(tmp_path / 'responses.jsonl'), '--dataset-root', str(tmp_path), '--output', str(tmp_path / 'native.jsonl'), '--configuration', 'a', '--representation', 'json'])
    args = exporter['parse_args']()
    assert args.configuration == ['a']
    assert args.representation == ['json']
    with pytest.raises(ValueError, match='previous benchmark version'):
        exporter['main']()
