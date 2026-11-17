"""Content fingerprints shared by workflow implementations."""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def tree_digest(root: Path) -> str:
    files = sorted(p for p in root.rglob("*") if p.is_file()
                   and not {".git", ".venv", "__pycache__"} & set(p.relative_to(root).parts))
    return digest([(p.relative_to(root).as_posix(), file_digest(p)) for p in files])


def implementation_digest() -> str:
    package = Path(__file__).resolve().parents[1]
    files = sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)
    dependencies = implementation_dependencies()
    return digest({"sources": [(p.relative_to(package).as_posix(), file_digest(p)) for p in files],
                   "dependencies": dependencies})


def implementation_dependencies() -> dict[str, str | None]:
    dependencies = {}
    for name in ("pydantic", "jsonschema", "openai", "anthropic", "google-genai", "fastmcp"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    return dependencies


def implementation_provenance() -> dict[str, object]:
    """Return the implementation digest and dependency versions used to compute it."""
    return {"digest": implementation_digest(), "dependencies": implementation_dependencies()}


def verify_snapshot(root: Path, manifest: dict, *, execution: bool = False,
                    implementation_digest_fn=None, tree_digest_fn=None) -> None:
    fingerprint = manifest.get("executionFingerprint")
    if fingerprint is None:
        raise ValueError("Execution fingerprint is required; create a fresh benchmark plan")
    inputs = manifest.get("fingerprintInputs")
    if not isinstance(inputs, dict) or digest(inputs) != fingerprint:
        raise ValueError("Execution fingerprint is corrupt")
    for filename, expected in inputs["artifacts"].items():
        if filename not in {"resolved.json", "trials.jsonl", "adaptive-plan.json", "knowledge.json"}:
            raise ValueError("Unexpected frozen artifact name")
        path = root / filename
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError(f"Frozen plan changed: {filename}")
    if execution:
        active_implementation_digest = implementation_digest_fn or implementation_digest
        active_tree_digest = tree_digest_fn or tree_digest
        if active_implementation_digest() != inputs["implementation"]:
            raise ValueError("Execution fingerprint mismatch: implementation changed; plan a fresh run")
        dataset = manifest["dataset"].get("materializedPath")
        if dataset and active_tree_digest(Path(dataset)) != inputs["dataset"]:
            raise ValueError("Execution fingerprint mismatch: dataset changed")


__all__ = ["digest", "file_digest", "tree_digest", "implementation_digest",
           "implementation_dependencies", "implementation_provenance", "verify_snapshot"]
