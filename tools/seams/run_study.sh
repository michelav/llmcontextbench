#!/usr/bin/env bash
# Collect a prepared SEAMS study: seed-major, arm order shuffled within each seed (seeded),
# wall-clock logged per episode, each finished episode evaluated in the background.
#
# Resumable: re-running skips evaluated episodes and resumes a partial one (--resume replays
# its sealed request packets through the controller). A request that was in flight when the
# process died is "uncertain" and is retried only with --retry-uncertain (the call may have
# been charged twice; its tokens become unavailable).
#
# Outage guard (pre-registration, "Interruptions and provider errors"): after each episode,
# any failed request that is not a task failure (step limit) stops the collection with exit 3,
# so a provider outage is not recorded as configuration behaviour.
#
# Run detached and keep the machine awake:
#   nohup systemd-inhibit --what=sleep:idle --why=seams-collection \
#     tools/seams/run_study.sh studies/seams3-inline-degradation > studies/seams3-inline-degradation/collect.out 2>&1 &
set -u
study_dir=${1:?usage: run_study.sh STUDY_DIR [--retry-uncertain]}
retry=()
[ "${2:-}" = "--retry-uncertain" ] && retry=(--retry-uncertain)
log=$study_dir/episodes.tsv
prepared=$study_dir/prepared.json

provider_errors() {
  jq -r 'select(.status != "success" and ((.errorMessage // "") | test("max_steps=") | not)) | .trialId' \
    "$1/responses.jsonl" 2>/dev/null | wc -l
}

for seed in $(jq -r '[.payload.episodes[].seed] | unique | .[]' "$prepared"); do
  while IFS=$'\t' read -r id policy scenario repeat; do
    if [ -s "$study_dir/episodes/$id/evals.jsonl" ]; then continue; fi
    start=$(date -u +%FT%TZ)
    llmctxbench study episode --prepared "$prepared" --policy "$policy" --scenario "$scenario" \
      --seed "$seed" --repeat "$repeat" --resume "${retry[@]}" > /dev/null 2>> "$study_dir/run.log"
    status=$?
    errors=$(provider_errors "$study_dir/episodes/$id")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$policy" "$scenario" "$seed" "$start" "$(date -u +%FT%TZ)" \
      "$status" "$errors" >> "$log"
    if [ "$errors" -gt 0 ]; then
      echo "STOP $(date -u +%FT%TZ): $errors non-task failures in episode $id ($policy, $scenario, seed $seed)"
      wait; exit 3
    fi
    if [ "$status" -ne 0 ]; then
      echo "STOP $(date -u +%FT%TZ): episode $id exited $status; see $study_dir/run.log"
      wait; exit 4
    fi
    (llmctxbench eval "$study_dir/episodes/$id/responses.jsonl" > /dev/null 2>> "$study_dir/eval.log" ||
       echo "EVAL FAIL $id" >> "$study_dir/eval.log") &
  done < <(jq -r --argjson s "$seed" '.payload.episodes[] | select(.seed == $s)
             | [.id, .policyName, .scenarioName, (.repeat|tostring)] | @tsv' "$prepared" | shuf --random-source=<(yes "$seed"))
done
wait
echo "collection finished $(date -u +%FT%TZ)"
