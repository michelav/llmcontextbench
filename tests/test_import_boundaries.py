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


def test_import_boundary_dataset_provider_does_not_import_lattes_packages() -> None:
    provider_path = SRC_ROOT / "dataset" / "provider.py"
    imports = _imported_modules(provider_path)

    assert not any(
        module == "ctxbench.datasets.lattes" or module.startswith("ctxbench.datasets.lattes.")
        for module in imports
    )
    assert not any(
        module == "ctxbench.adapters.lattes" or module.startswith("ctxbench.adapters.lattes.")
        for module in imports
    )
