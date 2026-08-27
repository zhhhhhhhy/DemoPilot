---
name: apple-ui-demo-design
description: Create an Apple-inspired but non-imitative sales demo interface with clear hierarchy, restrained motion, responsive layout, and accessible controls.
---

# Apple-inspired demo design

Create a calm, premium interface without claiming affiliation with Apple or copying proprietary assets.

## Visual system

- Use the customer's exact primary hex color as the action and focus accent, with neutral surfaces and semantic success, warning, and danger colors.
- Establish a visible hierarchy: concise headline, current business state, primary action, supporting details. Avoid equal-weight card grids.
- Use generous spacing, readable typography, subtle borders, restrained shadows, and consistent radii. Prefer clarity over glass effects.
- Keep numbers aligned and units explicit. Do not use decorative charts that contradict the sample data.

## Interaction and accessibility

- Provide visible hover, focus, active, selected, disabled, error, empty, and loading-like states where relevant.
- Keep keyboard focus visible and associate labels with controls. Do not communicate status through color alone.
- Keep motion short and optional; respect `prefers-reduced-motion`.
- At narrow widths, preserve the story, controls, results, and task workflow without horizontal page overflow.

## Demo clarity gate

The first viewport must state the simulated-data boundary and expose the main story or action. A salesperson should be able to explain what changed after every click without inspecting developer tools.
