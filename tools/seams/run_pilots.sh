#!/usr/bin/env bash
# SEAMS v2 pilots P1-P3 (provider-backed). Arm order shuffled within each pilot; wall-clock logged.
set -u
log=studies/pilot-episodes.tsv
for study_dir in studies/pilot-cascade studies/pilot-degradation studies/pilot-inline-degradation; do
  while IFS=$'\t' read -r policy scenario seed repeat; do
    start=$(date -u +%FT%TZ)
    llmctxbench study episode --prepared "$study_dir/prepared.json" \
      --policy "$policy" --scenario "$scenario" --seed "$seed" --repeat "$repeat" --resume > /dev/null
    status=$?
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$study_dir" "$policy" "$scenario" "$seed" "$start" "$(date -u +%FT%TZ)" "$status" >> "$log"
  done < <(jq -r '.payload.episodes[] | [.policyName, .scenarioName, (.seed|tostring), (.repeat|tostring)] | @tsv' \
           "$study_dir/prepared.json" | shuf --random-source=<(yes 903))
done
