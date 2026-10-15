import json
from pathlib import Path

import pytest

from ctxbench.adapters.repoqa.provider import RepoQAProvider
from ctxbench.adapters.repoqa.tools import RepoQAToolService, REPOQA_LEAN_OPERATIONS
from ctxbench.adapters.repoqa.mcp_server import RepoQAMCPServer
from ctxbench.ai.runtime import MCPRuntime

ROOT = Path(__file__).parent / 'fixtures/repoqa_tools_dataset/context'
WORKSPACE = 'repoqa-workspace-1'


def test_flat_filters_retrieval_and_payload_sizes():
    provider = RepoQAProvider(contexts_dir=ROOT)
    symbols = provider.list_symbols_lean(WORKSPACE)
    assert len(symbols) == len({s['symbol_id'] for s in symbols}) == 3
    assert [s['name'] for s in symbols] == ['Greeter', 'Greeter.greet', 'helper']
    assert [s['name'] for s in provider.list_symbols_lean(WORKSPACE, kind='function')] == ['Greeter.greet', 'helper']
    assert provider.list_symbols_lean(WORKSPACE, path='src/') == symbols
    assert provider.list_symbols_lean(WORKSPACE, kind='   ') == symbols
    assert provider.list_symbols_lean(WORKSPACE, path='other') == []
    assert symbols == provider.list_symbols_lean(WORKSPACE)
    for symbol in symbols:
        original = provider.get_symbol(WORKSPACE, symbol['symbol_id'])
        assert provider.get_symbol_lean(WORKSPACE, symbol['symbol_id']) == {'code': original['code']}
    for method in ('list_files', 'list_symbols'):
        full = getattr(provider, method)(WORKSPACE)
        lean = getattr(provider, method + '_lean')(WORKSPACE)
        assert len(json.dumps(lean).encode()) < len(json.dumps(full).encode())
    assert provider.read_file_lean(WORKSPACE, 'src/example.py') == {'content': provider.read_file(WORKSPACE, 'src/example.py')['content']}


@pytest.mark.parametrize('name, extra', [
    ('list_files_lean', {}), ('list_symbols_lean', {'kind': 'function'}),
    ('get_symbol_lean', {'symbol_id': 'existing-helper-id'}),
    ('get_symbol_lean', {'symbol_id': 'missing'}),
    ('read_file_lean', {'path': 'src/example.py'}),
    ('read_file_lean', {'path': 'src/hidden.py'}),
])
def test_lean_protocol_schema_and_content_parity(name, extra):
    service = RepoQAToolService(contexts_dir=str(ROOT), allowed_operations=list(REPOQA_LEAN_OPERATIONS))
    runtime = MCPRuntime.for_local_server(RepoQAMCPServer(contexts_dir=str(ROOT), allowed_operations=list(REPOQA_LEAN_OPERATIONS)))
    try:
        assert runtime.list_tools() == service.list_tools()
        arguments = {'workspace_id': WORKSPACE, **extra}
        direct = service.call_tool(name, arguments)
        actual = runtime.call_tool(name, arguments)
        assert actual.content == direct.content
        assert actual.is_error == direct.is_error
    finally:
        runtime.close()
        service.close()


def test_find_symbol_ranks_callables_and_validates_arguments():
    provider = RepoQAProvider(contexts_dir=ROOT)
    found = provider.find_symbol(WORKSPACE, 'Greet a person by name', 5)
    assert [s['name'] for s in found] == ['Greeter.greet', 'helper']
    assert found[0] == {'symbol_id': found[0]['symbol_id'], 'name': 'Greeter.greet', 'path': 'src/example.py',
                        'code': provider.get_symbol(WORKSPACE, found[0]['symbol_id'])['code']}
    assert [s['name'] for s in provider.find_symbol(WORKSPACE, 'strip value', 1)] == ['helper']
    service = RepoQAToolService(contexts_dir=ROOT, allowed_operations=['find_symbol'])
    assert [t.name for t in service.list_tools()] == ['find_symbol']
    assert service.call_tool('find_symbol', {'workspace_id': WORKSPACE, 'query': 'the of'}).is_error
    assert service.call_tool('find_symbol', {'workspace_id': WORKSPACE, 'query': 'greet', 'k': 'two'}).is_error
    assert not service.call_tool('find_symbol', {'workspace_id': WORKSPACE, 'query': 'greet', 'k': None}).is_error
