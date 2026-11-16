from __future__ import annotations

from pathlib import Path

from ctxbench.api.workflows import registry
from ctxbench.core.workflow import StatusGroupingError


def status_command(output_dir: str | None = None, *, by: str | None = None) -> int:
    root = Path(output_dir).resolve() if output_dir else Path(".").resolve()
    try:
        report = registry.for_run(root).status(root, by=by).report
    except StatusGroupingError as exc:
        for line in exc.report:
            print(line)
        raise
    for line in report:
        print(line)
    return 0
