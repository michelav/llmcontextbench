"""Execute the analysis against small canonical fixtures, without a Jupyter kernel."""
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("with_tools", [True, False])
def test_analysis_notebook_current_contract(tmp_path, monkeypatch, with_tools):
    monkeypatch.setenv('MPLCONFIGDIR', str(tmp_path / 'mpl'))
    pytest.importorskip('pandas')
    matplotlib = pytest.importorskip('matplotlib')
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import IPython.display
    monkeypatch.setattr(IPython.display, 'display', lambda *a, **kw: None)
    monkeypatch.setattr(plt, 'show', lambda *a, **kw: plt.close('all'))
    repo = Path(__file__).resolve().parents[1]
    root = tmp_path / 'input'
    root.mkdir()
    definitions = {
        'alpha': {'strategy': 'inline', 'representation': 'json', 'surface': 'full'},
        'beta': {'strategy': 'inline', 'representation': 'html', 'surface': 'full'},
        'gamma': {'strategy': 'local_function', 'representation': 'json', 'surface': 'ops'},
        'delta': {'strategy': 'local_function', 'representation': 'json', 'surface': 'ops'},
    }
    manifest = {'provisioningArtifactVersion': 2, 'surfaces': {'full': {'type': 'full_context'}, 'ops': {'type': 'operations', 'operations': ['get_evidence']}}, 'configurations': definitions, 'experimentId': 'fixture', 'evaluation': {'judges': []}}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    trials, responses, evals, votes = [], [], [], []
    for model in ('gpt1', 'gpt2', 'gemini1', 'gemini2'):
        for configuration_id, definition in definitions.items():
            for index, task in enumerate(('q_en', 'q_year')):
                trial_id = f'{model}-{configuration_id}-{task}'
                treatment = dict(configurationId=configuration_id, **definition)
                row = dict(trialId=trial_id, experimentId='fixture', instanceId='i1', taskId=task, modelId=model, model=model, provider='mock', repeatIndex=1, taskStatement='Fixture task', taskTemplate='Fixture task', taskTags=['objective' if index else 'descriptive'], contextBlocks=['summary'], validationType='judge', dataset={'id': 'fixture', 'version': '1'}, metadata=treatment, **treatment)
                trials.append(row)
                responses.append(dict(row, response='The fixture contains the requested evidence.', status='success', timing={'durationMs': 1000}, usage={'inputTokens': 8, 'outputTokens': 2, 'totalTokens': 10}, metricsSummary={'inputTokens': 8, 'outputTokens': 2, 'totalTokens': 10, 'totalDurationMs': 1000, 'toolCalls': int(with_tools and definition['strategy'] != 'inline'), 'mcpToolCalls': 0, 'functionCalls': int(with_tools and definition['strategy'] != 'inline'), 'modelCalls': 1}, traceRef=f'traces/executions/{trial_id}.json'))
                trace_path = root / 'traces' / 'executions' / f'{trial_id}.json'
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                trace_path.write_text(json.dumps({'toolCalls': [{'name': 'get_evidence', 'arguments': {}}] if with_tools and definition['strategy'] != 'inline' else []}))
                rating = 'meets' if index else 'misses'
                evals.append(dict(row, status='evaluated', evaluationMethod='judge', judgeCount=3, judgeErrorCount=0, outcome={criterion: {'rating': rating, 'agreement': True} for criterion in ('correctness', 'completeness')}, evaluationInputTokens=6, evaluationOutputTokens=3, evaluationTotalTokens=9, evaluationDurationMs=300))
                for judge in ('j1', 'j2', 'j3'):
                    votes.append(dict(trialId=trial_id, experimentId='fixture', instanceId='i1', taskId=task, surface=definition['surface'], judgeId=judge, provider='mock', model=judge, error=None, status='evaluated', criterias={criterion: {'rating': rating, 'justification': 'fixture'} for criterion in ('correctness','completeness')}, inputTokens=2, outputTokens=1, totalTokens=3, durationMs=100))
    for name, rows in [('trials',trials), ('responses',responses), ('evals',evals), ('judge_votes',votes)]:
        (root / f'{name}.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    monkeypatch.setenv('CTXBENCH_ANALYSIS_INPUT', str(root))
    monkeypatch.setenv('CTXBENCH_ANALYSIS_OUTPUT', str(tmp_path / 'analysis'))
    monkeypatch.chdir(tmp_path)
    notebook = json.loads((repo / 'outputs_analysis.ipynb').read_text())
    namespace = {}
    for index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] == 'code':
            assert cell['outputs'] == []
            assert cell['execution_count'] is None
            exec(compile(''.join(cell['source']), f'notebook-cell-{index}', 'exec'), namespace)
    runs = namespace['runs']
    assert len(runs) == 32
    assert set(runs.configurationId) == set(definitions)
    assert runs.full_unanimous_meet.sum() == 16
    assert runs.total_cost_tokens_corrected.sum() == 32 * 19
    assert namespace['runs_tool_base']['strategy'].eq('local_function').all()
    assert runs.status_answer.eq("success").all()
    assert namespace["HAS_TOOL_EVENTS"] is with_tools
    if with_tools:
        assert set(namespace["tool_entity_model"]["configurationId"]) == {"gamma", "delta"}
        assert namespace["tool_entity_model"]["total_runs"].eq(1).all()
