"""Backward-compatible import path for shared workflow fingerprints."""
from ctxbench.core.fingerprint import (
    digest,
    file_digest,
    implementation_digest,
    tree_digest,
    verify_snapshot as _verify_snapshot,
)


def verify_snapshot(root, manifest, *, execution: bool = False) -> None:
    """Compatibility wrapper preserving patch points on the benchmark import path."""
    _verify_snapshot(
        root, manifest, execution=execution,
        implementation_digest_fn=implementation_digest,
        tree_digest_fn=tree_digest,
    )

__all__ = ["digest", "file_digest", "implementation_digest", "tree_digest", "verify_snapshot"]
