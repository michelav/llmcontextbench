from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "ctxbench"


def _python_files(package: str) -> list[Path]:
    return sorted((SRC_ROOT / package).rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _has_import_with_prefix(path: Path, prefix: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in _imported_modules(path)
    )


def test_import_boundary_benchmark_modules_do_not_import_concrete_lattes_adapter() -> None:
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _python_files("benchmark")
        if _has_import_with_prefix(path, "ctxbench.adapters.lattes")
    ]

    assert offenders == []


def test_import_boundary_dataset_modules_do_not_import_adapters_package() -> None:
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _python_files("dataset")
        if _has_import_with_prefix(path, "ctxbench.adapters")
    ]

    assert offenders == []


def test_import_boundary_command_modules_do_not_import_concrete_lattes_adapter() -> None:
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _python_files("commands")
        if _has_import_with_prefix(path, "ctxbench.adapters.lattes")
    ]

    assert offenders == []


def test_import_boundary_dataset_provider_does_not_import_lattes_adapter() -> None:
    provider_path = SRC_ROOT / "dataset" / "provider.py"
    imports = _imported_modules(provider_path)

    assert not any(
        module == "ctxbench.adapters.lattes" or module.startswith("ctxbench.adapters.lattes.")
        for module in imports
    )


def _imports_any(package_or_file: str, prefixes: tuple[str, ...]) -> list[str]:
    target = SRC_ROOT / package_or_file
    files = [target] if target.is_file() else sorted(target.rglob("*.py"))
    return [
        f"{path.relative_to(SRC_ROOT)} imports {prefix}"
        for path in files
        for prefix in prefixes
        if _has_import_with_prefix(path, prefix)
    ]


def test_import_boundary_api_does_not_import_commands_or_cli() -> None:
    assert _imports_any("api", ("ctxbench.commands", "ctxbench.cli")) == []


def test_import_boundary_workflows_do_not_import_commands_or_api() -> None:
    prefixes = ("ctxbench.commands", "ctxbench.cli", "ctxbench.api")
    assert _imports_any("adaptive", prefixes) + _imports_any("benchmark", prefixes) == []


def test_import_boundary_adaptive_does_not_import_benchmark() -> None:
    assert _imports_any("adaptive", ("ctxbench.benchmark",)) == []


def test_import_boundary_adaptive_state_does_not_import_policy() -> None:
    assert _imports_any("adaptive/state.py", ("ctxbench.adaptive.policy",)) == []


def test_import_boundary_phases_do_not_import_commands_or_api() -> None:
    assert _imports_any("phases", ("ctxbench.commands", "ctxbench.cli", "ctxbench.api")) == []


def test_import_boundary_core_workflow_does_not_import_workflows_or_api() -> None:
    prefixes = ("ctxbench.adaptive", "ctxbench.benchmark", "ctxbench.api", "ctxbench.commands",
                "ctxbench.runtime", "ctxbench.execution", "ctxbench.ai")
    assert _imports_any("core/workflow.py", prefixes) == []


def test_workflow_kind_is_resolved_only_by_the_registry() -> None:
    """Commands and the public API must not branch on, or name, a workflow kind."""
    offenders = []
    files = _python_files("commands")
    files += _python_files("api")
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in {"workflowKind", "adaptive", "benchmark"}:
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno} {node.value!r}")
    assert offenders == []


ANALYSIS_ALLOWED_PREFIXES = (
    "ctxbench.util", "ctxbench.core", "ctxbench.analysis",
    "ctxbench.adaptive.state", "ctxbench.adaptive.goals",
    "ctxbench.adaptive.artifacts", "ctxbench.metrics.adaptive",
)


def test_import_boundary_analysis_reads_artifacts_only() -> None:
    offenders = []
    for path in _python_files("analysis"):
        for module in _imported_modules(path):
            if module == "ctxbench" or not module.startswith("ctxbench."):
                continue
            if not any(module == prefix or module.startswith(f"{prefix}.") for prefix in ANALYSIS_ALLOWED_PREFIXES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert offenders == []
