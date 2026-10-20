"""Trusted fresh-context Chromium execution of quotation business contracts."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import re
import secrets
import socket
from decimal import Decimal, InvalidOperation
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.async_api import async_playwright

from .quotation_contract import QuoteModel, journeys


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BrowserHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        # Windows SO_REUSEADDR can allow a second live server on the same port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def browser_http_server(app_dir):
    """Bind and retain a loopback socket in Chromium's permitted high range.

    An OS-selected port0 may be10080, which Chromium deliberately blocks.
    Never override browser protections or release a reservation before serving.
    Retry only bind conflicts/permissions, with a fixed finite budget.
    """
    for _ in range(32):
        port = 49152 + secrets.randbelow(16384)
        try:
            return BrowserHTTPServer(
                ("127.0.0.1", port), partial(QuietHandler, directory=str(app_dir))
            )
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, errno.EACCES}:
                raise
    raise OSError("No available browser-compatible loopback port after32 bind attempts")


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


def _active_fields(contract):
    fields = dict(FIELDS)
    if contract.get("version", 1) < 2:
        fields.pop("shipping")
    if contract["workflow"] != "manual_override":
        fields.pop("manual_rate")
    return fields


def _form_mismatches(expected, actual):
    """Compare committed business values, allowing equivalent numeric display."""
    mismatches = {}
    for key, value in expected.items():
        value, observed = str(value), actual.get(key)
        equal = value == observed
        if not equal and key in {"quantity", "second_quantity", "manual_rate"}:
            try:
                equal = Decimal(value) == Decimal(observed)
            except (TypeError, InvalidOperation):
                pass
        if not equal:
            mismatches[key] = dict(expected=value, actual=observed)
    return mismatches


async def _assert_restored_form(page, contract, values):
    # Observe immediately after selecting a record or reloading, before the
    # Calculate driver can overwrite stale form fields. Staged invalid edits
    # between these boundaries are deliberately not compared to committed data.
    fields = _active_fields(contract)
    actual = await page.locator("body").evaluate(
        """(body, fields) => Object.fromEntries(Object.entries(fields).map(
            ([key,id]) => [key, document.getElementById(id)?.value ?? null]))""",
        fields,
    )
    expected = {key: str(values[key]) for key in fields}
    mismatches = _form_mismatches(expected, actual)
    if mismatches:
        raise AssertionError(
            "Committed form fields were not restored: "
            + json.dumps(mismatches, ensure_ascii=False)
        )
    return dict(expected=expected, observed=actual)


async def _assert_rejection_message(page, *, accepted, action, button_disabled):
    required = accepted is False and action not in (None, "reload") and not button_disabled
    observed = dict(required=required, button_disabled=button_disabled)
    if not required:
        return observed
    error = page.locator("#error")
    visible = await error.is_visible()
    text = (await error.inner_text()).strip() if visible else ""
    observed.update(visible=visible, text=text)
    if not text:
        raise AssertionError(
            f"Rejected clickable action {action!r} requires a visible nonempty #error"
        )
    return observed


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
    server = browser_http_server(app_dir)
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
                        # Aborting an outgoing request keeps the test safe; it
                        # does not make an application that attempted it valid.
                        network_attempts = []

                        async def offline_request(route, *, attempts=network_attempts):
                            request = route.request
                            local = request.url.startswith(base_url)
                            read_only = request.method in {"GET", "HEAD"}
                            if local and read_only:
                                await route.continue_()
                                return
                            attempts.append(dict(
                                kind="http_request",
                                url=request.url,
                                method=request.method,
                                resource_type=request.resource_type,
                                navigation=request.is_navigation_request(),
                                reason="external_request" if not local else "submission_attempt",
                                action="aborted_before_destination",
                            ))
                            await route.abort()

                        def csp_violation(_source, detail, *, attempts=network_attempts):
                            attempts.append(dict(kind="csp_violation", **detail))

                        await context.expose_binding("__demopilotCspViolation", csp_violation)
                        await context.add_init_script("""document.addEventListener('securitypolicyviolation', e => {
                            window.__demopilotCspViolation({
                                url:e.blockedURI, directive:e.effectiveDirective,
                                action:'blocked_by_csp'
                            }).catch(() => {});
                        });""")
                        await context.route("**/*", offline_request)
                        page = await context.new_page()
                        page.set_default_timeout(3000)
                        errors = []
                        page.on(
                            "pageerror",
                            lambda error, page_errors=errors: page_errors.append(str(error)),
                        )
                        model = QuoteModel(contract)
                        trace = []
                        initial_form = None
                        failure = None
                        step = -1
                        try:
                            await page.goto(base_url, wait_until="load", timeout=8000)
                            initial_form = await _assert_restored_form(
                                page, contract, model.current["values"]
                            )
                            initial = model.snapshot()
                            if label == "new_shipping":
                                initial["_require_freight"] = True
                            await _assert_snapshot(page, initial)
                            for step, op in enumerate(ops):
                                form_restoration = None
                                for key in ("record", "role", "actor", "reason", "today"):
                                    if key in op:
                                        await _set(page, key, op[key])
                                        if key == "record" and op[key] != model.record:
                                            form_restoration = await _assert_restored_form(
                                                page, contract, model.records[op[key]]["values"]
                                            )
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
                                button_disabled = None
                                if action == "reload":
                                    await page.reload(wait_until="load")
                                    form_restoration = await _assert_restored_form(
                                        page, contract, model.current["values"]
                                    )
                                elif action:
                                    button = page.locator("#" + action)
                                    button_disabled = await button.is_disabled()
                                    if not button_disabled:
                                        await button.click()
                                rejection_message = await _assert_rejection_message(
                                    page, accepted=accepted, action=action,
                                    button_disabled=button_disabled,
                                )
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
                                        form_restoration=form_restoration,
                                        rejection_message=rejection_message,
                                    )
                                )
                            if network_attempts:
                                raise AssertionError(
                                    "Generated application attempted prohibited network/submission actions: "
                                    + json.dumps(network_attempts[:8], ensure_ascii=False)
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
                            initial_form=initial_form,
                            steps=trace,
                            browser_errors=errors,
                            network_attempts=network_attempts,
                            network_attempt_count=len(network_attempts),
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
        schema_version="quotation-business-browser-v3",
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
        network_attempt_count=sum(r["network_attempt_count"] for r in rows),
        browser_server=dict(host="127.0.0.1", port=server.server_port,
                            selection="bound high port49152-65535; browser protections unchanged"),
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
