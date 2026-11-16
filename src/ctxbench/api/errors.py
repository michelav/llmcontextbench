"""Public API error hierarchy.

Each class also derives from the built-in exception that internal code raises for the same
condition, so callers that catch ``ValueError`` or ``FileNotFoundError`` keep working.
"""


class CtxbenchError(Exception):
    """Base class for errors raised by the public API."""


class DefinitionError(CtxbenchError, ValueError):
    """A workflow definition is invalid."""


class ArtifactError(CtxbenchError, ValueError):
    """Run artifacts are missing, corrupt, unsupported, or fail their fingerprint."""


class RunNotFoundError(ArtifactError, FileNotFoundError):
    """No run artifacts exist at the requested path."""


class CapabilityError(CtxbenchError, ValueError):
    """A dataset or provider cannot support a declared requirement."""


class ExecutionStateError(CtxbenchError, RuntimeError):
    """A lifecycle operation is not valid for this run state or workflow."""
