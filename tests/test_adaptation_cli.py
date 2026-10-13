import json
import runpy
import subprocess
import sys

import pytest

from ctxbench.cli import build_parser, main
from ctxbench.adapters.repoqa import workflow


OPERATIONS = [
    ('prepare', ['--context-limit', '200000', '--output-reservation', '2048'],
     {'experiment': 'experiment.repoqa-adaptive.json', 'context_limit': 200000, 'output_reservation': 2048}),
    ('calibrate', ['--prepared', 'prepared.json'],
     {'prepared': 'prepared.json', 'delay_ms': 0, 'seed': 20261001, 'resume': False, 'retry_uncertain': False}),
    ('freeze', ['--prepared', 'prepared.json'], {'prepared': 'prepared.json', 'application_slo_ms': None}),
    ('episode', ['--prepared', 'prepared.json', '--scenario', 'stationary', '--policy', 'all'],
     {'prepared': 'prepared.json', 'scenario': 'stationary', 'policy': 'all', 'seed': 20261001,
      'resume': False, 'retry_uncertain': False}),
    ('analyze', [], {'bootstrap_replicates': 10000}),
]


@pytest.mark.parametrize('operation,arguments,expected', OPERATIONS)
def test_entry_points_share_arguments_and_json(operation, arguments, expected, monkeypatch, capsys):
    calls = []
    def operation_mock(**kwargs):
        calls.append(kwargs)
        return {'operation': operation}
    monkeypatch.setattr(workflow, operation, operation_mock)
    legacy = runpy.run_path('tools/repoqa/run_adaptation.py')['main']
    arguments = [operation, *arguments, '--output', 'study']
    for entry, prefix in ((main, ['adaptation', 'repoqa']), (legacy, [])):
        assert entry(prefix + arguments) == 0
        output = capsys.readouterr()
        assert json.loads(output.out) == {'operation': operation}
        if operation in ('calibrate', 'episode'):
            assert 'Provider execution spends API tokens' in output.err
        else:
            assert not output.err
    assert calls == [dict(expected, output='study')] * 2


@pytest.mark.parametrize('exception,code,message', [
    (ValueError('invalid study'), 1, 'invalid study'),
    (KeyboardInterrupt(), 130, 'Execution interrupted'),
])
def test_shared_error_and_interruption_handling(exception, code, message, monkeypatch, capsys):
    def fail(**kwargs):
        raise exception
    monkeypatch.setattr(workflow, 'analyze', fail)
    legacy = runpy.run_path('tools/repoqa/run_adaptation.py')['main']
    for entry, prefix in ((main, ['adaptation', 'repoqa']), (legacy, [])):
        assert entry(prefix + ['analyze', '--output', 'study']) == code
        output = capsys.readouterr()
        assert not output.out
        assert message in output.err


@pytest.mark.parametrize('arguments', [[], ['repoqa'], ['repoqa', 'prepare'],
    ['repoqa', 'episode', '--prepared', 'p', '--output', 's', '--policy', 'unknown', '--scenario', 'stationary'],
    ['repoqa', 'calibrate', '--prepared', 'p', '--output', 's', '--delay-ms', '999'],
    ['repoqa', 'calibrate', '--prepared', 'p', '--output', 's', '--execute-providers']])
def test_invalid_arguments(arguments):
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(['adaptation', *arguments])
    assert error.value.code == 2


def test_help_is_lazy_in_fresh_process():
    code = '''
import sys
from ctxbench.cli import main
for args in (['--help'], ['adaptation', '--help'], ['adaptation', 'repoqa', '--help'],
             *(['adaptation', 'repoqa', name, '--help'] for name in
               ('prepare', 'calibrate', 'freeze', 'episode', 'analyze'))):
    try:
        main(args)
    except SystemExit as exc:
        assert exc.code == 0
assert 'ctxbench.adapters.repoqa.workflow' not in sys.modules
assert 'repoqa.compute_score' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Experimental' in result.stdout


def test_resume_options_reach_workflow(monkeypatch):
    seen = []
    monkeypatch.setattr(workflow, 'calibrate', lambda **kwargs: seen.append(kwargs))
    assert main(['adaptation', 'repoqa', 'calibrate', '--prepared', 'p', '--output', 's',
                 '--seed', '20261003', '--delay-ms', '250', '--resume', '--retry-uncertain']) == 0
    assert seen == [dict(prepared='p', output='s', seed=20261003, delay_ms=250,
                         resume=True, retry_uncertain=True)]


def test_mocked_study_entry_point_parity(tmp_path, monkeypatch, capsys):
    """Real preparation, packets, freeze, replay and analysis; only execution is fake."""
    from pathlib import Path
    from ctxbench.adaptive import runner
    from ctxbench.adaptive.recovery import sealed_read, sealed_write
    from ctxbench.adapters.repoqa.adaptation_analysis import load_episode
    from tests.test_adaptive_runner import Clock, execute

    payload = json.loads(Path('tests/fixtures/repoqa_surface_experiment.json').read_text())
    payload['dataset']['root'] = str(Path('datasets/repoqa').resolve())
    payload['scope']['instances'] = []
    payload['execution'] = {'repeats': 2}
    experiment = tmp_path / 'experiment.json'
    experiment.write_text(json.dumps(payload))
    monkeypatch.setitem(sys.modules, 'tiktoken', None)
    monkeypatch.setitem(sys.modules, 'matplotlib', None)
    class Engine:
        def close(self):
            pass
    monkeypatch.setattr('ctxbench.ai.engine.Engine', Engine)
    calls = []
    def mock_execution(trial, engine, **kwargs):
        calls.append(trial.trialId)
        return execute(trial, engine, **kwargs)
    def run(*args, **kwargs):
        return runner.run_episode(*args, **kwargs, execution=mock_execution, monotonic=Clock())
    monkeypatch.setattr(workflow, 'run_episode', run)
    legacy = runpy.run_path('tools/repoqa/run_adaptation.py')['main']
    results = []
    for entry, prefix, name in ((main, ['adaptation', 'repoqa'], 'integrated'), (legacy, [], 'legacy')):
        output = tmp_path / name
        def invoke(operation, *args, expected=0):
            assert entry([*prefix, operation, '--output', str(output), *args]) == expected
            captured = capsys.readouterr()
            return json.loads(captured.out) if expected == 0 else captured.err
        invoke('prepare', '--experiment', str(experiment), '--context-limit', '200000',
               '--output-reservation', '2048')
        prepared_args = ['--prepared', str(output / 'prepared.json')]
        invoke('calibrate', *prepared_args)
        completed = len(calls)
        invoke('calibrate', *prepared_args, '--resume')
        assert len(calls) == completed
        for delay in (100, 250, 500, 1000):
            invoke('calibrate', *prepared_args, '--delay-ms', str(delay))
        frozen = invoke('freeze', *prepared_args)
        assert frozen['scenarios'] == ['stationary']
        assert 'stationary results only' in invoke('episode', *prepared_args, '--policy', 'all',
            '--scenario', 'degradation-recovery', expected=1)
        episodes = invoke('episode', *prepared_args, '--policy', 'all', '--scenario', 'stationary')
        assert [Path(row['output']).name for row in episodes] == list(workflow.ARMS)
        assert [row['completedRequests'] for row in episodes] == [64] * 4
        completed = len(calls)
        invoke('episode', *prepared_args, '--policy', 'all', '--scenario', 'stationary', '--resume')
        assert len(calls) == completed
        summary = invoke('analyze', '--bootstrap-replicates', '5')
        assert len(summary['episodes']) == 4
        assert (output / 'analysis/timeline.csv').is_file()
        decisions = []
        for row in episodes:
            root = Path(row['output'])
            load_episode(root)  # Validates canonical artifacts against recovery packets.
            decisions.append([json.loads(line) for line in (root / 'decisions.jsonl').read_text().splitlines()])
        study = sealed_read(output / 'prepared.json')
        results.append((study, {key: frozen[key] for key in ('estimates', 'scenarios', 'latencyObjectiveMs',
                         'selectedDelayMs', 'costProjection')}, decisions, summary['primary']))
        damaged = dict(frozen, baselineHash='changed')
        sealed_write(output / 'frozen.json', damaged)
        assert 'frozen provenance mismatch' in invoke('episode', *prepared_args, '--policy', 'all',
            '--scenario', 'stationary', '--resume', expected=1)
        assert len(calls) == completed
    assert results[0] == results[1]
