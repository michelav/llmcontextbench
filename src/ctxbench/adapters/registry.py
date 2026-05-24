from __future__ import annotations

from ctxbench.adapters.lattes.package import LattesDatasetAdapter
from ctxbench.adapters.repoqa.package import RepoQADatasetAdapter
from ctxbench.dataset.errors import AdapterUnavailableError
from ctxbench.dataset.registry import AdapterRegistry, ResolvedDatasetRef


def _lattes_factory(ref: ResolvedDatasetRef) -> LattesDatasetAdapter:
    root = ref.materialized_path or ref.root
    if root is None:
        raise AdapterUnavailableError("Lattes adapter requires a materialized dataset root.")
    return LattesDatasetAdapter(root)

def _repoqa_factory(ref: ResolvedDatasetRef) -> RepoQADatasetAdapter:
    root = ref.materialized_path or ref.root
    if root is None:
        raise AdapterUnavailableError("RepoQA adapter requires a materialized dataset root.")
    return RepoQADatasetAdapter(root)

_registry = AdapterRegistry()
_registry.register("ctxbench/lattes", _lattes_factory)
_registry.register("ctxbench/repoqa", _repoqa_factory)


def get_default_registry() -> AdapterRegistry:
    return _registry
