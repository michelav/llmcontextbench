"""Errors shared by runtime and dataset contracts."""

class CapabilityUnavailableError(ValueError):
    """A required context/tool capability is unavailable."""


class InvalidDefinitionError(ValueError):
    """A definition is well-formed JSON but describes an experiment that cannot be planned."""
