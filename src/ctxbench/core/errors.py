"""Errors shared by runtime and dataset contracts."""

class CapabilityUnavailableError(ValueError):
    """A required context/tool capability is unavailable."""
