# R3 inputs

Plan: `seams2027-adaptive-context/docs/r3/plan.md` (§5–§6).

| File | What it is |
|---|---|
| `experiment.json` | FI (`inline-code-full`) and RD (`remote-mcp-direct`) on `repoqa-2026-10-21-native.1`, model `gpt-6-luna`. RD has no delay headers (no injected delay); a study's `server-delay` effect adds them |
| `baseline.json` | calibration baseline: instance split, `long64` sizes, seeds 1 and 2 = sessions 1 and 2 (configuration order reversed in session 2), one repeat |
| `calibration.json` | 169 calibration-split instances: per size and class up to 12, languages round-robin, seed 2027; weights restore the evaluation split's class mix per size and make sizes equally frequent |
| `evaluation.json` | all 1,287 evaluation-split instances (the campaign draws from these) |
| `delay-check.s1.json`, `delay-check.s2.json` | delay check (plain experiments, outside the baseline): the 72 calibration instances at 32k–64k on RD with the S-D delay (mean 500 ms, `requests-exp`), one per session, each with its own condition label |

Regenerate the instance lists (from the tool repo root):

    PYTHONPATH=src python -m ctxbench.adapters.repoqa.calibration_sample \
        datasets/repoqa-2026-10-21-native.1/selection.json examples/studies/r3 --per-class 12 --seed 2027

Environment: `REPOQA_MCP_R3_URL` (the R3 server's `/mcp` URL) and `REPOQA_MCP_TOKEN` (sent as
`X-MCP-Token`, never written to outputs). Paths in `experiment.json` are relative to this directory
(the baseline resolves them from the file); the delay-check files use repo-root paths, so run them
from the tool repo root.
