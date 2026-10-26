from __future__ import annotations


class AdapterUnavailableError(ValueError):
    """Raised when no adapter is available for a dataset reference."""


from ctxbench.core.errors import CapabilityUnavailableError


class UnsupportedRepresentationError(ValueError):
    """Raised when an adapter cannot provide a requested context representation."""
