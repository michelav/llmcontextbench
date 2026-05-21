from __future__ import annotations

from typing import Any

from ctxbench.adapters.lattes.models import (
    EducationEntry,
    LattesCurriculum,
    LattesMeta,
    LattesProfile,
    LattesResearch,
    ProjectEntry,
    PublicationEntry,
)
from ctxbench.adapters.lattes.readers.base import LattesReader
from ctxbench.util.fs import load_json


class JsonLattesReader(LattesReader):
    def read(self, path: str) -> LattesCurriculum:
        payload = load_json(path)
        return LattesCurriculum(
            meta=self._read_meta(payload.get("meta")),
            profile=self._read_profile(payload.get("profile")),
            education=self._read_education(payload.get("education")),
            projects=self._read_projects(payload.get("projects")),
            research=self._read_research(payload.get("research")),
            publications=self._read_publications(payload.get("production")),
        )

    def _read_meta(self, raw: Any) -> LattesMeta:
        if not isinstance(raw, dict):
            return LattesMeta()
        return LattesMeta(
            lattes_id=self._as_str(raw.get("lattesId")),
            source_url=self._as_str(raw.get("sourceUrl")),
            last_updated=self._as_str(raw.get("lastUpdated")),
            generated_at=self._as_str(raw.get("generatedAt")),
        )

    def _read_profile(self, raw: Any) -> LattesProfile:
        if not isinstance(raw, dict):
            return LattesProfile()
        addresses: list[dict[str, str]] = []
        for address in raw.get("addresses", []):
            if not isinstance(address, dict):
                continue
            addresses.append(
                {
                    key: value
                    for key, value in {
                        "type": self._as_str(address.get("type")),
                        "organization": self._as_str(address.get("organization")),
                        "unit": self._as_str(address.get("unit")),
                        "city": self._as_str(address.get("city")),
                        "state": self._as_str(address.get("state")),
                        "country": self._as_str(address.get("country")),
                    }.items()
                    if value
                }
            )
        return LattesProfile(
            name=self._as_str(raw.get("name")),
            summary=self._as_str(raw.get("summary")),
            fellowship=self._as_str(raw.get("fellowship")),
            nationality=self._as_str(raw.get("nationality")),
            citation_names=[value for value in (self._as_str(item) for item in raw.get("citationNames", [])) if value],
            addresses=addresses,
            extra_fields=[value for value in (self._as_str(item) for item in raw.get("extraFields", [])) if value],
        )

    def _read_education(self, raw: Any) -> list[EducationEntry]:
        if not isinstance(raw, dict):
            return []
        entries: list[EducationEntry] = []
        for key in ("degrees", "postDoctoral", "complementaryCourses"):
            values = raw.get(key, [])
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                interval = item.get("interval") if isinstance(item.get("interval"), dict) else {}
                entries.append(
                    EducationEntry(
                        degree_name=self._as_str(item.get("degreeName")),
                        title=self._as_str(item.get("title")),
                        institution=self._as_str(item.get("institution")),
                        country=self._as_str(item.get("country")),
                        start_year=self._as_int(interval.get("start")),
                        end_year=self._as_int(interval.get("end")),
                        details=self._string_list(item.get("details")),
                        advisors=self._string_list(item.get("advisors")),
                        funding=self._string_list(item.get("funding")),
                    )
                )
        return entries

    def _read_projects(self, raw: Any) -> list[ProjectEntry]:
        if not isinstance(raw, list):
            return []
        projects: list[ProjectEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            interval = item.get("interval") if isinstance(item.get("interval"), dict) else {}
            projects.append(
                ProjectEntry(
                    kind=self._project_kind(item.get("type")),
                    name=self._as_str(item.get("name")),
                    description=self._as_str(item.get("description")),
                    start_year=self._as_int(interval.get("start")),
                    end_year=self._as_int(interval.get("end")),
                    details=self._string_list(item.get("details")),
                )
            )
        return projects

    def _read_research(self, raw: Any) -> LattesResearch:
        if not isinstance(raw, dict):
            return LattesResearch()
        return LattesResearch(
            lines_of_research=self._string_list(raw.get("linesOfResearch")),
            areas_of_expertise=self._string_list(raw.get("areasOfExpertise")),
        )

    def _read_publications(self, raw: Any) -> list[PublicationEntry]:
        bibliographical = raw.get("bibliographical") if isinstance(raw, dict) else []
        if not isinstance(bibliographical, list):
            return []
        publications: list[PublicationEntry] = []
        for item in bibliographical:
            publication = self._read_publication_entry(item)
            if publication is not None:
                publications.append(publication)
        return publications

    def _read_publication_entry(self, raw: Any) -> PublicationEntry | None:
        if not isinstance(raw, dict):
            return None
        title = self._as_str(raw.get("title")) or self._extract_title_from_text(raw.get("text"))
        year = self._as_int(raw.get("year")) or self._extract_year(raw.get("text"))
        kind = self._publication_kind(raw.get("category"))
        venue = self._as_str(raw.get("venue")) or self._extract_venue(raw.get("text"), title)
        authors = self._string_list(raw.get("authors")) or self._extract_authors(raw.get("text"))
        doi = self._normalize_doi(raw.get("doi")) or self._extract_doi(raw.get("text"))
        details = self._publication_details(raw)
        if not any([title, year, venue, authors, doi, details]):
            return None
        return PublicationEntry(
            kind=kind,
            title=title,
            year=year,
            venue=venue,
            authors=authors,
            doi=doi,
            details=details,
        )

    def _publication_details(self, raw: dict[str, Any]) -> list[str]:
        details: list[str] = []
        for key, value in raw.items():
            if key in {"category", "year", "authors", "title", "venue", "doi"}:
                continue
            if isinstance(value, list):
                details.extend(self._string_list(value))
            else:
                text = self._as_str(value)
                if text:
                    details.append(f"{key}: {text}")
        return details

    def _extract_title_from_text(self, value: Any) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        parts = [part.strip() for part in text.split(".") if part.strip()]
        return parts[1] if len(parts) > 1 else parts[0]

    def _extract_venue(self, value: Any, title: str | None) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        if title and f"{title}." in text:
            suffix = text.split(f"{title}.", 1)[1].strip()
            venue = suffix.split(",", 1)[0].strip()
            return venue or None
        return None

    def _extract_authors(self, value: Any) -> list[str]:
        text = self._as_str(value)
        if not text or "." not in text:
            return []
        prefix = text.split(".", 1)[0]
        authors = [part.strip() for part in prefix.split(";") if part.strip()]
        return authors

    def _extract_doi(self, value: Any) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        marker = "doi.org/"
        if marker not in text.lower():
            return None
        lower = text.lower()
        start = lower.index(marker) + len(marker)
        tail = text[start:]
        return tail.split()[0].rstrip(".,;")

    def _extract_year(self, value: Any) -> int | None:
        text = self._as_str(value)
        if not text:
            return None
        for token in reversed(text.replace(".", " ").split()):
            year = self._as_int(token)
            if year is not None and 1900 <= year <= 2100:
                return year
        return None

    def _project_kind(self, value: Any) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        return text.replace("_", " ")

    def _publication_kind(self, value: Any) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        lowered = text.lower()
        if "periódico" in lowered or "periodic" in lowered or "journal" in lowered:
            return "journal"
        if "anais" in lowered or "congresso" in lowered or "conference" in lowered:
            return "conference"
        if "aceitos" in lowered:
            return "accepted"
        return text

    def _normalize_doi(self, value: Any) -> str | None:
        text = self._as_str(value)
        if not text:
            return None
        if "doi.org/" in text.lower():
            lower = text.lower()
            start = lower.index("doi.org/") + len("doi.org/")
            return text[start:]
        return text

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in (self._as_str(item) for item in value) if item]

    def _as_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _as_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return number
