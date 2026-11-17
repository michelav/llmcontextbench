"""Build and plan a small adaptive experiment entirely through the Python API.

Usage: python examples/adaptive/code_built.py [OUTPUT_DIR]

OUTPUT_DIR must not exist yet; by default a fresh temporary directory is used, so the example
can be run repeatedly.
"""
import sys
import tempfile
from pathlib import Path

from ctxbench.api import (
    AdaptiveExperiment, Candidate, Configuration, Model, PolicyRef, Segment, Window,
    Workload, load_dataset, plan,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = REPOSITORY_ROOT / "tests/fixtures/fake_dataset/dataset"


def main(output: Path | None = None) -> None:
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="ctxbench-code-built-")) / "run"
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
    run = plan(experiment, output=output)
    print(f"Planned {len(list(run.requests()))} requests at {run.root}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
