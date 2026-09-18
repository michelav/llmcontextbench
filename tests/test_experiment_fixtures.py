from __future__ import annotations

import json
from pathlib import Path

from ctxbench.adapters.registry import get_default_registry
from ctxbench.benchmark.models import ExperimentDataset
from ctxbench.dataset.errors import AdapterUnavailableError


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "experiment.json"
ROOT_EXPERIMENTS = tuple(Path(__file__).resolve().parents[1].glob("experiment*.json"))

LATTES_OPERATIONS = {
    "get_profile",
    "get_expertise",
    "get_education",
    "get_projects",
    "get_supervisions",
    "get_experience",
    "get_academic_activities",
    "get_publications",
    "get_technical_output",
    "get_artistic_output",
}


def test_root_experiment_configurations_use_explicit_surfaces() -> None:
    from ctxbench.benchmark.models import Experiment

    for path in ROOT_EXPERIMENTS:
        experiment = Experiment.model_validate(json.loads(path.read_text(encoding="utf-8")))

        assert experiment.surfaces
        for configuration_id, configuration in experiment.configurations.items():
            assert configuration.surface in experiment.surfaces
            surface = experiment.surfaces[configuration.surface]
            if configuration.strategy == "inline":
                assert surface.type == "full_context", configuration_id
            else:
                assert surface.type == "operations", configuration_id
                assert surface.operations


def test_root_lattes_experiments_declare_the_complete_operation_catalog() -> None:
    from ctxbench.benchmark.models import Experiment

    for name in ("experiment.json", "experiment.baseline.json", "experiment.minimal.json"):
        payload = json.loads((Path(__file__).resolve().parents[1] / name).read_text(encoding="utf-8"))
        experiment = Experiment.model_validate(payload)
        operation_surfaces = [surface for surface in experiment.surfaces.values() if surface.type == "operations"]
        assert operation_surfaces
        assert set(operation_surfaces[0].operations) == LATTES_OPERATIONS


def test_root_experiment_uses_explicit_remote_mcp_strategy() -> None:
    payload = json.loads((Path(__file__).resolve().parents[1] / "experiment.json").read_text(encoding="utf-8"))

    assert "mcp-json" not in payload["configurations"]
    assert payload["configurations"]["remote-mcp-json"]["strategy"] == "remote_mcp"


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
        "clean.html",
        "parsed.json",
        "raw.html",
        "blocks.json",
    ]
    for value in forbidden:
        assert value not in serialized


def test_lattes_adapter_experiment_fixture_formats_are_plain_strings() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    formats = [value["representation"] for value in payload["configurations"].values()]

    assert formats
    assert all(isinstance(value, str) and value for value in formats)
