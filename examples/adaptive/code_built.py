"""Build and plan a small adaptive experiment entirely through the Python API."""
from pathlib import Path

from ctxbench.api import (
    AdaptiveExperiment, Candidate, Configuration, Model, PolicyRef, Segment, Window,
    Workload, load_dataset, plan,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = REPOSITORY_ROOT / "tests/fixtures/fake_dataset/dataset"


def main() -> None:
    dataset = load_dataset(DATASET_ROOT)
    workload = Workload.generate(
        dataset,
        [Segment(4)],
        seed=17,
        sampling="with_replacement",
        label_features=("validation_type",),
    )
    experiment = AdaptiveExperiment(
        id="code-built-adaptive-example",
        dataset={"root": str(DATASET_ROOT)},
        models={"mock": Model("mock", "mock-model")},
        surfaces={"full": {"type": "full_context"}},
        configurations={"inline-json": Configuration("inline", "json", "full")},
        candidates=[Candidate("A", "mock", "inline-json")],
        workload=workload,
        policy=PolicyRef("static", {"candidate": "A"}),
        window=Window(requests=4),
    )
    run = plan(experiment, output=Path("/tmp/ctxbench-code-built-example"))
    print(f"Planned {len(list(run.requests()))} requests at {run.root}")


if __name__ == "__main__":
    main()
