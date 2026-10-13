from pathlib import Path

import pytest

from ctxbench.adapters.repoqa.mcp_server import RepoQAMCPServer
from ctxbench.adapters.lattes.mcp_server import LattesMCPServer
from ctxbench.ai.runtime import MCPRuntime


@pytest.mark.parametrize('name, extra, error', [
    ('read_file', {'path': 'missing.py'}, True),
    ('read_file', {'path': 'src/hidden.py'}, True),
    ('get_symbol', {'symbol_id': 'missing'}, True),
    ('read_file', {'path': 'src/example.py'}, False),
    ('get_symbol', {'symbol_id': 'existing-helper-id'}, False),
])
def test_repoqa_protocol_preserves_service_result(name, extra, error):
    server = RepoQAMCPServer(contexts_dir=str(Path(__file__).parent / 'fixtures/repoqa_tools_dataset/context'))
    arguments = {'workspace_id': 'repoqa-workspace-1', **extra}
    direct = server.call_tool(name, arguments)
    runtime = MCPRuntime.for_local_server(server)
    try:
        actual = runtime.call_tool(name, arguments)
        assert actual.is_error is direct.is_error is error
        assert actual.content == direct.content
    finally:
        runtime.close()


def test_lattes_missing_researcher_raises_at_service_boundary(tmp_path):
    server = LattesMCPServer(contexts_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        server.call_tool(server.list_tools()[0].name, {'lattes_id': 'missing'})
    server.close()


def test_recoverable_operation_error_reaches_next_model_input_and_trace():
    from ctxbench.ai.models.base import AIRequest, ModelResponse, ToolCall
    from ctxbench.ai.strategies.local_mcp import LocalMCPStrategy
    from ctxbench.ai.trace import TraceCollector

    class Model:
        def generate(self, model_input, request, trace=None):
            if model_input.tool_results:
                assert model_input.tool_results[0].is_error is True
                return ModelResponse(text='Recovered')
            return ModelResponse(requested_tool_calls=[ToolCall(
                name='read_file', arguments={'workspace_id': 'repoqa-workspace-1', 'path': 'missing'},
            )])

    server = RepoQAMCPServer(contexts_dir=str(Path(__file__).parent / 'fixtures/repoqa_tools_dataset/context'))
    runtime = MCPRuntime.for_local_server(server)
    trace = TraceCollector()
    try:
        result = LocalMCPStrategy(runtime).execute(Model(), AIRequest(
            question='Read file', context='', provider_name='fixture', model_name='fixture',
            strategy_name='local_mcp', context_representation='json',
            metadata={'instance_id': 'repoqa-workspace-1'},
        ), trace)
        assert result.error is None
        assert result.answer == 'Recovered'
        assert result.tool_calls[0]['isError'] is True
        assert any(e.metadata.get('is_error') is True for e in trace.events)
    finally:
        runtime.close()
