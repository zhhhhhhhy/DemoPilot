---
name: mock-business-data
description: Design internally consistent fictional business data that supports filters, drill-downs, comparisons, workflows, and deterministic reset without implying real integration.
---

# Mock business data

Use fictional local records as a coherent demo fixture, not as random decoration.

## Fixture design

- Include enough contrasting records for every filter, sort, empty-state, anomaly, and comparison requirement to produce an observable result.
- Give records stable IDs and preserve referential integrity across summaries, lists, drill-downs, tasks, and timelines.
- Include ordinary, warning, and critical examples only when the scenario needs them. Make anomaly reasons explainable from visible fields.
- Keep totals, counts, percentages, rankings, labels, and detail values consistent across the page.
- Use realistic units and ranges without claiming they came from the customer or a production system.

## State changes

- Keep immutable initial fixtures separate from user-created demo records.
- Task creation must validate required values and generate a deterministic visible record.
- State transitions must follow a small allowed state machine and append a timestamp-like fictional timeline entry.
- Reset must restore the exact initial fixtures, filters, selections, counts, details, and story position.

## Disclosure

Display a concise statement that the data is simulated and no customer production system is connected. Do not turn this correct boundary into an issue or open gate.
