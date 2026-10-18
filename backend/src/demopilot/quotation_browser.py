"""Trusted fresh-context Chromium execution of quotation business contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.async_api import async_playwright

from .quotation_contract import QuoteModel, journeys


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def tree_hash(path):
    h = hashlib.sha256()
    for p in sorted(Path(path).rglob("*")):
        if p.is_symlink():
            raise ValueError("Symlinks are not accepted artifacts")
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
    return h.hexdigest()


FIELDS = dict(
    profile="profile",
    product="product",
    quantity="quantity",
    second_product="second-product",
    second_quantity="second-quantity",
    customer="customer",
    date="date",
    manual_rate="manual-rate",
    shipping="shipping",
)
SELECTS = {
    "profile",
    "product",
    "second_product",
    "customer",
    "shipping",
    "role",
    "actor",
    "record",
}
OUTPUTS = dict(
    state="state",
    revision="revision",
    approved_revision="approved-revision",
    history_count="history-count",
    subtotal="subtotal",
    discount="discount",
    tax="tax",
    total="total",
    free_quantity="free-quantity",
)


async def _set(page, key, value, *, allow_disabled=False):
    loc = page.locator("#" + FIELDS.get(key, key))
    if allow_disabled and await loc.is_disabled():
        return
    if key in SELECTS:
        await loc.select_option(str(value), timeout=3000)
    else:
        await loc.fill(str(value), timeout=3000)


async def _assert_snapshot(page, expected):
    selectors = dict(OUTPUTS)
    if expected.get("_require_freight"):
        selectors["freight"] = "freight"
    # One DOM read for a coherent visible snapshot, instead of ten sequential
    # remote round-trips whose values could straddle a render. Actions remain
    # genuine Playwright fill/select/click operations.
    actual = await page.locator("body").evaluate(
        """(body, selectors) => {
      const result={};
      for(const [key,id] of Object.entries(selectors)) {
        const el=document.getElementById(id);
        if(!el || !el.getClientRects().length) result[key]='<missing-or-hidden>';
        else result[key]=el.innerText.trim();
      }
      return result;
    }""",
        selectors,
    )
    mismatches = {
        k: dict(expected=expected[k], actual=actual[k]) for k in actual if actual[k] != expected[k]
    }
    if mismatches:
        raise AssertionError(json.dumps(mismatches, ensure_ascii=False))
    return actual


def chromium_diagnostic_options(evidence_dir):
    """Keep trusted runtime diagnostics outside the generated application tree."""
    log = (Path(evidence_dir).resolve() / "chromium.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    return dict(
        env={**os.environ, "CHROME_LOG_FILE": str(log)},
        args=["--enable-logging", "--log-file=" + str(log)],
    )


async def audit_application(app_dir, contract, evidence_dir, *, private=False):
    app_dir, evidence_dir = Path(app_dir).resolve(), Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    before = tree_hash(app_dir)
    rows = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(app_dir)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}/"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, **chromium_diagnostic_options(evidence_dir))
            try:
                for profile in contract["profiles"]:
                    for label, ops in journeys(contract, profile, private=private):
                        context = await browser.new_context()
                        # No authenticated browser, network service or live transaction.
                        await context.route(
                            "**/*",
                            lambda route: (
                                route.continue_()
                                if route.request.url.startswith(base_url)
                                else route.abort()
                            ),
                        )
                        page = await context.new_page()
                        page.set_default_timeout(3000)
                        errors = []
                        page.on(
                            "pageerror",
                            lambda error, page_errors=errors: page_errors.append(str(error)),
                        )
                        model = QuoteModel(contract)
                        trace = []
                        failure = None
                        step = -1
                        try:
                            await page.goto(base_url, wait_until="load", timeout=8000)
                            initial = model.snapshot()
                            if label == "new_shipping":
                                initial["_require_freight"] = True
                            await _assert_snapshot(page, initial)
                            for step, op in enumerate(ops):
                                for key in ("record", "role", "actor", "reason", "today"):
                                    if key in op:
                                        await _set(page, key, op[key])
                                # Form editing is staged until Calculate; reset staged invalid values.
                                next_record = op.get("record", model.record)
                                if op.get("action") == "calculate":
                                    values = dict(
                                        model.records[next_record]["values"], **op.get("values", {})
                                    )
                                    current_form = await page.locator("body").evaluate(
                                        """(body, fields) => Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,document.getElementById(id)?.value]))""",
                                        FIELDS,
                                    )
                                    read_only = op.get(
                                        "role", model.role
                                    ) != "seller" or model.records[next_record]["state"] in (
                                        "Accepted",
                                        "Cancelled",
                                    )
                                    for key, value in values.items():
                                        if key == "shipping" and contract.get("version", 1) < 2:
                                            continue
                                        if (
                                            key == "manual_rate"
                                            and contract["workflow"] != "manual_override"
                                        ):
                                            continue
                                        if current_form.get(key) != str(value):
                                            await _set(page, key, value, allow_disabled=read_only)
                                accepted = model.apply(op)
                                action = op.get("action")
                                if action == "reload":
                                    await page.reload(wait_until="load")
                                elif action:
                                    button = page.locator("#" + action)
                                    if not await button.is_disabled():
                                        await button.click()
                                expected = model.snapshot()
                                if label == "new_shipping":
                                    expected["_require_freight"] = True
                                actual = await _assert_snapshot(page, expected)
                                trace.append(
                                    dict(
                                        step=step,
                                        op=op,
                                        operation_accepted=accepted,
                                        observed=actual,
                                    )
                                )
                            if errors:
                                raise AssertionError("Browser script errors: " + str(errors))
                        except Exception as exc:
                            failure = dict(
                                type=type(exc).__name__,
                                message=str(exc)[:1800],
                                step=step,
                                op=ops[step] if step >= 0 else None,
                            )
                            await page.screenshot(path=str(evidence_dir / f"{profile}-{label}.png"))
                        finally:
                            await context.close()
                        row = dict(
                            profile=profile,
                            journey=label,
                            passed=failure is None,
                            failure=failure,
                            steps=trace,
                            browser_errors=errors,
                        )
                        rows.append(row)
                        (evidence_dir / f"{profile}-{label}.json").write_text(
                            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
            finally:
                await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=3)
    after = tree_hash(app_dir)
    planned = sum(
        len(journeys(contract, profile, private=private)) for profile in contract["profiles"]
    )
    report = dict(
        schema_version="quotation-business-browser-v2",
        private=private,
        version=contract.get("version", 1),
        app_id=contract["id"],
        status="passed"
        if len(rows) == planned and all(r["passed"] for r in rows) and before == after
        else "failed",
        planned_journeys=planned,
        executed_journeys=len(rows),
        passed_journeys=sum(r["passed"] for r in rows),
        source_unchanged=before == after,
        source_sha256=before,
        rows=rows,
        issues=[f"{r['profile']}/{r['journey']}: {r['failure']}" for r in rows if not r["passed"]][
            :12
        ],
    )
    (evidence_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def structural_check(app_dir):
    app_dir = Path(app_dir)
    issues = []
    for name in ("index.html", "app.js", "styles.css"):
        if not (app_dir / name).is_file():
            issues.append("missing " + name)
    if not issues:
        html = (app_dir / "index.html").read_text("utf-8")
        if re.search(r'<script[^>]+src=["\']https?://|<link[^>]+href=["\']https?://', html, re.I):
            issues.append("External executable dependencies prohibited")
    return dict(status="failed" if issues else "passed", issues=issues)
