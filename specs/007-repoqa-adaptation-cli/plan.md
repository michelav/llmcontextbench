# Sequential implementation slices

1. Extract orchestration to adapters/repoqa/workflow.py with keyword-only functions;
   retain script parsing temporarily. Check preparation/calibration/freezing/order
   with fixture tests. Risk: semantic drift. Commit: refactor(repoqa): extract adaptation workflow.
2. Register lazy commands in commands/adaptation.py and cli.py; replace script with
   shared entry point. Check parser defaults/help/JSON/errors/interruption.
   Depends on 1. Risk: entry-point mismatch. Commit: feat(cli): expose RepoQA adaptation commands.
3. Add provenance/helper/frozen/resume/uncertain checks and mocked workflow parity.
   Run adaptation, recovery, analysis and CLI tests. Depends on 2. Risk: unsafe
   continuation. Commit: test(repoqa): verify adaptation CLI compatibility.
4. Migrate README and maintained study guides, classify remaining script references,
   check links and documented arguments without providers. Depends on 3. Risk:
   docs drift. Commit: docs(repoqa): migrate study guides to adaptation CLI.

Keep artifact formats and source fingerprint coverage unchanged. Reuse scorer path
resolution from evaluation.py. Command handlers own parsing/output/warnings;
workflow functions own RepoQA protocol rules. One commit per passing slice.
