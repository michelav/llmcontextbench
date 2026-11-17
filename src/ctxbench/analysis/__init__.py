"""Artifact-only analysis helpers for experiment runs."""
from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any


def run_root(run: Any) -> Path:
    """Return the directory of a run given as a path or a handle with a ``root`` directory.

    Paths are checked first: ``pathlib`` paths also have a ``root`` attribute (the filesystem
    root), which must not be mistaken for a run handle.
    """
    if isinstance(run, (str, PurePath)):
        return Path(run).expanduser().resolve()
    root = getattr(run, "root", None)
    if root is None:
        raise TypeError(f"Expected a run directory path or a Run, got {type(run).__name__}")
    return Path(root).expanduser().resolve()
