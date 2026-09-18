from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ctxbench._compat import BaseModel, Field, ValidationError


class FullContextSurface(BaseModel):
    type: str = "full_context"

    def __init__(self, **data: Any) -> None:
        extra = set(data) - {"type"}
        if extra:
            raise ValueError(f"Unexpected full_context surface fields: {', '.join(sorted(extra))}")
        data.setdefault("type", "full_context")
        super().__init__(**data)
        if self.type != "full_context":
            raise ValueError(f"Unknown surface type: {self.type}")


class OperationSurface(BaseModel):
    type: str = "operations"
    operations: list[str] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        extra = set(data) - {"type", "operations"}
        if extra:
            raise ValueError(f"Unexpected operations surface fields: {', '.join(sorted(extra))}")
        data.setdefault("type", "operations")
        super().__init__(**data)
        if self.type != "operations":
            raise ValueError(f"Unknown surface type: {self.type}")
        if not self.operations or any(not isinstance(item, str) or not item.strip() for item in self.operations):
            raise ValueError("Operations surfaces require a non-empty list of operation names.")
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("Operations surfaces must not contain duplicate operation names.")


SurfaceSpec = FullContextSurface | OperationSurface


_SURFACE_TYPES = {
    "full_context": FullContextSurface,
    "operations": OperationSurface,
}


def parse_surface(value: Any) -> SurfaceSpec:
    if isinstance(value, (FullContextSurface, OperationSurface)):
        return value
    if not isinstance(value, dict):
        raise ValidationError("Surface declaration requires an object input.")
    surface_type = value.get("type")
    model = _SURFACE_TYPES.get(surface_type)
    if model is None:
        raise ValueError(f"unknown surface type: {surface_type}")
    return model.model_validate(dict(value))


@dataclass(frozen=True, slots=True)
class ResolvedSurface:
    declaration: SurfaceSpec
    operations: tuple[str, ...] = ()

    @property
    def type(self) -> str:
        return self.declaration.type
