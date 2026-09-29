"""Shared provisioning configuration contracts."""
from __future__ import annotations

from typing import Any

from ctxbench._compat import BaseModel


VALID_STRATEGY_NAMES = {"inline", "local_function", "local_mcp", "remote_mcp"}


class ProvisioningConfiguration(BaseModel):
    strategy: str
    representation: str
    surface: str

    def __init__(self, **data: Any) -> None:
        extra = set(data) - {"strategy", "representation", "surface"}
        # Benchmark subclasses add treatment and artifact fields.
        if type(self) is ProvisioningConfiguration and extra:
            raise ValueError(f"Unexpected configuration fields: {', '.join(sorted(extra))}")
        super().__init__(**data)
        if self.strategy not in VALID_STRATEGY_NAMES:
            raise ValueError(f"unknown strategy: {self.strategy}")
        if not self.representation.strip():
            raise ValueError("Configuration representation must be non-empty.")
        if self.strategy != "inline" and self.representation != "json":
            raise ValueError("Tool strategies support only the json representation.")
