from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ctxbench.adapters.lattes.mcp_server import LattesMCPServer
from ctxbench.adapters.lattes.provider import LattesProvider
from ctxbench.adapters.lattes.tools import LattesToolService


def _contexts_dir() -> str:
    return str((Path.cwd() / "datasets" / "lattes" / "context").resolve())


def test_provider_returns_resource_payloads_and_filters_years():
    provider = LattesProvider()

    profile = provider.get_profile(
        contexts_dir=_contexts_dir(),
        lattes_id="5521922960404236",
    )
    publications = provider.get_publications(
        contexts_dir=_contexts_dir(),
        lattes_id="5521922960404236",
        start_year=2025,
        end_year=2026,
    )

    assert isinstance(profile, dict)
    assert "summary" in profile
    assert isinstance(publications, dict)
    assert publications["items"]
    assert all(2025 <= int(item["year"]) <= 2026 for item in publications["items"] if isinstance(item, dict) and "year" in item)


def test_tool_service_exposes_resource_tools():
    service = LattesToolService(contexts_dir=_contexts_dir())

    tools = service.list_tools()
    profile = service.call_tool(
        "get_profile",
        {"lattes_id": "5521922960404236"},
    ).content
    education = service.call_tool(
        "get_education",
        {"lattes_id": "5521922960404236", "start_year": 1995, "end_year": 2000},
    ).content

    assert "get_profile" in {tool.name for tool in tools}
    assert "get_publications" in {tool.name for tool in tools}
    assert isinstance(profile, dict)
    assert isinstance(education, dict)
    assert "items" in education


def test_provider_returns_grouped_supervisions():
    provider = LattesProvider()

    supervisions = provider.get_supervisions(
        contexts_dir=_contexts_dir(),
        lattes_id="5521922960404236",
    )

    assert isinstance(supervisions, dict)
    assert "masters" in supervisions
    assert "doctoral" in supervisions
    assert "undergraduate" in supervisions
    assert isinstance(supervisions["masters"]["completed"], list)
    assert isinstance(supervisions["masters"]["ongoing"], list)


def test_mcp_server_routes_resource_tools():
    server = LattesMCPServer(contexts_dir=_contexts_dir())

    tools = server.list_tools()
    result = server.call_tool(
        "get_profile",
        {"lattes_id": "5521922960404236"},
    )

    assert any(tool.name == "get_profile" for tool in tools)
    assert isinstance(result.content, dict)


def test_mcp_server_uses_ctxbench_public_name():
    server = LattesMCPServer(contexts_dir=_contexts_dir())

    assert server.app.name == "ctxbench-lattes"
