# Review spec for lite conversion

Use this prompt to review an existing spec and decide whether it should be simplified into the lightweight spec format.

```text
Review the existing specification:

{{SPEC_DIR}}/spec.md

Goal:
Decide whether this spec should remain as a full spec or be converted into a lightweight spec.

Do not edit files.
Do not implement code.
Do not run provider-backed commands.

Check:
- Is the spec too verbose for its actual risk level?
- Does it contain product/app-style user stories that do not help this research/CLI change?
- Are requirements clear and testable?
- Are acceptance criteria observable?
- Are Given/When/Then scenarios present or easy to derive?
- Are implementation details mixed into the spec?
- Are plan/task decisions incorrectly embedded in the spec?
- Are scope and out-of-scope boundaries clear?
- Are artifact, metric, dataset, provider, and documentation impacts explicit enough?
- Are there repeated or obsolete sections that can be removed?
- Would converting this spec to the lite format lose important information?

Classify the spec as:
- keep-full
- convert-to-lite
- split-before-conversion
- needs-human-decision

Return:
- recommendation;
- sections to preserve;
- sections to remove or compress;
- missing requirements;
- suggested Given/When/Then acceptance scenarios;
- risks of conversion.
```
