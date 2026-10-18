"""Exercise the actual local release API and pinned generated applications."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))
from demopilot.quotation_browser import _assert_snapshot, chromium_diagnostic_options
from demopilot.quotation_contract import QuoteModel


async def main(base, registry, output):
    if output.exists():
        raise RuntimeError('Preserve earlier live delivery evidence')
    output.mkdir(parents=True)
    with urlopen(base + '/api/projects', timeout=10) as response:
        api = json.load(response)
    assert all('token' not in job for job in api['jobs'])
    intent_versions = {row['project']: row['revision'] for row in api['intents']}
    release_by_id = {row['project']: row for row in api['releases']
                     if row['revision'] == intent_versions.get(row['project'])}
    manifest = json.loads((registry / 'delivery-manifest.json').read_text('utf-8'))
    assert len(intent_versions) == manifest['application_groups']
    assert len(release_by_id) == manifest['current_visible']
    rows = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, **chromium_diagnostic_options(output))
        try:
            desk = await browser.new_page(viewport=dict(width=1280, height=900))
            await desk.goto(base + '/', wait_until='load')
            await desk.screenshot(path=str(output / 'release-desk.png'), full_page=True)
            await desk.close()
            for project, release in sorted(release_by_id.items()):
                contract = json.loads((ROOT / 'testdata' / project / 'contract-v2.json').read_text('utf-8'))
                prefix = f"/accepted/{project}/{release['revision']}/{release['artifact']}/"
                asset_checks = []
                for name in ('index.html', 'app.js', 'styles.css'):
                    with urlopen(base + f'/projects/{project}/demo/' + name, timeout=10) as response:
                        body = response.read()
                        exact = body == (registry / 'artifacts' / release['artifact'] / name).read_bytes()
                        assert prefix in response.url and exact
                        assert response.headers['X-DemoPilot-Artifact'] == release['artifact']
                        asset_checks.append(dict(file=name, exact_bytes=True, sha256=hashlib.sha256(body).hexdigest()))
                context = await browser.new_context(viewport=dict(width=1280, height=1000))
                await context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                page = await context.new_page()
                errors, failed_responses = [], []
                page.on('pageerror', lambda error, target=errors: target.append(str(error)))
                page.on('response', lambda response, target=failed_responses: target.append(dict(url=response.url, status=response.status)) if response.status >= 400 else None)
                await page.goto(base + f'/projects/{project}/demo/index.html', wait_until='load')
                model = QuoteModel(contract)
                await _assert_snapshot(page, model.snapshot())
                assert not errors and not failed_responses
                detailed = None
                if project == 'qflow-04':
                    for name, value in [('profile', 'quantity_tiers'), ('product', 'A'), ('second-product', 'B'), ('shipping', 'express')]:
                        await page.locator('#' + name).select_option(value)
                    await page.locator('#quantity').fill('11')
                    await page.locator('#second-quantity').fill('0')
                    await page.locator('#calculate').click()
                    assert (await page.locator('#total').inner_text()).strip() == '930.00'
                    await page.locator('#submit').click()
                    await page.locator('#role').select_option('manager')
                    await page.locator('#actor').select_option('manager1')
                    await page.locator('#approve').click()
                    assert (await page.locator('#state').inner_text()).strip() == 'PendingManager'
                    history = await page.locator('#history-count').inner_text()
                    if not await page.locator('#approve').is_disabled():
                        await page.locator('#approve').click()
                    assert (await page.locator('#state').inner_text()).strip() == 'PendingManager'
                    assert await page.locator('#history-count').inner_text() == history
                    await page.locator('#actor').select_option('manager2')
                    await page.locator('#approve').click()
                    assert (await page.locator('#state').inner_text()).strip() == 'Approved'
                    assert (await page.locator('#approved-revision').inner_text()).strip() == '1'
                    await page.screenshot(path=str(output / 'quote-approved.png'), full_page=True)
                    await page.locator('#role').select_option('seller')
                    await page.locator('#actor').select_option('seller1')
                    await page.locator('#quantity').fill('12')
                    await page.locator('#calculate').click()
                    assert (await page.locator('#state').inner_text()).strip() == 'Draft'
                    assert (await page.locator('#approved-revision').inner_text()).strip() == '-1'
                    assert (await page.locator('#revision').inner_text()).strip() == '2'
                    assert (await page.locator('#total').inner_text()).strip() == '1010.00'
                    detailed = dict(total='930.00', same_manager_cannot_approve_twice=True,
                                    two_distinct_managers_required=True, edit_invalidates_approval=True)
                assert not errors and not failed_responses
                rows.append(dict(project=project, pinned_url=page.url, initial_visible_snapshot_passed=True,
                                 exact_assets=asset_checks, browser_errors=errors, failed_http_responses=failed_responses,
                                 detailed=detailed))
                await context.close()
        finally:
            await browser.close()
    result = dict(status='passed', base_url=base, visible_projects=len(rows), intent_projects=len(api['intents']),
                  token_exposed=False, real_local_chromium=True, screenshots_are_actual_live_server=True,
                  production_customer_data=False, rows=rows)
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], visible_projects=len(rows), pinned_assets_verified=3 * len(rows)), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5188')
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.base_url.rstrip('/'), args.registry.resolve(), args.output.resolve()))
