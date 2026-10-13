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
