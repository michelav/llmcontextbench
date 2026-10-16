# Plan: separate the tool from the SEAMS 2027 article

Status: in progress. SEAMS 2027 deadline: 2026-10-23.

Progress:
- **Slice 0 (2026-10-16):** done. The signed tag `seams2027-paper` is on `4f42ed7`, and the fingerprinted files are unchanged since `seams-v3-freeze`.
- **Slice 0b (2026-10-16):** done.
  - `main` was fast-forwarded to `4f42ed7`.
  - The worktree `../llmcontextbench-direct` was removed after its `runs/direct-check` was copied here and checked against its hashes.
  - All merged branches were deleted, locally and on `origin`.
  - `tool-refactoring` was parked as `docs/development/ideas/lattes-filtered-tools.md` and then deleted.
  - `study status` verifies on `main`.
  - Nothing has been pushed to `main`.

## Goal

This repository should hold llmctxbench, the tool. Material that exists only because of one paper
moves to an article repository, and study data moves to a citable archive. The paper's evidence
must stay reproducible at every step.

Rule for each item: if another researcher running their own study with llmctxbench would need
it, it stays here. Otherwise it belongs to the article.

## Target layout

| Tool repository (this one) | Article repository (new) | Data archive (Zenodo DOI) |
|---|---|---|
| `src/ctxbench`, including the study, replay and adaptive engine | `docs/seams2027/` (ARTIFACT.md, scenarios, figures, tables) | `baselines/repoqa-long64-v3` |
| `tests/`, `schemas/` | `docs/development/seams2027-plan.md`, `seams2027-preregistration.md` | `studies/seams3-inline-degradation`, `studies/pilot-*`, `studies/pilot-episodes.tsv` |
| `docs/studies.md`, `docs/repoqa.md`, `docs/architecture/` | `tools/seams/` | `studies/replay-v3calib`, `studies/replay-validation` |
| `tools/repoqa/` (dataset build, RepoQA scorer) | SEAMS definitions (list below) | anonymized copy for review, on an anonymous host |
| one small example per study feature in `examples/studies/` | `experiment.repoqa-long64-v3.json`, `experiment.repoqa-direct-check.json` | `runs/direct-check` (direct-surface provider check) |
| `specs/`, `.specify/`, skills | paper LaTeX source, advisor status page | |

SEAMS definitions to move:
- `examples/studies/baseline.repoqa-long64-v3.json`;
- `examples/studies/pilot.{cascade,degradation,inline-degradation,v3-inline-degradation}.json`;
- `examples/studies/study.seams-*.json`, `study.seams3-inline-degradation.json`;
- `examples/studies/replay/*.grid.json`.

The v1 long64 material (`study.long64-*`, `studies/definitions/`, `baseline.repoqa-long64.json`)
is SEAMS history. Move it with the rest, or keep it here, labelled historical, if the tool docs
still use it as an example.

## Constraints

1. **The frozen baseline fingerprint needs a git checkout of the tool.**
   - `measurement_sources()` (`src/ctxbench/studies/baseline.py:23`) finds the repository root from its own file and runs `git rev-parse HEAD`.
   - It hashes fingerprinted files by their paths relative to that root.
   - So the article repository must include the tool as a git submodule pinned to a tag; a pip-installed tool cannot verify.
2. **Fingerprinted files keep their paths until after submission.**
   - Re-verification runs at the pinned tag, so later changes to the tool are safe.
   - Before the tag exists, any move breaks `study status` and `analyze`.
3. **Data paths.**
   - Definitions refer to the baseline relatively (`../../baselines/repoqa-long64-v3/frozen.json`).
   - Prepared studies and raw logs contain absolute checkout paths.
   - Level C (`study status`, `analyze`) has only been checked with the data inside a tool checkout. Slice 1 tests it from the article layout.
4. **Nothing is deleted from this repository before the article repository reproduces levels A to C.**
5. **Files never committed anywhere:** `docs/LLMContextBench_evolution_working_brief.pdf`, `shared-context.md`, `runs/` (except that `runs/direct-check` goes into the data archive).
6. **Commits are GPG-signed.** No provider calls are needed for any slice.

## Implementation slices

### Slice 0: Tag the paper revision of the tool

- **Goal:** a fixed reference for the article submodule.
- **Do:** commit pending work and create the annotated tag `seams2027-paper` on `feat/adaptive-runtime`.
  - Check that the measurement code is unchanged since `seams-v3-freeze`: `git diff seams-v3-freeze -- <fingerprinted paths>` must be empty.
- **Files:** none.
- **Validation:** an empty diff; `git show seams2027-paper` shows the tag.
- **Dependencies:** none.
- **Command:** `git tag -s seams2027-paper -m "SEAMS 2027 paper revision"`

### Slice 0b: Merge into main and prune branches

- **Goal:** `main` holds the full history of the paper revision, so slice 4 cleans up on `main`.
- **State (2026-10-16):**
  - `feat/adaptive-runtime` is 55 commits ahead of `main`, with nothing behind, and is not pushed.
  - `exp/direct-surface` is fully contained in it and is checked out in the worktree `../llmcontextbench-direct`.
  - The local `feat/{dataset-boundaries-capabilities,metrics,provisioning-configs,rename-llmctxbench,repoqa-adapter}` branches are merged.
  - The remote branches `agent/add-mit-license`, `chore/architecture-redesign-roadmap`, `feat/{artifact-contracts,command-model,dataset-distribution}` and `refactor/dataset-distribution` are merged.
  - `origin/tool-refactoring` has one unmerged commit, `4a0c82a`.
- **Do:**
  1. Merge `feat/adaptive-runtime` into `main` without squashing or rebasing: `git switch main && git merge --ff-only feat/adaptive-runtime`.
     - Rewriting would drop the commits that the tags `seams-v1/v2/v3-*`, the hashes in `ARTIFACT.md` (`5c09994`, `ea298ac`) and the HEAD recorded by the baseline point to.
  2. Check the worktree's untracked `runs/`. Then run `git worktree remove ../llmcontextbench-direct` and delete `exp/direct-surface`.
  3. Delete the merged branches: the local ones with `git branch -d`, and the remote ones with `git push origin --delete ...`.
  4. Check `4a0c82a` against the current tool surface. If it is superseded, delete `tool-refactoring`; otherwise record it as a post-SEAMS idea first.
  5. **Do not push `main` or the `seams-*` / `seams2027-paper` tags until the paper is submitted (2026-10-23).**
     - The GitHub repository is public.
     - As of 2026-10-16, `origin/main` is `8231af9`, from before the SEAMS work, and no SEAMS tag or branch has been pushed.
     - Merged-branch deletions on `origin` are safe to push now.
     - After submission, push `main` with slice 4 applied, plus the tags. The article repository and its submodule then resolve against the public tool repository.
- **Validation:**
  - `git merge-base --is-ancestor seams2027-paper main`;
  - `git branch -a` lists only `main` and `feat/adaptive-runtime`, or only `main` once that branch is deleted;
  - `study status studies/seams3-inline-degradation` still verifies on `main`, since its HEAD equals the tag.
- **Dependencies:** slice 0.
- **Commit:** none; this is a fast-forward.

### Slice 1: Reproducibility spike (decides the article layout)

- **Goal:** prove level C works with the tool as a submodule and the data outside the tool checkout.
- **Do,** in a scratch directory with no commits:
  1. Clone the tool at `seams2027-paper` into `article/tool`.
  2. Unpack the data archive into `article/` with the same relative layout: `baselines/`, `studies/`.
  3. Copy the definitions to `article/studies/definitions/` or `article/examples/studies/` so that `../../baselines/...` still resolves.
  4. Run `uv sync` in `tool/` and `tool/tools/repoqa`.
  5. From `article/`, run `study status`, `study analyze --allow-source-drift`, `make_figures.py` and `make_tables.py`.
- **Validation:**
  - `analysis.json` is identical to the original except `sourceDrift`;
  - figures and tables are byte-identical.
- **Outcomes:**
  - If it passes, use this layout.
  - If absolute paths in prepared or raw files break it, decide between two options:
    - (a) keep the data under `tool/` inside the article repository, the layout known to work;
    - (b) add a read-only path remap to `study analyze`.

    Option (b) is a tool change and must be in a module the fingerprint does not cover.
- **Dependencies:** slice 0.

### Slice 2: Create the article repository

- **Goal:** a self-contained repository for the paper.
- **Do:**
  - **Create the repository** (`seams2027-adaptive-context`), private for now. Add the tool as a submodule at `seams2027-paper`.
  - **Copy in, keeping history if practical** (`git filter-repo --path ...` on a clone, or a plain copy with a pointer to the tool commit):
    - `docs/seams2027/`;
    - the two `seams2027-*.md` development documents;
    - `tools/seams/`;
    - the SEAMS definitions;
    - `experiment.repoqa-long64-v3.json` and `experiment.repoqa-direct-check.json`.
  - **Adjust paths in the scripts:** `tools/seams/*.py` and `make_archive.sh` assume the tool root as the working directory. Give them one base-path variable, or run them from the article root with `PYTHONPATH=tool/src`.
  - **Rewrite `ARTIFACT.md`** for the new layout: clone with `--recurse-submodules`, fetch the data by DOI, then levels A to D.
  - **Add `paper/`** with the LaTeX source, and the advisor page as `docs/status.html`.
- **Validation:**
  - levels A, B and C from a fresh `git clone --recurse-submodules` plus the archive;
  - `make_figures.py` output byte-identical to the committed PDFs.
- **Dependencies:** slice 1.
- **Commit (article repository):** `chore: import SEAMS 2027 study material from llmctxbench@seams2027-paper`

### Slice 3: Publish the data

- **Goal:** a citable, verifiable data archive.
- **Do:**
  - Build with `make_archive.sh dist` and `--anonymize`.
  - Reserve a Zenodo DOI and upload the full archive with `SHA256SUMS`; keep it unpublished until camera-ready if needed for double-blind review.
  - Upload the anonymized copy to an anonymous host for the reviewers.
  - Put the DOI and checksums in `ARTIFACT.md`.
- **Validation:** download, `sha256sum -c`, then level A from the downloaded copy.
- **Dependencies:** slice 2. It can run alongside slice 4.

### Slice 4: Remove SEAMS material from the tool repository

- **Goal:** the tool repository describes the tool only.
- **Do:**
  - Delete the moved files listed above.
  - Keep a short "Studies using llmctxbench" section in `README.md` that links the article repository and the tag.
  - **Fix references** in `docs/studies.md`, `docs/repoqa.md`, `README.md`, `docs/development/repoqa-adaptation-prototype.md`, `repoqa-lean-surface-plan.md` and `ideas/repoqa-interface-redesign.md`.
  - **Add a pointer** to `docs/development/worklog.md`: SEAMS entries continue in the article repository.
  - **Keep one small example** per study feature: router, cascade, replay grid. Make them point at a small baseline example, not the v3 one.
- **Do not:** touch fingerprinted files or `tools/repoqa/`.
- **Validation:**
  - `pytest` (tests do not read `examples/studies` or `tools/seams`; confirmed by grep);
  - `rg "seams|docs/seams2027|tools/seams"` shows only the pointer;
  - `llmctxbench study prepare` with a remaining example succeeds.
- **Dependencies:** slice 2 validated; slice 0b (the removal is committed on `main`). Tag `seams2027-paper` exists, so history keeps everything.
- **Commit:** `chore: move SEAMS 2027 study material to its article repository`

### Slice 5 (after submission): Tool clean-up and promotion

- **Goal:** turn study-specific scripts into tool features, and tidy older paper material.
- **Do,** as separate small changes:
  - **`run_study.sh` → `llmctxbench study run`:** a resumable loop with seeded arm order and an episode log.
  - **Promote helpers to public API:** `select_parameters.py` logic → `llmctxbench study replay select`; `_cluster_bootstrap` → a public analysis function.
  - **Publish the long64 dataset** as a versioned archive through the existing dataset distribution, then remove it from the source tree.
  - **Tidy SBES-era material:**
    - move `publications/`, `outputs_analysis.ipynb` and `demo-video.md` to an SBES article repository, or to `docs/publications.md` links;
    - reduce the root `experiment.*.json` files to one or two examples under `examples/`.
- **Only then** consider moving fingerprinted files. Any move invalidates re-verification at HEAD; the article stays reproducible through its pinned tag.
- **Dependencies:** paper submitted.

## Schedule

| Date | Slices |
|---|---|
| Oct 16 | 0, 0b, 1 |
| Oct 17 | 2 |
| Oct 18 | 3 (DOI and upload), 4 |
| Oct 19–23 | writing; the article repository is the working place for the paper |
| after Oct 23 | 5 |

## Risks

- **Slice 1 fails because of absolute paths.**
  - Mitigation: option (a), the known-good layout, costs nothing.
  - Option (b) is a small tool change outside the fingerprint, so it needs no new baseline.
- **History is lost when copying.** Mitigation: the tag `seams2027-paper` keeps the full record in the tool repository; the article's first commit names it.
- **Double-blind review.** Both repositories identify the authors. Reviewers get an anonymized mirror of the article repository, with the submodule flattened and anonymized, plus the anonymized data archive.
  - The tool repository is public, and its name identifies the authors.
  - The paper should name the tool neutrally during review.
  - Nothing SEAMS-related is pushed before submission (slice 0b).
  - The article repository stays private until camera-ready.
- **Time.** If slices 2 to 4 slip, submit from the current layout. ARTIFACT.md already reproduces from this repository, and slice 4 can wait until after submission.
