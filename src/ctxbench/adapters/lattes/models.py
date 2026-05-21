from __future__ import annotations

from ctxbench._compat import BaseModel, Field


class LattesMeta(BaseModel):
    lattes_id: str | None = None
    source_url: str | None = None
    last_updated: str | None = None
    generated_at: str | None = None


class LattesProfile(BaseModel):
    name: str | None = None
    summary: str | None = None
    fellowship: str | None = None
    nationality: str | None = None
    citation_names: list[str] = Field(default_factory=list)
    addresses: list[dict[str, str]] = Field(default_factory=list)
    extra_fields: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree_name: str | None = None
    title: str | None = None
    institution: str | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    details: list[str] = Field(default_factory=list)
    advisors: list[str] = Field(default_factory=list)
    funding: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    kind: str | None = None
    name: str | None = None
    description: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    details: list[str] = Field(default_factory=list)


class LattesResearch(BaseModel):
    lines_of_research: list[str] = Field(default_factory=list)
    areas_of_expertise: list[str] = Field(default_factory=list)


class PublicationEntry(BaseModel):
    kind: str | None = None
    title: str | None = None
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    details: list[str] = Field(default_factory=list)


class LattesCurriculum(BaseModel):
    meta: LattesMeta = Field(default_factory=LattesMeta)
    profile: LattesProfile = Field(default_factory=LattesProfile)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    research: LattesResearch = Field(default_factory=LattesResearch)
    publications: list[PublicationEntry] = Field(default_factory=list)
