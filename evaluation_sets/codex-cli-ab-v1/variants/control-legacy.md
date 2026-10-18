# Control prompt profile: pre-IT-005

This file records the control condition used by the executable pilot. The Core receives only the free-form scenario, priority and must-have capabilities, plus the same common file/acceptance rules used by treatment. It does not receive the structured evaluation intent, goal, flow steps, expected result or evaluation method in the prompt header. Each run is labeled `prompt_profile=control-legacy`.

This is an intent-format control, not an attempt to weaken the deterministic gates. The harness still copies the same testdata, runs the same acceptance child, uses the same Chromium checks, and applies the same publication rule. The only planned difference is the information and structure supplied in the Core Builder prompt.

This profile is a record of the control condition, not a new instruction to weaken the acceptance contract. The same authored `acceptance.json`, static checks, Chromium gates and publication rule remain active in both variants.
