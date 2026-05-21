from __future__ import annotations

import html
import re
from pathlib import Path
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


class HtmlLattesReader(LattesReader):
    def read(self, path: str) -> LattesCurriculum:
        raw_html = self._read_text(path)
        return LattesCurriculum(
            meta=self._read_meta(raw_html),
            profile=self._read_profile(raw_html),
            education=self._read_education(self._section(raw_html, "FormacaoAcademicaTitulacao")),
            projects=self._read_projects(raw_html),
            research=self._read_research(self._section(raw_html, "LinhaPesquisa")),
            publications=self._read_publications(raw_html),
        )

    def _read_text(self, path: str) -> str:
        raw = Path(path).read_bytes()
        for encoding in ("utf-8", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _read_meta(self, raw_html: str) -> LattesMeta:
        return LattesMeta(
            lattes_id=self._search(r"ID Lattes:\s*<span[^>]*>([^<]+)</span>", raw_html),
            source_url=self._search(r"CV:\s*(http://lattes\.cnpq\.br/\d+)", self._text(raw_html)),
            last_updated=self._search(r"Última atualização do currículo em ([^<]+)</li>", raw_html),
        )

    def _read_profile(self, raw_html: str) -> LattesProfile:
        identification = self._section(raw_html, "Identificacao")
        name = self._search(r'<h2 class="nome">([^<]+)</h2>', raw_html)
        summary = self._search(r'<p class="resumo">(.*?)<span class="texto"', raw_html, flags=re.DOTALL)
        nationality = self._value_after_label(identification, "País de Nacionalidade")
        citation_names = self._value_after_label(identification, "Nome em citações bibliográficas")
        fellowship = self._search(
            r'<h2 class="nome"><span class="texto"[^>]*>([^<]+)</span></h2>',
            raw_html,
        )
        addresses = []
        endereco = self._section(raw_html, "Endereco")
        address_text = self._value_after_label(endereco, "Endereço Profissional")
        if address_text:
            addresses.append({"type": "Profissional", "organization": address_text.split(".", 1)[0], "raw": address_text})
        return LattesProfile(
            name=self._clean(name),
            summary=self._clean(summary),
            fellowship=self._clean(fellowship),
            nationality=self._clean(nationality),
            citation_names=[item.strip() for item in (citation_names or "").split(";") if item.strip()],
            addresses=addresses,
            extra_fields=[],
        )

    def _read_education(self, section_html: str) -> list[EducationEntry]:
        if not section_html:
            return []
        pattern = re.compile(
            r'<div class="layout-cell layout-cell-3 text-align-right"><div class="layout-cell-pad-5 text-align-right"><b>([^<]+)</b></div></div>'
            r'<div class="layout-cell layout-cell-9"><div class="layout-cell-pad-5">(.*?)</div></div>',
            re.DOTALL,
        )
        entries: list[EducationEntry] = []
        for year_text, body_html in pattern.findall(section_html):
            body = self._clean(body_html)
            if not body:
                continue
            details = [part.strip() for part in body.split("\n") if part.strip()]
            degree_line = details[0] if details else None
            institution = details[1] if len(details) > 1 else None
            entries.append(
                EducationEntry(
                    degree_name=degree_line.split(".", 1)[0].strip() if degree_line else None,
                    title=self._search(r"Título:\s*([^,]+)", body),
                    institution=institution,
                    country=self._extract_country(institution),
                    start_year=self._extract_first_year(year_text),
                    end_year=self._extract_last_year(year_text),
                    details=details[2:] if len(details) > 2 else [],
                    advisors=self._search_list(r"Orientador:\s*([^\.]+)", body),
                    funding=self._search_list(r"Bolsista do\(a\):\s*([^\.]+)", body),
                )
            )
        return entries

    def _read_research(self, section_html: str) -> LattesResearch:
        lines = re.findall(r'<div class="layout-cell-pad-5">([^<]+)</div>', section_html)
        normalized = []
        for item in lines:
            cleaned = self._clean(item)
            if cleaned and not cleaned.endswith(".") and cleaned not in {"1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."}:
                normalized.append(cleaned)
        return LattesResearch(lines_of_research=normalized, areas_of_expertise=[])

    def _read_projects(self, raw_html: str) -> list[ProjectEntry]:
        projects: list[ProjectEntry] = []
        for anchor_name, kind in [
            ("ProjetosPesquisa", "research"),
            ("ProjetoDesenvolvimentoTecnologico", "development"),
            ("ProjetoDesenvolvimentoTecnologicoPI", "development"),
            ("OutrosProjetos", "other"),
            ("OutrosProjetosPI", "other"),
        ]:
            section = self._section(raw_html, anchor_name)
            if not section:
                continue
            pattern = re.compile(
                r"<a name='PP_[^']*'></a>"
                r'<div class="layout-cell layout-cell-3 text-align-right"><div class="layout-cell-pad-5 text-align-right"><b>([^<]+)</b></div></div>'
                r'<div class="layout-cell layout-cell-9"><div class="layout-cell-pad-5">(.*?)<br class="clear" /></div></div>'
                r'.*?<div class="layout-cell layout-cell-9"><div class="layout-cell-pad-5">(.*?)</div></div>',
                re.DOTALL,
            )
            for years, title_html, body_html in pattern.findall(section):
                title = self._clean(title_html)
                body = self._clean(body_html)
                if not title and not body:
                    continue
                details = [part.strip() for part in body.split("\n") if part.strip()]
                description = None
                for line in details:
                    if line.startswith("Descrição:"):
                        description = line.split("Descrição:", 1)[1].strip()
                        break
                projects.append(
                    ProjectEntry(
                        kind=kind,
                        name=title,
                        description=description,
                        start_year=self._extract_first_year(years),
                        end_year=self._extract_last_year(years),
                        details=details,
                    )
                )
        return projects

    def _read_publications(self, raw_html: str) -> list[PublicationEntry]:
        publications: list[PublicationEntry] = []
        publications.extend(self._read_journal_publications(self._publication_section(raw_html, "ArtigosCompletos", "TrabalhosPublicadosAnaisCongresso")))
        publications.extend(self._read_simple_publications(self._publication_section(raw_html, "TrabalhosPublicadosAnaisCongresso", "ArtigosAceitos"), "conference"))
        publications.extend(self._read_simple_publications(self._publication_section(raw_html, "ArtigosAceitos", "OutrasProducoesBibliograficas"), "accepted"))
        return publications

    def _read_journal_publications(self, section_html: str) -> list[PublicationEntry]:
        entries: list[PublicationEntry] = []
        if not section_html:
            return entries
        pattern = re.compile(r'<div class="artigo-completo">(.*?)</div><br class="clear"><br class="clear">', re.DOTALL)
        for block in pattern.findall(section_html):
            year = self._search(r"data-tipo-ordenacao='ano'>(\d{4})</span>", block)
            doi = self._search(r'icone-doi" href="https?://dx\.doi\.org/([^"]+)"', block)
            text = self._clean(block)
            publication = self._publication_from_text(text, "journal", year, doi)
            if publication is not None:
                entries.append(publication)
        return entries

    def _read_simple_publications(self, section_html: str, kind: str) -> list[PublicationEntry]:
        entries: list[PublicationEntry] = []
        if not section_html:
            return entries
        pattern = re.compile(r'<span class="transform">(.*?)</span>', re.DOTALL)
        for block in pattern.findall(section_html):
            text = self._clean(block)
            publication = self._publication_from_text(text, kind, None, self._search(r'dx\.doi\.org/([^"\s]+)', block))
            if publication is not None:
                entries.append(publication)
        return entries

    def _publication_from_text(
        self,
        text: str,
        kind: str,
        explicit_year: str | None,
        doi: str | None,
    ) -> PublicationEntry | None:
        if not text:
            return None
        authors_part, _, remainder = text.partition(" . ")
        title = None
        venue = None
        if ". " in remainder:
            title, remainder = remainder.split(". ", 1)
            venue = remainder.split(",", 1)[0].strip() if remainder else None
        year = self._extract_last_year(explicit_year or text)
        authors = [item.strip() for item in authors_part.split(";") if item.strip()]
        details = [text] if text else []
        if not any([title, year, venue, authors, doi]):
            return None
        return PublicationEntry(
            kind=kind,
            title=title.strip() if title else None,
            year=year,
            venue=venue,
            authors=authors,
            doi=doi,
            details=details,
        )

    def _publication_section(self, raw_html: str, start_anchor: str, end_anchor: str) -> str:
        start = raw_html.find(f'name="{start_anchor}"')
        if start == -1:
            return ""
        end = raw_html.find(f'name="{end_anchor}"', start + 1)
        if end == -1:
            end = len(raw_html)
        return raw_html[start:end]

    def _section(self, raw_html: str, anchor_name: str) -> str:
        start = raw_html.find(f'name="{anchor_name}"')
        if start == -1:
            return ""
        next_title = raw_html.find('<div class="title-wrapper">', start + 1)
        end = next_title if next_title != -1 else len(raw_html)
        return raw_html[start:end]

    def _value_after_label(self, section_html: str, label: str) -> str | None:
        pattern = re.compile(
            rf"<b>{re.escape(label)}</b></div></div><div class=\"layout-cell layout-cell-9\"><div class=\"layout-cell-pad-5\">(.*?)</div></div>",
            re.DOTALL,
        )
        match = pattern.search(section_html)
        if not match:
            return None
        return self._clean(match.group(1))

    def _search(self, pattern: str, value: str, flags: int = 0) -> str | None:
        match = re.search(pattern, value, flags)
        if not match:
            return None
        return self._clean(match.group(1))

    def _search_list(self, pattern: str, value: str) -> list[str]:
        return [item.strip() for item in re.findall(pattern, value) if item.strip()]

    def _extract_country(self, value: str | None) -> str | None:
        if not value or "," not in value:
            return None
        return value.rsplit(",", 1)[-1].strip().rstrip(".")

    def _extract_first_year(self, value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"(19|20)\d{2}", value)
        return int(match.group(0)) if match else None

    def _extract_last_year(self, value: str | None) -> int | None:
        if not value:
            return None
        matches = re.findall(r"(?:19|20)\d{2}", value)
        return int(matches[-1]) if matches else None

    def _text(self, raw_html: str) -> str:
        return self._clean(raw_html)

    def _clean(self, value: Any) -> str | None:
        if value is None:
            return None
        text = html.unescape(str(value))
        text = text.replace("\xa0", " ")
        text = re.sub(r"<br[^>]*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n\s+", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = text.strip()
        return text or None
