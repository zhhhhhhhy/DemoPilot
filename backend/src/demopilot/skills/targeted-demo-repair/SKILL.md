---
name: targeted-demo-repair
description: Prevent and repair demo failures by tracing evidence to the smallest responsible state, handler, render, selector, or fixture change while preserving passed behavior.
---

# Targeted demo repair

Use evidence, not a broad rewrite.

## First-pass failure shield

Before submission, inspect the common failure chain for every requirement:

`fixture → initial state → control → handler → state mutation → render → test selector → assertion`

If any link is missing or points to a different business concept, repair it before returning the files. Pay special attention to filter/sort composition, task validation, workflow timelines, reset completeness, story visibility, and selectors that target decorative text.

## Revision mode

- Read the verifier and Reviewer evidence, then identify the smallest responsible module.
- Preserve already passing requirements, security boundaries, stable IDs, and the three-file contract.
- Change fixture, state, handler, render, and test together only when their contract requires it.
- Return complete replacement files as required by the Harness, but avoid unrelated redesign or new features.
- Never hide a failure by weakening the assertion, deleting a requirement, or replacing an interaction with static text.
- Recheck the failed path first, then mentally replay all must-have paths and reset from the initial state.

Summarize each repair by evidence, root cause, changed contract, and expected verification result in the existing `revision_response` field.
