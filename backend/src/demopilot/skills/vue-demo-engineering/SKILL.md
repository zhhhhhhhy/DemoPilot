---
name: vue-demo-engineering
description: Build maintainable Vue-style interactive demo behavior with explicit state, deterministic rendering, stable selectors, and safe DOM updates.
---

# Vue-style demo engineering

Apply component and state-management discipline even when the current artifact contract is dependency-free HTML, CSS, and JavaScript. Do not add Vue or a package manager when the contract permits only static files.

## State and rendering

- Keep one canonical state object for filters, sort, selection, created tasks, workflow state, story position, and open detail.
- Derive rendered views from canonical state. Do not let DOM text become the source of truth.
- Compose operations in a stable order: source data → filters → sort → render. Sorting must never restore filtered-out records.
- Give each business module a focused render function and each user action one explicit handler.
- Reset by restoring a fresh copy of the initial state and rerendering every dependent module.

## Interaction contracts

- Use native `button`, `input`, `select`, and labelled controls. Disabled and validation states must be visible.
- Use stable, unique IDs for action controls and result regions referenced by browser tests.
- A successful form submission must create a visible record and update the count from canonical state. An invalid submission must create nothing and show a useful message.
- A workflow transition must update both the current status and its business timeline. Do not confuse it with the three-act story timeline.
- A plan comparison must contain actual selection buttons and persist the selected plan visibly.
- Use `textContent`, `createElement`, and `replaceChildren`; never introduce unsafe HTML insertion or network access.

## First-pass preflight

Trace each declared interaction test against the actual initial state, selector, handler, state mutation, render function, and visible assertion. Correct mismatches before returning complete replacement files.
