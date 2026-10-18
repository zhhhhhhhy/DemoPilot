"""Isolated manual acceptance server with one explicit pre-publication fault.

The model is always the real Codex CLI. This driver corrupts only the first
completed candidate, after the model returns and before the trusted business
gate. It never patches a release or supplies a generated implementation.
Production main:app does not import or enable this driver.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from demopilot.config import Settings
from demopilot.core_harness import CodexCliHarness
from demopilot.main import create_app
from demopilot.quotation_cli import IsolatedCodexProvider
from demopilot.sales_core import SalesCoreManager


class OneFaultHarness:
    name = "real_codex_cli_with_explicit_controlled_fault"

    def __init__(self, inner):
        self.inner = inner
        self.injected = False

    async def build(self, **kwargs):
        result = await self.inner.build(**kwargs)
        source = kwargs["workspace"] / "card-web" / "app.js"
        if not self.injected and source.is_file():
            with source.open("a", encoding="utf-8") as stream:
                stream.write("""\n// CONTROLLED_PREPUBLICATION_FAULT: test driver, not a natural model failure.
(()=>{const install=()=>document.getElementById('calculate')?.addEventListener('click',()=>{document.getElementById('total').textContent='0.00'});if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install()})();
""")
            self.injected = True
            result["controlled_fault_injected"] = True
            print(json.dumps({"event": "controlled_fault_injected", "workspace": str(kwargs["workspace"])}, ensure_ascii=False), flush=True)
        return result


def factory():
    settings = Settings(data_dir=ROOT / ".data" / "sales-core-fault-check")
    provider = IsolatedCodexProvider(command=settings.codex_command, model=settings.codex_model,
                                     reasoning_effort=settings.codex_reasoning_effort,
                                     timeout_seconds=settings.codex_timeout_seconds)
    manager = SalesCoreManager(settings, harness=OneFaultHarness(CodexCliHarness(provider)))
    app = create_app(settings, sales_core=manager)
    app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="acceptance-only-ui")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()
    print("CONTROLLED TEST ONLY: first completed candidate is deliberately corrupted before trusted checking", flush=True)
    uvicorn.run(factory(), host="127.0.0.1", port=args.port)
