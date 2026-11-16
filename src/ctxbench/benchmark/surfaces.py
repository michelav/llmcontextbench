"""Backward-compatible import path for shared surface contracts."""
from ctxbench.core.surfaces import (
    FullContextSurface,
    OperationSurface,
    ResolvedSurface,
    SurfaceSpec,
    parse_surface,
)

__all__ = ["FullContextSurface", "OperationSurface", "ResolvedSurface", "SurfaceSpec", "parse_surface"]
