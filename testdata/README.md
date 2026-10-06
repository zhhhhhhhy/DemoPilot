# DemoPilot Core testdata

Every evaluation case has an isolated directory here. `inputs.json` describes the local fixture and exact paths; `acceptance.json` is the executable visible-UI acceptance contract; `manifest.json` records hashes. The Core Builder receives these paths in its prompt and may read them from its run workspace.

The invoice images are public, synthetic fixtures pinned by SHA-256 and copied into the invoice cases. Other cases use deterministic fixture records from the authored browser contract. This is a generation-loop evaluation dataset, not a claim of production integrations.
