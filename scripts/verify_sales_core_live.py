"""Read-only final acceptance of a terminal, actually served sales-Core release.

Does not submit requirements, call models, repair source or replace old scores.
Uses private-value browser journeys plus exact HTTP bundle and live-route checks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from demopilot.quotation_browser import (
    _assert_snapshot,
    _set,
    audit_application,
    tree_hash,
)
from demopilot.quotation_contract import QuoteModel, approve_steps
from demopilot.quotation_loop import write_json


async def verify(args):
    if not re.fullmatch(r"[a-f0-9]{16}", args.session):
        raise ValueError("Invalid session identifier")
    base = args.base_url.rstrip("/")
    if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Acceptance is scoped to the local service")
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=base, trust_env=False, timeout=15) as client:
        response = client.get(f"/api/sales-core/sessions/{args.session}")
        response.raise_for_status()
        session = response.json()
        if session["status"] != "published" or not session["demo_url"]:
            raise RuntimeError("Cannot score an unfinished/unpublished session")
        revision = session["revision"]
        directory = args.data_dir / "sales-core" / "sessions" / args.session / f"revision-{revision}"
        result = json.loads((directory / "result.json").read_text("utf-8"))
        if result["status"] != "published":
            raise RuntimeError("Parent has not completed the terminal result")
        release = result["published"]
        artifact = args.data_dir / "sales-core" / "registry" / "artifacts" / release["artifact"]
        if tree_hash(artifact) != release["artifact"]:
            raise RuntimeError("Accepted artifact hash changed")
        version = result["version"]
        contract = json.loads((directory / "inputs" / f"contract-v{version}.json").read_text("utf-8"))
        root_url = session["demo_url"].rsplit("/", 1)[0]
        assets = []
        for name in ("index.html", "app.js", "styles.css"):
            served = client.get(root_url + "/" + name)
            served.raise_for_status()
            if served.content != (artifact / name).read_bytes():
                raise AssertionError("Actual route does not serve exact accepted bytes: " + name)
            if served.headers.get("x-demopilot-revision") != str(revision):
                raise AssertionError("Revision header mismatch")
            assets.append(name)
    private = await audit_application(artifact, contract, args.output / "independent-private", private=True)
    if private["status"] != "passed":
        write_json(args.output / "summary.json", {"status": "failed", "session": args.session, "revision": revision, "failure_stage": "post-publication independent audit", "private": private})
        raise AssertionError("Published app failed final independent private-value checks")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(base + session["demo_url"], wait_until="load")
            model = QuoteModel(contract)
            await _assert_snapshot(page, model.snapshot())
            operations = [
                {"action": "calculate", "values": {"quantity": "5", "second_quantity": "0"}},
                {"action": "submit"}, *approve_steps(contract),
                {"role": "seller", "actor": "seller1", "action": "calculate", "values": {"quantity": "8"}},
            ]
            rows = []
            for index, operation in enumerate(operations):
                for key in ("role", "actor"):
                    if key in operation:
                        await _set(page, key, operation[key])
                for key, value in operation.get("values", {}).items():
                    await _set(page, key, value)
                accepted = model.apply(operation)
                button = page.locator("#" + operation["action"])
                if not await button.is_disabled():
                    await button.click()
                actual = await _assert_snapshot(page, model.snapshot())
                if index == 0 and actual["total"] != args.expected_total:
                    raise AssertionError("Hand-computed 5-item amount mismatch")
                rows.append({"operation": operation, "accepted": accepted, "actual": actual})
                if actual["state"] == "Approved":
                    await page.screenshot(path=str(args.output / "accepted-quote.png"), full_page=True)
            if model.current["state"] != "Draft" or model.current["approved_revision"] != -1:
                raise AssertionError("Editing did not invalidate approval")
            if errors:
                raise AssertionError("Served application script errors: " + str(errors))
            write_json(args.output / "served-flow.json", {"rows": rows, "page_errors": errors})
            await context.close()
        finally:
            await browser.close()
    summary = {"status": "passed", "session": args.session, "revision": revision,
                   "requirement_revision": result["requirement_revision"], "contract_feature_version": version,
                   "cli_calls": result["cli_calls"], "internal_repair_rounds": result["internal_repair_rounds"],
                   "artifact_sha256": release["artifact"], "exact_served_assets": assets,
                   "private_paths": {"planned": private["planned_journeys"], "executed": private["executed_journeys"], "passed": private["passed_journeys"]},
                   "served_operations": len(rows), "expected_five_item_total": args.expected_total,
                   "source_unchanged": tree_hash(artifact) == release["artifact"],
                   "boundary": "Synthetic seller, fresh product interaction. Private audit after terminal publication; no feedback or source repair during final scoring. Headless screenshots are separate from visible CUA browser interaction."}
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".data")
    parser.add_argument("--session", required=True)
    parser.add_argument("--expected-total", required=True, help="Independently hand-computed 5*A total")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(verify(parser.parse_args()))
