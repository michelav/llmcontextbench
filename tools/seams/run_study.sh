#!/usr/bin/env bash
# Collect a prepared SEAMS study: seed-major, arm order shuffled within each seed (seeded),
# wall-clock logged per episode, each finished episode evaluated in the background.
# Resumable: re-running skips completed episodes (--resume). Meant to run detached:
#   nohup tools/seams/run_study.sh studies/seams3-inline-degradation > studies/seams3-inline-degradation/collect.out 2>&1 &
set -u
study_dir=${1:?usage: run_study.sh STUDY_DIR}
log=$study_dir/episodes.tsv
prepared=$study_dir/prepared.json
for seed in $(jq -r '[.payload.episodes[].seed] | unique | .[]' "$prepared"); do
  while IFS=$'\t' read -r id policy scenario repeat; do
    if [ -s "$study_dir/episodes/$id/evals.jsonl" ]; then continue; fi
    start=$(date -u +%FT%TZ)
    llmctxbench study episode --prepared "$prepared" --policy "$policy" --scenario "$scenario" \
      --seed "$seed" --repeat "$repeat" --resume > /dev/null 2>> "$study_dir/run.log"
    status=$?
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$policy" "$scenario" "$seed" "$start" "$(date -u +%FT%TZ)" "$status" >> "$log"
    if [ "$status" -eq 0 ]; then
      (llmctxbench eval "$study_dir/episodes/$id/responses.jsonl" > /dev/null 2>> "$study_dir/eval.log" ||
         echo "EVAL FAIL $id" >> "$study_dir/eval.log") &
    fi
  done < <(jq -r --argjson s "$seed" '.payload.episodes[] | select(.seed == $s)
             | [.id, .policyName, .scenarioName, (.repeat|tostring)] | @tsv' "$prepared" | shuf --random-source=<(yes "$seed"))
done
wait
echo "collection finished $(date -u +%FT%TZ)"
