"""Validation for the provisioning contract at artifact-only lifecycle boundaries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ctxbench.benchmark.models import CONFIGURATION_ID_PATTERN, ProvisioningConfiguration

PROVISIONING_ARTIFACT_VERSION = 1
LEGACY_MESSAGE = (
    "Unsupported provisioning artifact contract. Historical artifacts require the previous "
    "benchmark version; define configurations and run 'llmctxbench plan' in a fresh directory."
)


def validate_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.exists():
        raise ValueError(f"{LEGACY_MESSAGE} Missing {path}.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("provisioningArtifactVersion") if isinstance(manifest, dict) else None
    if type(version) is not int or version != PROVISIONING_ARTIFACT_VERSION:
        raise ValueError(LEGACY_MESSAGE)
    configurations = manifest.get("configurations")
    if not isinstance(configurations, dict) or not configurations:
        raise ValueError("Manifest requires selected configuration definitions.")
    for key, value in configurations.items():
        if not CONFIGURATION_ID_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid configuration ID: {key}")
        ProvisioningConfiguration.model_validate(value)
    return manifest


def validate_artifact_directory(root: Path) -> dict[str, Any]:
    """Stream canonical rows and check every duplicate treatment against the snapshot."""
    manifest = validate_manifest(root)
    definitions = manifest["configurations"]
    trials: dict[str, tuple[str, str, str]] = {}
    for filename in ("trials.jsonl", "responses.jsonl", "evals.jsonl"):
        path = root / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                key = row.get("configurationId")
                if key not in definitions or "format" in row:
                    raise ValueError(f"{LEGACY_MESSAGE} Invalid treatment in {path}.")
                definition = definitions[key]
                metadata = row.get("metadata")
                if not isinstance(metadata, dict):
                    raise ValueError(f"Missing provisioning metadata in {path}.")
                expected = {"configurationId": key, **definition}
                for field, value in expected.items():
                    if row.get(field) != value or metadata.get(field) != value:
                        raise ValueError(f"Inconsistent provisioning field {field} in {path}.")
                treatment = (key, definition["strategy"], definition["representation"])
                trial_id = row.get("trialId")
                if trial_id in trials and trials[trial_id] != treatment:
                    raise ValueError(f"Conflicting provisioning definition for trialId {trial_id}.")
                trials[trial_id] = treatment
    return manifest


def validate_configuration_union(manifests: list[dict[str, Any]]) -> None:
    definitions: dict[str, dict[str, str]] = {}
    for manifest in manifests:
        for key, definition in manifest["configurations"].items():
            if key in definitions and definitions[key] != definition:
                raise ValueError(f"Conflicting definitions for configuration ID '{key}'.")
            definitions[key] = definition
