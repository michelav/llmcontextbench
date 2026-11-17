# Implement slice

Use with Codex.

```text
Spec: {{SPEC_DIR}}
Slice: {{SLICE_ID}} — {{SLICE_GOAL}}
Tasks: {{TASK_IDS}}

Do:
{{DO_LIST}}

Don't:
- create or switch branches
- run provider-backed commands
- run the full benchmark
- perform opportunistic refactors
- implement future slices

Run:
{{TEST_COMMANDS}}

Update:
- worklog.md if this is a meaningful Level 2/3 slice
- usage.jsonl only if usage data is available or explicitly unavailable

Report:
- files changed
- commands run
- test results
- remaining risks
```
