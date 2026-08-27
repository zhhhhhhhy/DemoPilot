# DemoPilot API

FastAPI service for the DemoPilot multi-agent demo factory. The workflow includes
brief refinement, manager planning, a parallel product/design stage, artifact
verification, and an evidence-bound Reviewer revision loop. The Reviewer prepares a rubric before build, then reviews the customer request, final project, verifier output, manifest, and Chromium evidence without write access. Dependencies are managed by `uv`.

```powershell
uv sync --extra dev
uv run uvicorn --env-file ../.env --app-dir src demopilot.main:app --reload --port 8091
```

To enable the optional official Claude Agent SDK adapter:

```powershell
uv sync --extra dev --extra claude
$env:DEMOPILOT_ENABLE_CLAUDE = "true"
```

Claude mode also requires a valid Anthropic/Claude Code login. Mock mode is the
default and is intentionally deterministic for local demos and tests.

DeepSeek, AIHubMix, and ZJU use their OpenAI-compatible chat endpoints. They are
enabled only when the corresponding API key, base URL, and model variables are
present in the project root `.env` file.
