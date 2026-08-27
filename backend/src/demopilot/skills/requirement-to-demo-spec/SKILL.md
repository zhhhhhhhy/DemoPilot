---
name: requirement-to-demo-spec
description: Convert an unstructured sales request into a bounded, demonstrable specification with traceable interactions and acceptance evidence.
---

# Requirement to demo specification

Turn the request into evidence that downstream agents can implement without guessing.

## Working rules

- Preserve every `must_haves` string verbatim as the requirement identifier. Do not merge, rename, or weaken it.
- Separate customer facts from team assumptions. Unknown business details become clearly labelled fictional demo assumptions, never customer claims.
- For each must-have, determine five things: visible module, sample records, user action, visible result, and reset state.
- Prefer one coherent user journey over unrelated dashboard cards. Connect the three story acts to the same records and state transitions.
- Treat "pure display demo with local simulated data" as a fixed boundary, not an unfinished integration.
- Do not add a production integration, database, authentication, deployment, or business outcome unless the request explicitly requires it within the demo boundary.

## Acceptance contract

Before returning the agent's required JSON schema, verify that:

1. Every must-have can be demonstrated through at least one browser action and visible result.
2. Combined operations describe their composition, such as filtering first and sorting only the filtered subset.
3. Creation and workflow requirements define validation, the newly created record, allowed state transitions, and timeline evidence.
4. Drill-down requirements identify the parent record and the related details that must appear.
5. Reset requirements state the exact initial values that must be restored.
6. Success criteria describe observable demo behavior, not subjective phrases such as "smart" or "efficient".

Keep the current agent's output fields unchanged. This skill improves decisions; it does not introduce a new response schema.
