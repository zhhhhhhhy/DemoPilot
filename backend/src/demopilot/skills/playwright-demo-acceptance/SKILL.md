---
name: playwright-demo-acceptance
description: Define and verify requirement-bound browser tests that execute real controls and assert visible business outcomes rather than labels or self-reported completion.
---

# Playwright demo acceptance

Treat a test as proof only when it performs the user's action and observes the required business result.

## Test design

- Freeze one acceptance path per verbatim must-have before trusting the implementation.
- Start each path from a known initial state. If prior actions are needed, include them explicitly or reset first.
- Prefer stable IDs on controls and result regions. Never use a feature chip, navigation label, or decorative card as proof of business behavior.
- Assert both the expected result and a meaningful exclusion when the requirement involves filtering, validation, reset, or state transitions.
- Keep the action budget small enough to diagnose failures, while including every prerequisite action.

## High-risk patterns

- Filter plus sort: select a non-empty filter, sort, then prove excluded records stay absent.
- Drill-down: click the anomaly record, then prove related entity and reason details appear.
- Plan comparison: compare visible dimensions, click a real selection button, then prove the chosen plan is visible.
- Validated creation: prove an invalid submission creates nothing, then fill required fields and prove the new record or count appears.
- Workflow: create or select a task, transition it, then assert both status and the task-specific timeline.
- Reset: first mutate state, reset, then assert exact initial content. Do not use a generic `text_changed` assertion for returning to an initial value.

## Evidence boundary

Browser success, zero console errors, artifact validation, and Reviewer judgment are separate signals. Do not let any one of them substitute for the others.
