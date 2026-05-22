from __future__ import annotations


class AdapterUnavailableError(ValueError):
    """Raised when no adapter is available for a dataset reference."""


class CapabilityUnavailableError(ValueError):
    """Raised when an adapter lacks a capability required by a lifecycle phase."""


class UnsupportedRepresentationError(ValueError):
    """Raised when an adapter cannot provide a requested context representation."""
