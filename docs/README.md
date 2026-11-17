# Documentation

| Folder | Content | Describes |
|---|---|---|
| [`guide/`](guide/) | How to use the tool: getting started, concepts, experiments, datasets, reference. | Current behaviour only. |
| [`architecture/`](architecture/) | Tool architecture: layering, domain model, C4 views, workflows, contracts, ADRs. | Current design; normative. |
| [`development/`](development/) | Contributing: setup, tests, validation, scenarios, spec workflow. | How to work on the code. |
| [`sprints/`](sprints/) | Development history, one folder per major effort. | The past; not normative. |

## Where content goes

- `guide/` and `architecture/` describe the code as it is. They change in the same change set as
  the behaviour they describe and never refer to work packages or planned work.
- `sprints/` is history. Drafts, designs, reviews and acceptance reports live there; after a
  sprint closes only its README status changes. Sprint folders have semantic names without
  dates; dates live in the sprint README and in the [`sprints/README.md`](sprints/README.md)
  index.
- Closing a sprint promotes its results: durable decisions become ADRs in
  `architecture/decisions/`, design content is merged into `architecture/`, user-visible
  behaviour goes into `guide/`, and the sprint README links to all three.
- `specs/` stays as managed by spec-kit; sprint READMEs link to the relevant spec folders.
- Commands in fenced blocks tagged `console` in `README.md` and `guide/` are executed by the docs
  test (`tests/test_docs.py`) and must run provider-free as written. A command that cannot (real
  provider, judge, Lattes or RepoQA data, installation) goes in a `shell` block preceded by
  `<!-- docs-test: skip (<reason>) -->`; the reason is required. `text` blocks are for display
  only (usage synopses, output).
