from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ctxbench.dataset.contexts import context_path
from ctxbench.util.fs import load_json

YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")

ACADEMIC_ACTIVITIES_EMPTY = {
    "reviewerRoles": [],
    "editorialBoards": [],
    "eventParticipations": [],
    "eventOrganizations": [],
    "defenseBoards": [],
    "otherBoards": [],
}

SUPERVISION_LEVELS = (
    "masters",
    "doctoral",
    "undergraduate",
    "specialization",
    "others",
)

SUPERVISIONS_EMPTY = {
    level: {"completed": [], "ongoing": []}
    for level in SUPERVISION_LEVELS
}


class LattesProvider:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def get_profile(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
    ) -> dict[str, Any]:
        return self._get_section_object(contexts_dir=contexts_dir, lattes_id=lattes_id, section_name="profile")

    def get_expertise(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
    ) -> dict[str, Any]:
        return self._get_section_object(contexts_dir=contexts_dir, lattes_id=lattes_id, section_name="expertise")

    def get_education(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        return self._filter_items_section(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="education",
            start_year=start_year,
            end_year=end_year,
        )

    def get_projects(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        return self._filter_items_section(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="projects",
            start_year=start_year,
            end_year=end_year,
        )

    def get_supervisions(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        section = self._get_section_object(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="supervisions",
            default=SUPERVISIONS_EMPTY,
        )
        payload: dict[str, Any] = {}
        for level in SUPERVISION_LEVELS:
            level_section = section.get(level)
            if not isinstance(level_section, dict):
                payload[level] = {"completed": [], "ongoing": []}
                continue
            payload[level] = {
                "completed": self._filter_sequence(level_section.get("completed"), start_year, end_year),
                "ongoing": self._filter_sequence(level_section.get("ongoing"), start_year, end_year),
            }
        return payload

    def get_experience(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        return self._filter_items_section(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="experience",
            start_year=start_year,
            end_year=end_year,
        )

    def get_academic_activities(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        section = self._get_section_object(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="academicActivities",
            default=ACADEMIC_ACTIVITIES_EMPTY,
        )
        return {
            key: self._filter_sequence(section.get(key), start_year, end_year)
            for key in ACADEMIC_ACTIVITIES_EMPTY
        }

    def get_publications(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        section = self._get_section_object(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="publications",
            default={"metadata": {}, "items": []},
        )
        metadata = section.get("metadata")
        return {
            "metadata": metadata if isinstance(metadata, dict) else {},
            "items": self._filter_sequence(section.get("items"), start_year, end_year),
        }

    def get_technical_output(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        return self._filter_items_section(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="technicalOutput",
            start_year=start_year,
            end_year=end_year,
        )

    def get_artistic_output(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        return self._filter_items_section(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name="artisticOutput",
            start_year=start_year,
            end_year=end_year,
        )

    def get_parsed_curriculum(self, *, contexts_dir: str, lattes_id: str) -> dict[str, Any]:
        path = context_path(contexts_dir, lattes_id, "json")
        cache_key = str(path.resolve())
        if cache_key not in self._cache:
            payload = load_json(path)
            if not isinstance(payload, dict):
                raise ValueError(f"Parsed curriculum must be a JSON object: {path}")
            self._cache[cache_key] = payload
        return self._cache[cache_key]

    def resolve_instance_dir(self, *, contexts_dir: str, lattes_id: str) -> str:
        path = Path(contexts_dir) / lattes_id
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"Missing context directory for lattes_id={lattes_id}: {path}")
        return str(path.resolve())

    def close(self) -> None:
        self._cache.clear()

    def _get_section_object(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        section_name: str,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.get_parsed_curriculum(contexts_dir=contexts_dir, lattes_id=lattes_id)
        section = payload.get(section_name)
        if isinstance(section, dict):
            return dict(section)
        return dict(default or {})

    def _filter_items_section(
        self,
        *,
        contexts_dir: str,
        lattes_id: str,
        section_name: str,
        start_year: int | None,
        end_year: int | None,
    ) -> dict[str, Any]:
        section = self._get_section_object(
            contexts_dir=contexts_dir,
            lattes_id=lattes_id,
            section_name=section_name,
            default={"items": []},
        )
        return {"items": self._filter_sequence(section.get("items"), start_year, end_year)}

    def _filter_sequence(
        self,
        value: Any,
        start_year: int | None,
        end_year: int | None,
    ) -> list[Any]:
        if not isinstance(value, list):
            return []
        if start_year is None and end_year is None:
            return list(value)
        return [item for item in value if self._matches_year_window(item, start_year, end_year)]

    def _matches_year_window(
        self,
        item: Any,
        start_year: int | None,
        end_year: int | None,
    ) -> bool:
        item_start, item_end = self._item_year_range(item)
        if item_start is None and item_end is None:
            return False
        effective_start = item_start if item_start is not None else item_end
        effective_end = item_end if item_end is not None else item_start
        if effective_start is None or effective_end is None:
            return False
        if start_year is not None and effective_end < start_year:
            return False
        if end_year is not None and effective_start > end_year:
            return False
        return True

    def _item_year_range(self, item: Any) -> tuple[int | None, int | None]:
        if isinstance(item, dict):
            year = self._coerce_year(item.get("year"))
            if year is not None:
                return year, year
            interval = item.get("interval")
            if isinstance(interval, dict):
                start = self._coerce_year(interval.get("start"))
                end = self._coerce_year(interval.get("end"))
                if start is not None or end is not None:
                    return start, end
        years = self._extract_years(item)
        if not years:
            return None, None
        return min(years), max(years)

    def _extract_years(self, item: Any) -> list[int]:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = json.dumps(item, ensure_ascii=False)
        else:
            text = str(item)
        years = [int(match.group(0)) for match in YEAR_PATTERN.finditer(text)]
        return sorted(set(years))

    def _coerce_year(self, value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None
