"""Shared explicit provisioning-surface fixtures for contract-v2 tests."""

FULL_SURFACE = {"full": {"type": "full_context"}}


def operation_surface(*operations: str) -> dict[str, dict[str, object]]:
    return {"operations": {"type": "operations", "operations": list(operations)}}


def add_surface(payload: dict, surface: str = "full", surface_spec: dict | None = None) -> dict:
    """Add the persisted surface fields to a mutable test payload."""
    payload["surface"] = surface
    if surface_spec is not None:
        payload["surfaceSpec"] = surface_spec
    return payload


def full_context_configuration(strategy: str = "inline", representation: str = "json") -> dict[str, str]:
    return {"strategy": strategy, "representation": representation, "surface": "full"}
