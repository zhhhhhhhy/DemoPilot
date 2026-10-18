# hard-v2 semantic gap — 2026-10-07

The eight hard-v2 cases are structurally valid: their files, hashes, selectors and four journeys are consistent, and all eight reached `published` in the real treatment run. The data is still too generic to support a strong claim about business difficulty.

The fixtures mostly contain three placeholder entities, three placeholder subentities, one text rule and terminal metadata. The journeys mostly click the same phase controls and assert generic status text. The declared filter and approval controls are not exercised by the journeys, and the current contracts do not prove concrete numeric thresholds, multi-role approvals, business-record aggregates, or mutation-based cross-entity isolation.

Therefore the 8/8 result should be read as: “the Core Builder and release loop can execute and publish eight structurally valid contracts.” It should not be read as: “the Agent Core solved eight realistic hard business applications.” The next dataset revision must add case-specific records, values, roles and stronger stateful assertions before this set is suitable as a business-difficulty benchmark.
