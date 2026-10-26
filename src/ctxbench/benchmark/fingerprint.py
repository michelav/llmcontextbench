"""Content fingerprints for frozen v1 plans; no Git subprocess or environment secrets."""
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
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def tree_digest(root: Path) -> str:
    files = sorted(p for p in root.rglob('*') if p.is_file()
                   and not {'.git', '.venv', '__pycache__'} & set(p.relative_to(root).parts))
    return digest([(p.relative_to(root).as_posix(), file_digest(p)) for p in files])


def implementation_digest() -> str:
    package = Path(__file__).resolve().parents[1]
    files = sorted(p for p in package.rglob('*.py') if '__pycache__' not in p.parts)
    dependencies = {}
    for name in ('pydantic', 'jsonschema', 'openai', 'anthropic', 'google-genai', 'fastmcp'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    return digest({'sources': [(p.relative_to(package).as_posix(), file_digest(p)) for p in files],
                   'dependencies': dependencies})


def verify_snapshot(root: Path, manifest: dict, *, execution: bool = False) -> None:
    fingerprint = manifest.get('executionFingerprint')
    if fingerprint is None:
        return  # Existing study stack; removed with the legacy definition path.
    inputs = manifest.get('fingerprintInputs')
    if not isinstance(inputs, dict) or digest(inputs) != fingerprint:
        raise ValueError('Execution fingerprint is corrupt')
    for filename, expected in inputs['artifacts'].items():
        if filename not in {'resolved.json', 'trials.jsonl', 'adaptive-plan.json', 'knowledge.json'}:
            raise ValueError('Unexpected frozen artifact name')
        path = root / filename
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError(f'Frozen plan changed: {filename}')
    if execution:
        if implementation_digest() != inputs['implementation']:
            raise ValueError('Execution fingerprint mismatch: implementation changed; plan a fresh run')
        dataset = manifest['dataset'].get('materializedPath')
        if dataset and tree_digest(Path(dataset)) != inputs['dataset']:
            raise ValueError('Execution fingerprint mismatch: dataset changed')
