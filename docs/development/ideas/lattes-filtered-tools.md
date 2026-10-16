# Idea: fine-grained and filtered Lattes tools

Status: **parked** (2026-10-16). Recovered from the deleted branch `tool-refactoring`
(commit `4a0c82a`, 2026-04-29, made before the `copa` → `ctxbench` rename). It was
never merged. Revisit with the post-SEAMS Lattes work (thesis) and alongside the RepoQA
interface idea ([repoqa-interface-redesign.md](repoqa-interface-redesign.md)).

## What the commit did

All changes were in the Lattes dataset under the old path `src/copa/datasets/lattes/`. Today
that code lives in `src/ctxbench/adapters/lattes/`.

- **New `get_advisees` tool.**
  - Returns a compact list of advisees and co-advisees.
  - Its description tells the model to call it before checking publications when the question mentions students.
  - `provider.get_advisees` parses supervision entries (`_parse_supervision_entry`, with level and status).
- **Filtered `get_publications`.** Besides `start_year` and `end_year`, the tool gained:
  - `coauthors`: a list of names, matched case- and accent-insensitively in the author text (`_normalize_text`, `_text_contains_name`);
  - `publication_type`: a closed enum: `conference_paper`, `journal_article`, `presentation`, `book_chapter`, `expanded_abstract`, `conference_abstract`, `other_work`, `press_article`, `edited_book`, `book_and_chapters`, `technical_process`, `technical_other`.

  The schema used `additionalProperties: false`, and the description explained when to use each filter.
- **Tests** (`tests/test_lattes_sections.py`):
  - `test_provider_filters_publications_by_coauthor_and_type`;
  - `test_publications_tool_uses_closed_enum_and_updated_guidance`.
- **Experiment files** for the comparison: `experiment.tool-refactor.json`, `experiment.full.json` and `experiment.reduced.json`.

## Why it is worth revisiting

- **It is the Lattes counterpart of the RepoQA finding.** Tool latency there is driven by the number of model round trips, not by tool time. Filters that answer a question in one call (publications with a given coauthor, of a given type, in a year range) should cut calls and tokens compared with fetching everything and filtering in the prompt.
- **It fits the post-SEAMS Lattes route in the SEAMS v2 plan,** which needs real quality and cost trade-offs.

## To recover the code

The branch was deleted from `origin` on 2026-10-16, so the commit is kept as a patch next to
this note: `lattes-filtered-tools.patch`. It does not apply as is:
- paths need `src/copa/datasets/lattes` → `src/ctxbench/adapters/lattes`;
- the current `get_publications` signature has changed since.
