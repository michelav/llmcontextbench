from __future__ import annotations

from pathlib import Path


REPRESENTATION_ARTIFACTS = {
    "html": "clean.html",
    "raw_html": "raw.html",
    "cleaned_html": "clean.html",
    "clean_html": "clean.html",
    "json": "parsed.json",
    "parsed_json": "parsed.json",
    "blocks": "blocks.json",
}


def artifact_name_for_representation(representation: str) -> str:
    return REPRESENTATION_ARTIFACTS.get(representation, representation)


def context_path(context_dir: str | Path, context_id: str, representation: str) -> Path:
    return Path(context_dir) / context_id / artifact_name_for_representation(representation)
