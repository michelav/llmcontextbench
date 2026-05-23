#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATASET_ID = "ctxbench/repoqa"
DEFAULT_TASK_ID = "snf_retrieve_function"

TASK_STATEMENT = (
    "Based on the function description and code context, retrieve and repeat "
    "the exact described function from the code context in a code block wrapped "
    "by triple backticks. Function description: {description}"
)

DATASET_INSTRUCTIONS = """Retrieve the exact described function from the provided code context.
Return the function in a fenced code block.
Do not use external knowledge.
Do not invent code that is not present in the context.
"""


@dataclass(frozen=True)
class BaseNeedle:
    language: str
    repo_name: str
    repo_raw: dict[str, Any]
    needle_raw: dict[str, Any]
    needle_index: int
    needle_count: int


@dataclass(frozen=True)
class PreparedInstance:
    instance_id: str
    base_id: str
    requested_context_tokens: int
    language: str
    repo: str
    path: str
    needle_name: str
    description: str
    repoqa_description: str
    code_context: str
    repoqa_prompt: str
    target_function: str
    position_ratio: float
    needle_token_start: int | None
    needle_token_end: int | None
    code_context_ntokens: int | None
    start_line: int | None
    end_line: int | None
    start_byte: int | None
    end_byte: int | None
    native_task: dict[str, Any]


def main() -> int:
    args = parse_args()
    output_root = Path(args.output).expanduser().resolve()
    context_sizes = normalize_context_sizes(args.context_tokens)

    recreate_output_dir(output_root, force=args.force)
    dataset = load_repoqa_dataset(args.input)

    (output_root / "raw").mkdir(parents=True, exist_ok=True)
    (output_root / "context").mkdir(parents=True, exist_ok=True)

    raw_file = write_raw_copy(dataset=dataset, output_root=output_root, version=args.version)
    base_needles = select_base_needles(
        dataset=dataset,
        languages=set(args.language) if args.language else None,
        max_base_instances=args.max_base_instances,
    )
    if not base_needles:
        raise SystemExit("No RepoQA base needles were selected. Check input data and filters.")

    prepared = prepare_instances_native(
        base_needles=base_needles,
        context_sizes=context_sizes,
        clean_comments=args.clean_comments,
    )
    if not prepared:
        raise SystemExit("No RepoQA instances were generated.")

    write_manifest(
        output_root=output_root,
        dataset_id=args.dataset_id,
        version=args.version,
        raw_file=raw_file,
        context_sizes=context_sizes,
        clean_comments=args.clean_comments,
        base_count=len(base_needles),
        instance_count=len(prepared),
    )
    write_dataset_instructions(output_root)
    write_tasks_json(output_root=output_root, dataset_id=args.dataset_id, version=args.version)
    write_task_instances_json(
        output_root=output_root,
        dataset_id=args.dataset_id,
        version=args.version,
        prepared=prepared,
    )
    write_context_artifacts(output_root=output_root, prepared=prepared)
    write_instances_index(output_root=output_root, prepared=prepared)

    print(f"Generated CTXBench RepoQA package: {output_root}")
    print(f"Base needles: {len(base_needles)}")
    print(f"Context sizes: {', '.join(str(size) for size in context_sizes)}")
    print(f"Instances: {len(prepared)}")
    print(f"Task: {DEFAULT_TASK_ID}")
    print("Next:")
    print(f"  ctxbench dataset inspect {output_root}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert RepoQA data into a CTXBench dataset package while using "
            "RepoQA's native code-context generation."
        )
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "Path to RepoQA .json or .json.gz file. If omitted, calls "
            "repoqa.data.get_repoqa_data(), which may download/cache the default RepoQA release."
        ),
    )
    parser.add_argument("--output", required=True, help="Output CTXBench dataset root, e.g. datasets/repoqa.")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--version", default="2024-06-23-experimental.1")
    parser.add_argument(
        "--context-tokens",
        type=int,
        action="append",
        default=None,
        help=(
            "Requested RepoQA code_context_size. Can be repeated, e.g. "
            "--context-tokens 1024 --context-tokens 8192 --context-tokens 16384. "
            "Defaults to 16384."
        ),
    )
    parser.add_argument(
        "--clean-comments",
        choices=["none", "positional_padding", "no_padding"],
        default="none",
        help="Comment-cleaning mode passed to RepoQA's native context builder.",
    )
    parser.add_argument("--language", action="append", default=[], help="Language to include. Can be repeated.")
    parser.add_argument(
        "--max-base-instances",
        type=int,
        default=None,
        help=(
            "Limit the number of selected RepoQA base needles before context-size expansion. "
            "Example: 2 base needles x 3 context sizes = 6 CTXBench instances."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Replace output directory if it exists.")
    return parser.parse_args()


def normalize_context_sizes(raw_sizes: list[int] | None) -> list[int]:
    sizes = raw_sizes or [16_384]
    normalized: list[int] = []
    seen: set[int] = set()
    for value in sizes:
        if value <= 0:
            raise SystemExit("--context-tokens values must be positive integers.")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def recreate_output_dir(output_root: Path, *, force: bool) -> None:
    if output_root.exists() and any(output_root.iterdir()) and not force:
        raise SystemExit(
            f"Output directory already exists and is not empty: {output_root}\n"
            "Use --force to replace it."
        )
    if output_root.exists() and force:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def load_repoqa_dataset(input_path: str | None) -> dict[str, Any]:
    if input_path:
        path = Path(input_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
    else:
        try:
            from repoqa.data import get_repoqa_data
        except Exception as exc:  # pragma: no cover - optional dependency
            raise SystemExit(
                "RepoQA is not importable. Either pass --input or install RepoQA, e.g.\n"
                "  uv pip install 'git+https://github.com/evalplus/repoqa.git'"
            ) from exc
        payload = get_repoqa_data()

    if not isinstance(payload, dict):
        raise ValueError("RepoQA dataset must be a JSON object keyed by language.")
    return payload


def write_raw_copy(*, dataset: dict[str, Any], output_root: Path, version: str) -> str:
    raw_name = f"repoqa-{version}.json"
    raw_path = output_root / "raw" / raw_name
    write_json(raw_path, dataset)
    return f"raw/{raw_name}"


def select_base_needles(
    *,
    dataset: dict[str, Any],
    languages: set[str] | None,
    max_base_instances: int | None,
) -> list[BaseNeedle]:
    selected: list[BaseNeedle] = []

    for language, repos_raw in dataset.items():
        if languages is not None and language not in languages:
            continue
        if not isinstance(repos_raw, list):
            print(f"Skipping language {language!r}: expected a list of repositories.")
            continue

        for repo_raw in repos_raw:
            if not isinstance(repo_raw, dict):
                continue
            repo_name = str(repo_raw.get("repo") or "").strip()
            content = repo_raw.get("content")
            needles = repo_raw.get("needles")
            if not repo_name or not isinstance(content, dict) or not isinstance(needles, list) or not needles:
                continue

            for needle_index, needle_raw in enumerate(needles):
                if not isinstance(needle_raw, dict):
                    continue
                needle_name = str(needle_raw.get("name") or "").strip()
                needle_path = str(needle_raw.get("path") or "").strip()
                description = str(needle_raw.get("description") or "").strip()
                if not needle_name or not needle_path or not description:
                    continue
                if needle_path not in content or not isinstance(content[needle_path], str):
                    continue

                selected.append(
                    BaseNeedle(
                        language=language,
                        repo_name=repo_name,
                        repo_raw=repo_raw,
                        needle_raw=needle_raw,
                        needle_index=needle_index,
                        needle_count=len(needles),
                    )
                )
                if max_base_instances is not None and len(selected) >= max_base_instances:
                    return selected

    return selected


def prepare_instances_native(
    *,
    base_needles: list[BaseNeedle],
    context_sizes: list[int],
    clean_comments: str,
) -> list[PreparedInstance]:
    try:
        from repoqa.search_needle_function import (
            INSTRUCTION,
            TEMPLATE,
            CleanComment,
        )
        from repoqa.utility import topological_sort
    except Exception as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "RepoQA is required for native dataset generation. Install it or add it to PYTHONPATH, e.g.\n"
            "  uv pip install 'git+https://github.com/evalplus/repoqa.git'\n"
            "or\n"
            "  PYTHONPATH=/path/to/repoqa:$PYTHONPATH python scripts/build_repoqa_dataset.py ..."
        ) from exc

    clean_mode = {
        "none": CleanComment.NoClean,
        "positional_padding": CleanComment.PositionalPadding,
        "no_padding": CleanComment.NoPadding,
    }[clean_comments]

    prepared: list[PreparedInstance] = []

    for base in base_needles:
        repo_raw = base.repo_raw
        content = repo_raw["content"]
        dependency = repo_raw.get("dependency")
        ordered_paths = topological_sort(dependency)
        file_content_list = [
            (path, content[path])
            for path in ordered_paths
            if path in content and isinstance(content[path], str)
        ]
        if not file_content_list:
            continue

        for context_tokens in context_sizes:
            prepared.append(
                prepare_single_native_instance(
                    base=base,
                    file_content_list=file_content_list,
                    instruction=INSTRUCTION,
                    template=TEMPLATE,
                    clean_mode=clean_mode,
                    context_tokens=context_tokens,
                    topological_paths=ordered_paths,
                )
            )

    return prepared


def prepare_single_native_instance(
    *,
    base: BaseNeedle,
    file_content_list: list[tuple[str, str]],
    instruction: str,
    template: str,
    clean_mode: Any,
    context_tokens: int,
    topological_paths: list[str],
) -> PreparedInstance:
    try:
        from repoqa.search_needle_function import make_code_context
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("RepoQA make_code_context is unavailable.") from exc

    needle = base.needle_raw
    content = base.repo_raw["content"]
    needle_name = str(needle["name"]).strip()
    needle_path = str(needle["path"]).strip()
    clean_description = str(needle["description"]).strip()
    position_ratio = (base.needle_index + 0.5) / max(1, base.needle_count)
    repoqa_description = f"\nFunction Description:{clean_description}\n"

    native_task: dict[str, Any] = {
        "repo": base.repo_name,
        "name": needle_name,
        "language": base.language,
        "path": needle_path,
        "position_ratio": position_ratio,
        "description": repoqa_description,
        "instruction": instruction,
        "template": template,
    }
    code_context_info = make_code_context(
        needle,
        file_content_list,
        position_ratio=position_ratio,
        code_context_size=context_tokens,
        language=base.language,
        clean_comments=clean_mode,
    )
    native_task.update(code_context_info)

    target_function = extract_target_function_like_repoqa(
        target_file=content[needle_path],
        start_line=as_optional_int(needle.get("start_line")),
        end_line=as_optional_int(needle.get("end_line")),
        start_byte=as_optional_int(needle.get("start_byte")),
        end_byte=as_optional_int(needle.get("end_byte")),
    )

    base_id = make_base_id(language=base.language, repo=base.repo_name, needle_name=needle_name)
    instance_id = make_instance_id(base_id=base_id, context_tokens=context_tokens)

    native_task["ctxbench_instance_id"] = instance_id
    native_task["ctxbench_base_id"] = base_id
    native_task["ctxbench_requested_context_tokens"] = context_tokens
    native_task["ctxbench_topological_paths"] = list(topological_paths)

    return PreparedInstance(
        instance_id=instance_id,
        base_id=base_id,
        requested_context_tokens=context_tokens,
        language=base.language,
        repo=base.repo_name,
        path=needle_path,
        needle_name=needle_name,
        description=clean_description,
        repoqa_description=repoqa_description,
        code_context=str(native_task["code_context"]),
        repoqa_prompt=render_repoqa_prompt(native_task),
        target_function=target_function,
        position_ratio=position_ratio,
        needle_token_start=as_optional_int(native_task.get("needle_token_start")),
        needle_token_end=as_optional_int(native_task.get("needle_token_end")),
        code_context_ntokens=as_optional_int(native_task.get("code_context_ntokens")),
        start_line=as_optional_int(needle.get("start_line")),
        end_line=as_optional_int(needle.get("end_line")),
        start_byte=as_optional_int(needle.get("start_byte")),
        end_byte=as_optional_int(needle.get("end_byte")),
        native_task=native_task,
    )


def render_repoqa_prompt(native_task: dict[str, Any]) -> str:
    prompt = ""
    for key in str(native_task["template"]).split("\n"):
        prompt += str(native_task[key])
    return prompt


def extract_target_function_like_repoqa(
    *,
    target_file: str,
    start_line: int | None,
    end_line: int | None,
    start_byte: int | None,
    end_byte: int | None,
) -> str:
    # RepoQA's scorer reconstructs target functions with:
    # "\n".join(contents[path].split("\n")[start_line:end_line])
    if start_line is not None and end_line is not None:
        lines = target_file.split("\n")
        start = max(0, min(start_line, len(lines)))
        end = max(start, min(end_line, len(lines)))
        return "\n".join(lines[start:end])

    if start_byte is not None and end_byte is not None and 0 <= start_byte <= end_byte <= len(target_file):
        return target_file[start_byte:end_byte]

    return ""


def write_manifest(
    *,
    output_root: Path,
    dataset_id: str,
    version: str,
    raw_file: str,
    context_sizes: list[int],
    clean_comments: str,
    base_count: int,
    instance_count: int,
) -> None:
    write_json(
        output_root / "ctxbench.dataset.json",
        {
            "id": dataset_id,
            "datasetVersion": version,
            "manifestSchemaVersion": 1,
            "name": "CTXBench RepoQA Experimental",
            "description": "RepoQA Search Needle Function dataset packaged for CTXBench.",
            "domain": "software-repository",
            "origin": {"source": "evalplus/repoqa", "rawFile": raw_file},
            "generation": {
                "contextBuilder": "repoqa-native",
                "contextTokenBudgets": context_sizes,
                "cleanComments": clean_comments,
                "baseNeedles": base_count,
                "instances": instance_count,
            },
            "layout": {
                "tasks": "tasks.json",
                "taskInstances": "tasks.instance.json",
                "contextRoot": "context/",
            },
        },
    )


def write_dataset_instructions(output_root: Path) -> None:
    (output_root / "dataset-instructions.md").write_text(DATASET_INSTRUCTIONS, encoding="utf-8")


def write_tasks_json(*, output_root: Path, dataset_id: str, version: str) -> None:
    write_json(
        output_root / "tasks.json",
        {
            "datasetId": dataset_id,
            "domain": "software-repository",
            "language": "multi",
            "version": version,
            "description": "RepoQA Search Needle Function task adapted to CTXBench.",
            "tasks": [
                {
                    "id": DEFAULT_TASK_ID,
                    "statement": TASK_STATEMENT,
                    "tags": [
                        "code",
                        "repository",
                        "retrieval",
                        "long-context",
                        "needle",
                        "function-search",
                    ],
                    "validation": {"type": "judge"},
                    "contextBlocks": ["function_description", "code_context"],
                }
            ],
        },
    )


def write_task_instances_json(
    *,
    output_root: Path,
    dataset_id: str,
    version: str,
    prepared: list[PreparedInstance],
) -> None:
    write_json(
        output_root / "tasks.instance.json",
        {
            "datasetId": dataset_id,
            "domain": "software-repository",
            "version": version,
            "instances": [
                {
                    "instanceId": item.instance_id,
                    "contextBlocks": f"context/{item.instance_id}/blocks.json",
                    "tasks": [
                        {
                            "id": DEFAULT_TASK_ID,
                            "parameters": {"description": item.description},
                        }
                    ],
                }
                for item in prepared
            ],
        },
    )


def write_context_artifacts(*, output_root: Path, prepared: list[PreparedInstance]) -> None:
    for item in prepared:
        instance_dir = output_root / "context" / item.instance_id
        instance_dir.mkdir(parents=True, exist_ok=True)

        # Primary CTXBench model-facing context for format="code_context".
        (instance_dir / "code_context.txt").write_text(item.code_context, encoding="utf-8")

        # Native RepoQA prompt for calibration/reproducibility only.
        # Do not expose this as the default CTXBench model-facing context.
        (instance_dir / "repoqa_prompt.txt").write_text(item.repoqa_prompt, encoding="utf-8")

        # Model-facing structured context for format="json"/"parsed".
        # It deliberately excludes needleName, targetFunction, and native task name.
        parsed = {
            "context_type": "repoqa_code_context",
            "context_builder": "repoqa-native",
            "requested_context_tokens": item.requested_context_tokens,
            "actual_code_context_tokens": item.code_context_ntokens,
            "code_context": item.code_context,
        }
        write_json(instance_dir / "parsed.json", parsed)

        # Evidence for optional judge/audit. It contains the task description and code
        # context, but not the hidden target function body.
        blocks = {
            "function_description": item.description,
            "code_context": item.code_context,
            "metadata": {
                "language": item.language,
                "repo": item.repo,
                "path": item.path,
                "base_id": item.base_id,
                "requested_context_tokens": item.requested_context_tokens,
                "actual_code_context_tokens": item.code_context_ntokens,
                "position_ratio": item.position_ratio,
            },
        }
        write_json(instance_dir / "blocks.json", blocks)

        # Hidden ground truth/evaluation artifact.
        oracle = {
            "language": item.language,
            "repo": item.repo,
            "needleName": item.needle_name,
            "path": item.path,
            "startLine": item.start_line,
            "endLine": item.end_line,
            "startByte": item.start_byte,
            "endByte": item.end_byte,
            "targetFunction": item.target_function,
        }
        write_json(instance_dir / "oracle.json", oracle)

        # Native RepoQA task used to reconstruct RepoQA model-output JSONL for scoring.
        # Contains ground-truth name; do not expose as model-facing context.
        write_json(instance_dir / "native_task.json", item.native_task)

        metadata = asdict(item)
        metadata.pop("code_context", None)
        metadata.pop("repoqa_prompt", None)
        metadata.pop("target_function", None)
        metadata.pop("native_task", None)
        write_json(instance_dir / "metadata.json", metadata)


def write_instances_index(*, output_root: Path, prepared: list[PreparedInstance]) -> None:
    rows = []
    for item in prepared:
        rows.append(
            {
                "instanceId": item.instance_id,
                "baseId": item.base_id,
                "language": item.language,
                "repo": item.repo,
                "path": item.path,
                "requestedContextTokens": item.requested_context_tokens,
                "actualCodeContextTokens": item.code_context_ntokens,
                "positionRatio": item.position_ratio,
                "contextDir": f"context/{item.instance_id}",
            }
        )
    write_json(output_root / "instances.index.json", rows)


def make_base_id(*, language: str, repo: str, needle_name: str) -> str:
    return "__".join([slug(language), slug(repo), slug(needle_name)])


def make_instance_id(*, base_id: str, context_tokens: int) -> str:
    context_label = f"ctx{context_tokens // 1024}k" if context_tokens >= 1024 else f"ctx{context_tokens}"
    return f"{base_id}__{context_label}"


def slug(value: str) -> str:
    value = value.strip().replace("/", "_slash_")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def as_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
