#!/usr/bin/env bash
# Build the SEAMS 2027 data archive (untracked study data) with a SHA256SUMS manifest.
# Code, definitions, figures and tables are in git (tag the paper revision); this archive holds
# what git does not: the frozen v3 baseline, pilots, replay reports, the S-E' study and the
# direct-surface provider check (runs/direct-check).
#
# Usage: tools/seams/make_archive.sh OUTPUT_DIR [--anonymize]
# Produces OUTPUT_DIR/seams2027-data[-anon].tar.gz and the matching .SHA256SUMS.
#
# --anonymize (double-blind review): copies the data and replaces the absolute repository path
# with "<repo>". The copy still regenerates figures and tables, but `study analyze` and `status`
# refuse it, because the frozen digests cover the original files.
set -euo pipefail
out=${1:?usage: make_archive.sh OUTPUT_DIR [--anonymize]}
out=$(realpath -m "$out")
mkdir -p "$out"
name=seams2027-data
if [ "${2:-}" = "--anonymize" ]; then
  name=seams2027-data-anon
  repo=$(git rev-parse --show-toplevel)
  stage=$(mktemp -d)
  trap 'rm -rf "$stage"' EXIT
fi
paths=(
  baselines/repoqa-long64-v3
  studies/seams3-inline-degradation
  studies/pilot-v3-inline-degradation
  studies/pilot-inline-degradation studies/pilot-degradation studies/pilot-cascade studies/pilot-episodes.tsv
  studies/replay-v3calib studies/replay-validation
  runs/direct-check
)
if [ -n "${stage:-}" ]; then
  cp -a --parents "${paths[@]}" "$stage"
  cd "$stage"
  grep -rlIZ -F "$repo" "${paths[@]}" | xargs -0 -r sed -i "s#$repo#<repo>#g"
  if grep -rqI -F "$HOME" "${paths[@]}"; then echo "home path still present" >&2; exit 1; fi
fi
manifest=$out/$name.SHA256SUMS
find "${paths[@]}" -type f -print0 | sort -z | xargs -0 sha256sum > "$manifest"
# Deterministic order and metadata, so the same inputs give the same archive.
tar --sort=name --mtime='2026-10-15 00:00Z' --owner=0 --group=0 --numeric-owner \
  -cf - "${paths[@]}" | gzip -n > "$out/$name.tar.gz"
sha256sum "$out/$name.tar.gz"
echo "files: $(wc -l < "$manifest")"
