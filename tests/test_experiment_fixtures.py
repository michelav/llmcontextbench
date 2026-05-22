from __future__ import annotations

import json
from pathlib import Path

from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.dataset.errors import AdapterUnavailableError


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "experiment.json"


def test_lattes_adapter_experiment_fixture_uses_registered_dataset_reference() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    dataset = payload["dataset"]
    assert isinstance(dataset.get("id"), str)
    assert dataset["id"] == "ctxbench/lattes"

    try:
        get_default_registry().resolve(ExperimentDataset.model_validate(dataset))
    except AdapterUnavailableError as exc:
        raise AssertionError("Canonical experiment fixture must use a registered dataset id.") from exc


def test_lattes_adapter_experiment_fixture_omits_adapter_implementation_details() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, sort_keys=True)

    forbidden = [
        "LattesDatasetAdapter",
        "LattesDatasetPackage",
        "ctxbench.adapters",
        "ctxbench.datasets",
        "clean.html",
        "parsed.json",
        "raw.html",
        "blocks.json",
    ]
    for value in forbidden:
        assert value not in serialized


def test_lattes_adapter_experiment_fixture_formats_are_plain_strings() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    formats = payload.get("factors", {}).get("format", [])

    assert formats
    assert all(isinstance(value, str) and value for value in formats)
