"""Documentation gate: documented commands run provider-free, and relative links resolve.

Commands are taken from fenced ``console`` blocks in README.md and docs/guide/. Each document runs
its blocks in order inside its own temporary directory holding a copy of ``examples/``, so
relative paths in the docs work as written from the repository root. A command that cannot run
provider-free belongs in a ``shell`` block preceded by ``<!-- docs-test: skip (<reason>) -->``.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ctxbench.cli import main as cli_main


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs" / "guide").rglob("*.md"))]
LINK_DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]
CURRENT_DOCS = [*sorted((REPO_ROOT / "docs" / "guide").rglob("*.md")),
                *sorted((REPO_ROOT / "docs" / "architecture").rglob("*.md"))]

FENCE = re.compile(r"^```(?P<lang>[\w-]*)[^\n]*\n(?P<body>.*?)^```[ \t]*$", re.M | re.S)
SKIP = re.compile(r"<!--\s*docs-test:\s*skip\s*\((?P<reason>[^)]+)\)\s*-->\s*$")
COMMAND = re.compile(r"(^|\s)(llmctxbench\s|python3?\s+examples/)")
SHELL_LANGS = {"shell", "bash", "sh", "zsh"}
LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)\)|^\[[^\]]+\]:\s*(?P<ref>\S+)", re.M)


def _blocks(path: Path):
    text = path.read_text(encoding="utf-8")
    for match in FENCE.finditer(text):
        before = text[:match.start()].rstrip("\n").rsplit("\n", 1)[-1]
        skip = SKIP.search(before)
        yield match.group("lang"), match.group("body"), skip.group("reason").strip() if skip else None


def _commands(body: str) -> list[str]:
    commands, pending = [], ""
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("$ "):
            line = line[2:]
        if not line and not pending or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        commands.append(pending + line)
        pending = ""
    assert not pending, f"dangling line continuation: {pending!r}"
    return commands


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _assert_provider_free(definition_path: Path) -> None:
    definition = json.loads(definition_path.read_text(encoding="utf-8"))
    providers = {str(model.get("provider")) for model in definition.get("models", {}).values()}
    judges = (definition.get("evaluation") or {}).get("judges") or []
    providers |= {str(judge.get("provider")) for judge in judges}
    assert providers <= {"mock"}, f"{definition_path} uses non-mock providers {sorted(providers)}"
    assert "extends" not in definition, "documented definitions must be self-contained"


def _run(command: str, workdir: Path) -> None:
    argv = shlex.split(command)
    assert not set(argv) & {"|", ">", ">>", "&&", ";"}, f"shell syntax is not supported: {command}"
    if argv[0] == "llmctxbench":
        if argv[1:2] == ["plan"]:
            _assert_provider_free(workdir / argv[2])
        assert argv[1:2] != ["eval"], "eval runs judge providers; mark it with docs-test: skip"
        cwd = Path.cwd()
        os.chdir(workdir)
        try:
            code = cli_main(argv[1:])
        finally:
            os.chdir(cwd)
        assert code in (0, None), f"`{command}` exited with {code}"
        return
    assert argv[0] in {"python", "python3"} and argv[1].startswith("examples/"), command
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    result = subprocess.run([sys.executable, *argv[1:]], cwd=workdir, env=env,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"`{command}` failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.parametrize("path", COMMAND_DOCS, ids=_rel)
def test_command_blocks_are_marked(path: Path) -> None:
    for lang, body, skip in _blocks(path):
        if lang in SHELL_LANGS and COMMAND.search(body):
            assert skip, f"{_rel(path)}: a `{lang}` block runs llmctxbench; use `console` or add a skip marker"


@pytest.mark.workflow
@pytest.mark.parametrize("path", COMMAND_DOCS, ids=_rel)
def test_documented_commands_run_provider_free(path: Path, tmp_path: Path) -> None:
    commands = [command for lang, body, skip in _blocks(path) if lang == "console"
                for command in _commands(body)]
    if not commands:
        pytest.skip("no console blocks")
    shutil.copytree(REPO_ROOT / "examples", tmp_path / "examples",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for command in commands:
        _run(command, tmp_path)


@pytest.mark.parametrize("path", LINK_DOCS, ids=_rel)
def test_relative_links_resolve(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = FENCE.sub("", text)
    broken = []
    for match in LINK.finditer(text):
        target = match.group("target") or match.group("ref")
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith(("#", "/")):
            continue
        target_path = target.split("#", 1)[0]
        if target_path and not (path.parent / target_path).exists():
            broken.append(target)
    assert not broken, f"{_rel(path)}: broken links {broken}"


@pytest.mark.parametrize("path", CURRENT_DOCS, ids=_rel)
def test_current_docs_do_not_reference_work_packages(path: Path) -> None:
    text = LINK.sub(lambda match: match.group(0).split("](")[0], path.read_text(encoding="utf-8"))
    hits = re.findall(r"\bWP-?[0-9][0-9A-Z]*\b|\bWP-[A-Z]\b|work package", text, re.I)
    assert not hits, f"{_rel(path)} refers to work packages: {sorted(set(hits))}"


def test_metrics_reference_lists_every_column() -> None:
    from ctxbench.metrics import adaptive, aggregate, trial_rows, writers

    reference = (REPO_ROOT / "docs/guide/reference/metrics.md").read_text(encoding="utf-8")
    columns = {*trial_rows.TRIAL_FIELDS, *aggregate.AGGREGATE_FIELDS, *aggregate.EFFECTIVENESS_FIELDS,
               *aggregate.EFFICIENCY_FIELDS, *aggregate.ROBUSTNESS_FIELDS,
               *aggregate.EVALUATION_RELIABILITY_FIELDS, *aggregate.OBSERVABILITY_FIELDS,
               *writers.FAILURE_FIELDS, *adaptive.REQUEST_FIELDS, *adaptive.ATTEMPT_FIELDS,
               *adaptive.GOAL_FIELDS}
    missing = sorted(column for column in columns if f"`{column}`" not in reference)
    assert not missing, f"metrics reference misses columns: {missing}"
