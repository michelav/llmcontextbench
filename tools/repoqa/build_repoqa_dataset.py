#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import gzip
import json
import re
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATASET_ID = "ctxbench/repoqa"
DEFAULT_TASK_ID = "snf_retrieve_function"
DEFAULT_VALIDATION_TYPE = "repoqa-scorer"

TASK_STATEMENT = (
    "Based on the function description and code context, retrieve and repeat "
    "the exact described function from the code context in a code block wrapped "
    "by triple backticks. Function description: {description}"
)

DATASET_INSTRUCTIONS = """When a tool requires a `workspace_id`, use the `Instance ID`.
Do not invent or modify dataset identifiers.
"""

LANGUAGE_ALIASES = {
    "py": "python",
    "python": "python",
    "java": "java",
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "go": "go",
    "golang": "go",
    "rs": "rust",
    "rust": "rust",
}

LANGUAGE_SHORT_NAMES = {
    "python": "py",
    "java": "java",
    "javascript": "js",
    "typescript": "ts",
    "go": "go",
    "rust": "rs",
}

TREE_SITTER_SYMBOL_NODE_TYPES = {
    "python": {
        "function_definition": "function",
        "class_definition": "class",
    },
    "java": {
        "method_declaration": "method",
        "constructor_declaration": "constructor",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
    },
    "javascript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "generator_function_declaration": "function",
        "lexical_declaration": "declaration",
        "variable_declaration": "declaration",
    },
    "typescript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "type_alias_declaration": "type_alias",
        "lexical_declaration": "declaration",
        "variable_declaration": "declaration",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
    "rust": {
        "function_item": "function",
        "impl_item": "impl",
        "struct_item": "struct",
        "trait_item": "trait",
        "enum_item": "enum",
    },
}


@dataclass(frozen=True)
class BaseNeedle:
    language: str
    normalized_language: str
    sequence: int
    base_id: str
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
    normalized_language: str
    sequence: int
    repo: str
    path: str
    needle_name: str
    description: str
    repoqa_description: str
    native_code_context: str
    model_code_context: str
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
    repo_content: dict[str, str]
    native_task: dict[str, Any]


def main() -> int:
    args = parse_args()
    output_root = Path(args.output).expanduser().resolve()
    context_sizes = normalize_context_sizes(args.context_tokens)
    requested_languages = normalize_requested_languages(args.language)

    recreate_output_dir(output_root, force=args.force)
    dataset = load_repoqa_dataset(args.input)

    (output_root / "raw").mkdir(parents=True, exist_ok=True)
    (output_root / "context").mkdir(parents=True, exist_ok=True)

    raw_file = write_raw_copy(
        dataset=dataset,
        output_root=output_root,
        version=args.version,
        compress=args.compress_raw,
    )
    base_needles = select_base_needles(
        dataset=dataset,
        requested_languages=requested_languages,
        max_base_instances_per_language=args.max_base_instances,
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
        validation_threshold=args.validation_threshold,
        ignore_comments=args.ignore_comments,
    )
    write_dataset_instructions(output_root)
    write_tasks_json(
        output_root=output_root,
        dataset_id=args.dataset_id,
        version=args.version,
        threshold=args.validation_threshold,
        ignore_comments=args.ignore_comments,
    )
    write_task_instances_json(
        output_root=output_root,
        dataset_id=args.dataset_id,
        version=args.version,
        prepared=prepared,
    )
    write_context_artifacts(output_root=output_root, prepared=prepared)
    write_instances_index(output_root=output_root, prepared=prepared)

    print(f"Generated LLMContextBench RepoQA package: {output_root}")
    print(f"Base needles: {len(base_needles)}")
    print(f"Context sizes: {', '.join(str(size) for size in context_sizes)}")
    print(f"Instances: {len(prepared)}")
    print(f"Task: {DEFAULT_TASK_ID}")
    print(f"Validation: {DEFAULT_VALIDATION_TYPE}")
    print("Next:")
    print(f"  llmctxbench dataset inspect {output_root}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert RepoQA data into a LLMContextBench dataset package while using "
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
    parser.add_argument("--output", required=True, help="Output LLMContextBench dataset root, e.g. datasets/repoqa.")
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
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help=(
            "Language to include. Can be repeated, e.g. "
            "--language python --language java --language typescript. Matching is case-insensitive."
        ),
    )
    parser.add_argument(
        "--max-base-instances",
        type=int,
        default=None,
        help=(
            "Limit selected RepoQA base needles per language before context-size expansion. "
            "Example: 2 languages x 2 base needles per language x 3 context sizes = 12 instances."
        ),
    )
    parser.add_argument(
        "--validation-threshold",
        type=float,
        default=0.8,
        help="Threshold used by repoqa-scorer evaluation metadata. Default: 0.8.",
    )
    parser.add_argument(
        "--ignore-comments",
        action="store_true",
        help="Set ignoreComments=true in repoqa-scorer validation metadata.",
    )
    parser.add_argument(
        "--compress-raw",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write the copied raw RepoQA dataset as raw/repoqa-<version>.json.gz. Default: false.",
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


def normalize_language_name(language: str) -> str:
    key = str(language).strip().lower()
    return LANGUAGE_ALIASES.get(key, key)


def short_language_name(language: str) -> str:
    normalized = normalize_language_name(language)
    return LANGUAGE_SHORT_NAMES.get(normalized, slug(normalized)[:8] or "lang")


def normalize_requested_languages(raw_languages: list[str]) -> set[str] | None:
    if not raw_languages:
        return None
    return {normalize_language_name(language) for language in raw_languages if str(language).strip()}


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
                "  uv pip install 'git+https://github.com/evalplus/repoqa.git'\n"
                f"Original import error: {type(exc).__name__}: {exc}"
            ) from exc
        payload = get_repoqa_data()

    if not isinstance(payload, dict):
        raise ValueError("RepoQA dataset must be a JSON object keyed by language.")
    return payload


def write_raw_copy(*, dataset: dict[str, Any], output_root: Path, version: str, compress: bool) -> str:
    raw_name = f"repoqa-{version}.json.gz" if compress else f"repoqa-{version}.json"
    raw_path = output_root / "raw" / raw_name
    if compress:
        with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
            json.dump(dataset, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    else:
        write_json(raw_path, dataset)
    return f"raw/{raw_name}"


def select_base_needles(
    *,
    dataset: dict[str, Any],
    requested_languages: set[str] | None,
    max_base_instances_per_language: int | None,
) -> list[BaseNeedle]:
    selected: list[BaseNeedle] = []
    selected_per_language: dict[str, int] = defaultdict(int)

    for raw_language, repos_raw in dataset.items():
        normalized_language = normalize_language_name(raw_language)
        if requested_languages is not None and normalized_language not in requested_languages:
            continue
        if not isinstance(repos_raw, list):
            print(f"Skipping language {raw_language!r}: expected a list of repositories.")
            continue

        for repo_raw in repos_raw:
            if max_base_instances_per_language is not None and selected_per_language[normalized_language] >= max_base_instances_per_language:
                break
            if not isinstance(repo_raw, dict):
                continue
            repo_name = str(repo_raw.get("repo") or "").strip()
            content = repo_raw.get("content")
            needles = repo_raw.get("needles")
            if not repo_name or not isinstance(content, dict) or not isinstance(needles, list) or not needles:
                continue

            for needle_index, needle_raw in enumerate(needles):
                if max_base_instances_per_language is not None and selected_per_language[normalized_language] >= max_base_instances_per_language:
                    break
                if not isinstance(needle_raw, dict):
                    continue
                needle_name = str(needle_raw.get("name") or "").strip()
                needle_path = str(needle_raw.get("path") or "").strip()
                description = str(needle_raw.get("description") or "").strip()
                if not needle_name or not needle_path or not description:
                    continue
                if needle_path not in content or not isinstance(content[needle_path], str):
                    continue

                sequence = selected_per_language[normalized_language] + 1
                base_id = make_base_id(language=normalized_language, sequence=sequence)
                selected.append(
                    BaseNeedle(
                        language=str(raw_language),
                        normalized_language=normalized_language,
                        sequence=sequence,
                        base_id=base_id,
                        repo_name=repo_name,
                        repo_raw=repo_raw,
                        needle_raw=needle_raw,
                        needle_index=needle_index,
                        needle_count=len(needles),
                    )
                )
                selected_per_language[normalized_language] += 1

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
            "  PYTHONPATH=/path/to/repoqa:$PYTHONPATH python scripts/build_repoqa_dataset.py ...\n"
            f"Original import error: {type(exc).__name__}: {exc}"
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
    content = {
        str(path): value
        for path, value in base.repo_raw["content"].items()
        if isinstance(value, str)
    }
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

    native_code_context = str(native_task["code_context"])
    model_code_context = render_model_code_context(
        language=base.normalized_language,
        repo=base.repo_name,
        primary_path=needle_path,
        native_code_context=native_code_context,
    )
    target_function = extract_target_function_like_repoqa(
        target_file=content[needle_path],
        start_line=as_optional_int(needle.get("start_line")),
        end_line=as_optional_int(needle.get("end_line")),
        start_byte=as_optional_int(needle.get("start_byte")),
        end_byte=as_optional_int(needle.get("end_byte")),
    )

    instance_id = make_instance_id(base_id=base.base_id, context_tokens=context_tokens)

    native_task["ctxbench_instance_id"] = instance_id
    native_task["ctxbench_base_id"] = base.base_id
    native_task["ctxbench_requested_context_tokens"] = context_tokens
    native_task["ctxbench_topological_paths"] = list(topological_paths)

    return PreparedInstance(
        instance_id=instance_id,
        base_id=base.base_id,
        requested_context_tokens=context_tokens,
        language=base.language,
        normalized_language=base.normalized_language,
        sequence=base.sequence,
        repo=base.repo_name,
        path=needle_path,
        needle_name=needle_name,
        description=clean_description,
        repoqa_description=repoqa_description,
        native_code_context=native_code_context,
        model_code_context=model_code_context,
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
        repo_content=content,
        native_task=native_task,
    )


def render_model_code_context(*, language: str, repo: str, primary_path: str, native_code_context: str) -> str:
    """Render LLMContextBench's text context.

    The model-facing text context adds repository/file orientation but no token
    or analysis metadata. native_code_context.txt keeps the exact RepoQA output.
    """
    prefix = comment_prefix_for_language(language)
    context = native_code_context.strip("\n")
    if contains_path_marker(context):
        return f"{prefix} Repository: {repo}\n\n{context}\n"
    return f"{prefix} Repository: {repo}\n{prefix} File: {primary_path}\n\n{context}\n"


def comment_prefix_for_language(language: str) -> str:
    if language in {"python", "ruby", "shell", "bash"}:
        return "#"
    return "//"


def contains_path_marker(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*(#|//|--|/\*|<!--)\s*(Path|File)\s*:", text))


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
    validation_threshold: float,
    ignore_comments: bool,
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
                "idScheme": "<language>_<sequence>_ctx<size>",
            },
            "validation": {
                "type": DEFAULT_VALIDATION_TYPE,
                "threshold": validation_threshold,
                "ignoreComments": ignore_comments,
            },
            "layout": {
                "tasks": "tasks.json",
                "taskInstances": "tasks.instance.json",
                "datasetInstructions": "dataset-instructions.txt",
                "contextRoot": "context/",
            },
        },
    )


def write_dataset_instructions(output_root: Path) -> None:
    (output_root / "dataset-instructions.txt").write_text(DATASET_INSTRUCTIONS, encoding="utf-8")


def write_tasks_json(
    *,
    output_root: Path,
    dataset_id: str,
    version: str,
    threshold: float,
    ignore_comments: bool,
) -> None:
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
                    "validation": {
                        "type": DEFAULT_VALIDATION_TYPE,
                        "threshold": threshold,
                        "ignoreComments": ignore_comments,
                    },
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

        # Primary CTXBench model-facing text context for format="code_context".
        # Includes repository/file orientation but no token/analysis metadata.
        (instance_dir / "code_context.txt").write_text(item.model_code_context, encoding="utf-8")

        # Native RepoQA context and prompt for calibration/reproducibility only.
        # native_code_context.txt intentionally preserves RepoQA's raw generated context.
        (instance_dir / "native_code_context.txt").write_text(item.native_code_context, encoding="utf-8")
        (instance_dir / "repoqa_prompt.txt").write_text(item.repoqa_prompt, encoding="utf-8")

        # Model-facing structured context for format="json"/"parsed".
        # It deliberately excludes needleName, targetFunction, and native task name.
        parsed = strip_json_strings(build_parsed_context(item))
        write_json(instance_dir / "parsed.json", parsed)

        # Evidence/audit wrapper. This can be used by optional judge/audit steps,
        # while RepoQA deterministic scoring should use native_task.json + responses.
        blocks = {
            "function_description": item.description,
            "evidence": [
                {
                    "id": "code_context",
                    "type": "text",
                    "content": item.model_code_context,
                },
                {
                    "id": "parsed_context",
                    "type": "structured_code",
                    "source": "parsed.json",
                },
            ],
            "metadata": {
                "instance_id": item.instance_id,
                "base_id": item.base_id,
                "sequence": item.sequence,
                "language": item.language,
                "normalized_language": item.normalized_language,
                "repo": item.repo,
                "path": item.path,
                "requested_context_tokens": item.requested_context_tokens,
                "actual_code_context_tokens": item.code_context_ntokens,
                "position_ratio": item.position_ratio,
            },
        }
        write_json(instance_dir / "blocks.json", strip_json_strings(blocks))

        # Hidden ground truth/evaluation artifact.
        oracle = {
            "instanceId": item.instance_id,
            "baseId": item.base_id,
            "sequence": item.sequence,
            "language": item.language,
            "normalizedLanguage": item.normalized_language,
            "repo": item.repo,
            "needleName": item.needle_name,
            "path": item.path,
            "startLine": item.start_line,
            "endLine": item.end_line,
            "startByte": item.start_byte,
            "endByte": item.end_byte,
            "targetFunction": item.target_function,
        }
        write_json(instance_dir / "oracle.json", strip_json_strings(oracle))

        # Native RepoQA task used to reconstruct RepoQA model-output JSONL for scoring.
        # Contains ground-truth name; do not expose as model-facing context.
        write_json(instance_dir / "native_task.json", item.native_task)

        metadata = asdict(item)
        metadata.pop("native_code_context", None)
        metadata.pop("model_code_context", None)
        metadata.pop("repoqa_prompt", None)
        metadata.pop("target_function", None)
        metadata.pop("native_task", None)
        metadata.pop("repo_content", None)
        write_json(instance_dir / "metadata.json", strip_json_strings(metadata))


def build_parsed_context(item: PreparedInstance) -> dict[str, Any]:
    files = parse_context_projection(
        language=item.language,
        normalized_language=item.normalized_language,
        default_path=item.path,
        repo_content=item.repo_content,
        model_code_context=item.model_code_context,
    )
    return {
        "context_type": "repoqa_structured_code_context",
        "context_builder": "repoqa-native",
        "repository": item.repo,
        "workspace_id": item.instance_id,
        "files": files,
        "metadata": {
            "instance_id": item.instance_id,
            "base_id": item.base_id,
            "sequence": item.sequence,
            "language": item.language,
            "normalized_language": item.normalized_language,
            "requested_context_tokens": item.requested_context_tokens,
            "actual_code_context_tokens": item.code_context_ntokens,
            "position_ratio": item.position_ratio,
        },
    }


def parse_context_projection(
    *,
    language: str,
    normalized_language: str,
    default_path: str,
    repo_content: dict[str, str],
    model_code_context: str,
) -> list[dict[str, Any]]:
    visible_segments = split_context_by_file_markers(model_code_context, default_path=default_path)
    visible_by_path: dict[str, str] = {}
    for path, code in visible_segments:
        if path in visible_by_path:
            visible_by_path[path] += "\n\n" + code
        else:
            visible_by_path[path] = code

    files: list[dict[str, Any]] = []
    for path, visible_code in visible_by_path.items():
        full_source = repo_content.get(path)
        if full_source is None:
            files.append(partial_context_file(path=path, language=normalized_language, visible_code=visible_code, reason="source_file_not_found"))
            continue

        if normalized_language == "python":
            files.append(parse_python_full_file_filtered(path=path, language=normalized_language, full_source=full_source, visible_code=visible_code))
        else:
            files.append(parse_tree_sitter_full_file_filtered(path=path, language=normalized_language, full_source=full_source, visible_code=visible_code))
    return files


def split_context_by_file_markers(text: str, *, default_path: str) -> list[tuple[str, str]]:
    lines = text.splitlines(keepends=True)
    segments: list[tuple[str, list[str]]] = []
    current_path = default_path
    current_lines: list[str] = []

    marker_re = re.compile(
        r"^\s*(?:#|//|--|/\*+|<!--)\s*(?:Path|File)\s*:\s*(?P<path>.+?)\s*(?:\*/|-->)?\s*$"
    )
    repo_re = re.compile(r"^\s*(?:#|//|--|/\*+|<!--)\s*Repository\s*:")

    for line in lines:
        if repo_re.match(line):
            continue
        marker = marker_re.match(line)
        if marker:
            if current_lines:
                segments.append((current_path, current_lines))
                current_lines = []
            current_path = marker.group("path").strip() or default_path
            continue
        current_lines.append(line)

    if current_lines:
        segments.append((current_path, current_lines))

    if not segments:
        return [(default_path, text)]

    return [(path, "".join(code_lines).strip("\n")) for path, code_lines in segments]


def parse_python_full_file_filtered(*, path: str, language: str, full_source: str, visible_code: str) -> dict[str, Any]:
    try:
        tree = ast.parse(full_source, type_comments=True)
    except SyntaxError as exc:
        return partial_context_file(path=path, language=language, visible_code=visible_code, reason=f"full_source_parse_error: {exc}")

    lines = full_source.splitlines()
    all_symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_symbols.append(python_function_symbol(path=path, node=node, lines=lines, kind="function", parent_id=None, parent_name=None))
        elif isinstance(node, ast.ClassDef):
            all_symbols.append(python_class_symbol(path=path, node=node, lines=lines, parent_id=None, parent_name=None))

    visible_symbols = filter_visible_symbols(all_symbols, visible_code=visible_code)
    return {
        "path": path,
        "language": language,
        "symbols": visible_symbols,
        "unparsed_code": None if visible_symbols else visible_code,
        "parse_status": "ok_filtered",
        "parse_error": None,
    }


def python_class_symbol(*, path: str, node: ast.ClassDef, lines: list[str], parent_id: str | None, parent_name: str | None) -> dict[str, Any]:
    symbol_name = strip_optional_text(node.name)
    symbol_id = make_symbol_id(path=path, name=symbol_name, kind="class", start_line=getattr(node, "lineno", None), parent_name=parent_name)
    children: list[dict[str, Any]] = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            children.append(python_function_symbol(path=path, node=child, lines=lines, kind="method", parent_id=symbol_id, parent_name=symbol_name))
        elif isinstance(child, ast.ClassDef):
            children.append(python_class_symbol(path=path, node=child, lines=lines, parent_id=symbol_id, parent_name=symbol_name))

    return {
        "symbol_id": symbol_id,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "kind": "class",
        "name": symbol_name,
        "qualified_name": qualified_name(symbol_name, parent_name),
        "signature": strip_required_text(extract_python_header(node=node, lines=lines)),
        "documentation": strip_optional_text(ast.get_docstring(node, clean=True)),
        "code": strip_structured_text(source_for_node(node=node, lines=lines)),
        "start_line": getattr(node, "lineno", None),
        "end_line": getattr(node, "end_lineno", None),
        "children": children,
    }


def python_function_symbol(
    *,
    path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    kind: str,
    parent_id: str | None,
    parent_name: str | None,
) -> dict[str, Any]:
    if isinstance(node, ast.AsyncFunctionDef):
        kind = f"async_{kind}"
    symbol_name = strip_optional_text(node.name)
    symbol_id = make_symbol_id(path=path, name=symbol_name, kind=kind, start_line=getattr(node, "lineno", None), parent_name=parent_name)
    return {
        "symbol_id": symbol_id,
        "parent_id": parent_id,
        "parent_name": parent_name,
        "kind": kind,
        "name": symbol_name,
        "qualified_name": qualified_name(symbol_name, parent_name),
        "signature": strip_required_text(extract_python_header(node=node, lines=lines)),
        "documentation": strip_optional_text(ast.get_docstring(node, clean=True)),
        "code": strip_structured_text(source_for_node(node=node, lines=lines)),
        "start_line": getattr(node, "lineno", None),
        "end_line": getattr(node, "end_lineno", None),
        "children": [],
    }


def parse_tree_sitter_full_file_filtered(*, path: str, language: str, full_source: str, visible_code: str) -> dict[str, Any]:
    try:
        from tree_sitter_languages import get_parser
    except Exception as exc:
        return partial_context_file(path=path, language=language, visible_code=visible_code, reason=f"tree_sitter_unavailable: {exc}")

    if language not in TREE_SITTER_SYMBOL_NODE_TYPES:
        return partial_context_file(path=path, language=language, visible_code=visible_code, reason="unsupported_language")

    try:
        parser = get_parser(language)
        source_bytes = full_source.encode("utf-8")
        tree = parser.parse(source_bytes)
        all_symbols = extract_tree_sitter_symbols(language=language, path=path, source=full_source, source_bytes=source_bytes, root=tree.root_node)
        visible_symbols = filter_visible_symbols(all_symbols, visible_code=visible_code)
        return {
            "path": path,
            "language": language,
            "symbols": visible_symbols,
            "unparsed_code": None if visible_symbols else visible_code,
            "parse_status": "partial" if getattr(tree.root_node, "has_error", False) else "ok_filtered",
            "parse_error": None,
        }
    except Exception as exc:
        return partial_context_file(path=path, language=language, visible_code=visible_code, reason=f"tree_sitter_parse_failed: {exc}")


def partial_context_file(*, path: str, language: str, visible_code: str, reason: str) -> dict[str, Any]:
    return {
        "path": path,
        "language": language,
        "symbols": [],
        "unparsed_code": visible_code,
        "parse_status": "partial_context",
        "parse_error": reason,
    }


def extract_tree_sitter_symbols(*, language: str, path: str, source: str, source_bytes: bytes, root: Any) -> list[dict[str, Any]]:
    node_types = TREE_SITTER_SYMBOL_NODE_TYPES.get(language, {})
    symbols: list[dict[str, Any]] = []
    for node in walk_tree_sitter_nodes(root):
        kind = node_types.get(getattr(node, "type", ""))
        if kind is None:
            continue
        code_text = text_for_tree_sitter_node(node=node, source_bytes=source_bytes)
        name = strip_optional_text(name_for_tree_sitter_node(node=node, source_bytes=source_bytes, code_text=code_text))
        start_line = node.start_point[0] + 1
        symbols.append(
            {
                "symbol_id": make_symbol_id(path=path, name=name, kind=kind, start_line=start_line, parent_name=None),
                "parent_id": None,
                "parent_name": None,
                "kind": kind,
                "name": name,
                "qualified_name": name,
                "signature": strip_required_text(signature_for_tree_sitter_code(code_text=code_text, kind=kind)),
                "documentation": strip_optional_text(documentation_before_node(code=source, start_line=start_line)),
                "code": strip_structured_text(code_text),
                "start_line": start_line,
                "end_line": node.end_point[0] + 1,
                "children": [],
            }
        )
    return symbols


def walk_tree_sitter_nodes(root: Any) -> list[Any]:
    nodes: list[Any] = []
    stack = [root]
    while stack:
        node = stack.pop()
        nodes.append(node)
        children = getattr(node, "children", [])
        stack.extend(reversed(children))
    return nodes


def text_for_tree_sitter_node(*, node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def name_for_tree_sitter_node(*, node: Any, source_bytes: bytes, code_text: str) -> str | None:
    name_node = None
    try:
        name_node = node.child_by_field_name("name")
    except Exception:
        name_node = None
    if name_node is not None:
        return text_for_tree_sitter_node(node=name_node, source_bytes=source_bytes)

    patterns = [
        r"\bfunction\s+([A-Za-z_$][\w$]*)",
        r"\bclass\s+([A-Za-z_$][\w$]*)",
        r"\binterface\s+([A-Za-z_$][\w$]*)",
        r"\bstruct\s+([A-Za-z_][\w]*)",
        r"\btrait\s+([A-Za-z_][\w]*)",
        r"\bfn\s+([A-Za-z_][\w]*)",
        r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)",
        r"\b(?:public|private|protected|static|final|synchronized|abstract|native|strictfp|async|export|default|const|let|var)\s+([A-Za-z_$][\w$]*)\s*[=(]",
        r"^\s*([A-Za-z_$][\w$]*)\s*\(",
    ]
    for pattern in patterns:
        match = re.search(pattern, code_text)
        if match:
            return match.group(1)
    return None


def signature_for_tree_sitter_code(*, code_text: str, kind: str) -> str:
    lines = code_text.splitlines()
    signature_lines: list[str] = []
    balance = 0
    for line in lines:
        signature_lines.append(line)
        balance += line.count("(") + line.count("[") + line.count("{")
        balance -= line.count(")") + line.count("]") + line.count("}")
        stripped = line.strip()
        if kind in {"class", "interface", "struct", "trait", "enum", "impl", "type", "type_alias"}:
            if "{" in stripped or stripped.endswith(";"):
                break
        elif balance <= 0 and (stripped.endswith("{") or stripped.endswith(";") or stripped.endswith(":")):
            break
    signature = "\n".join(signature_lines).strip()
    return signature.rstrip("{").rstrip(":").rstrip()


def documentation_before_node(*, code: str, start_line: int) -> str | None:
    lines = code.splitlines()
    index = max(0, start_line - 2)
    docs: list[str] = []
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped:
            if docs:
                break
            index -= 1
            continue
        if stripped.startswith(("#", "//", "///", "//!", "*", "/*", "/**")):
            docs.append(strip_comment_prefix(stripped))
            index -= 1
            continue
        break
    docs.reverse()
    text = "\n".join(line for line in docs if line is not None).strip()
    return text or None


def strip_comment_prefix(line: str) -> str:
    line = re.sub(r"^/\*+", "", line)
    line = re.sub(r"\*/$", "", line)
    line = re.sub(r"^(#|//+|\*+|!+)", "", line)
    return line.strip()


def filter_visible_symbols(symbols: list[dict[str, Any]], *, visible_code: str) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for symbol in symbols:
        visible = is_code_visible(symbol.get("code"), visible_code)
        filtered_children = filter_visible_symbols(symbol.get("children") or [], visible_code=visible_code)
        if visible:
            copied = dict(symbol)
            copied["children"] = filtered_children
            filtered.append(copied)
        elif filtered_children:
            copied = dict(symbol)
            copied["code"] = None
            copied["documentation"] = None
            copied["signature"] = copied.get("signature") if is_code_visible(copied.get("signature"), visible_code) else None
            copied["children"] = filtered_children
            filtered.append(copied)
    return filtered


def is_code_visible(code: object, visible_code: str) -> bool:
    if not isinstance(code, str) or not code.strip():
        return False
    haystack = normalize_for_visibility_match(visible_code)
    needle = normalize_for_visibility_match(code)
    return bool(needle and needle in haystack)


def normalize_for_visibility_match(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_python_header(*, node: ast.AST, lines: list[str]) -> str:
    start = max(0, getattr(node, "lineno", 1) - 1)
    header_lines: list[str] = []
    balance = 0
    for line in lines[start:]:
        header_lines.append(line)
        stripped = line.strip()
        balance += line.count("(") + line.count("[") + line.count("{")
        balance -= line.count(")") + line.count("]") + line.count("}")
        if stripped.endswith(":") and balance <= 0:
            break
    header = "\n".join(header_lines).strip()
    return header[:-1].rstrip() if header.endswith(":") else header


def source_for_node(*, node: ast.AST, lines: list[str]) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return ""
    return "\n".join(lines[start - 1 : end])


def strip_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def strip_required_text(value: object) -> str:
    return str(value).strip()


def strip_structured_text(value: str) -> str:
    # JSON fields are structured values, not executable files. Strip leading and
    # trailing whitespace/newlines from the field value. The exact indentation is
    # preserved in code_context.txt, native_code_context.txt, and repoqa_prompt.txt.
    return value.strip()


def qualified_name(name: str | None, parent_name: str | None) -> str | None:
    if not name:
        return None
    return f"{parent_name}.{name}" if parent_name else name


def make_symbol_id(*, path: str, name: str | None, kind: str, start_line: int | None, parent_name: str | None) -> str:
    qname = qualified_name(name, parent_name) or "anonymous"
    suffix = f":{start_line}" if start_line is not None else ""
    return f"{path}#{kind}:{qname}{suffix}"


def write_instances_index(*, output_root: Path, prepared: list[PreparedInstance]) -> None:
    rows = []
    for item in prepared:
        rows.append(
            {
                "instanceId": item.instance_id,
                "baseId": item.base_id,
                "sequence": item.sequence,
                "language": item.language,
                "normalizedLanguage": item.normalized_language,
                "repo": item.repo,
                "path": item.path,
                "needleName": item.needle_name,
                "requestedContextTokens": item.requested_context_tokens,
                "actualCodeContextTokens": item.code_context_ntokens,
                "positionRatio": item.position_ratio,
                "contextDir": f"context/{item.instance_id}",
            }
        )
    write_json(output_root / "instances.index.json", rows)


def make_base_id(*, language: str, sequence: int) -> str:
    return f"{short_language_name(language)}_{sequence:03d}"


def make_instance_id(*, base_id: str, context_tokens: int) -> str:
    return f"{base_id}_{context_label(context_tokens)}"


def context_label(context_tokens: int) -> str:
    if context_tokens >= 1024 and context_tokens % 1024 == 0:
        return f"ctx{context_tokens // 1024}k"
    return f"ctx{context_tokens}"


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


def strip_json_strings(value: Any) -> Any:
    """Strip leading/trailing whitespace from string values in structured JSON.

    This is intentionally applied to CTXBench-facing structured artifacts such
    as parsed.json, blocks.json, metadata.json, and oracle.json. It is not
    applied to raw RepoQA data or native_task.json, which should preserve
    RepoQA-native fields.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return [strip_json_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: strip_json_strings(item) for key, item in value.items()}
    return value


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
