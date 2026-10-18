"""Reproduce old unversioned delivery race and verify pinned-release behavior."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend/src'))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import FileResponse
from demopilot.quotation_api import create_app
from demopilot.quotation_browser import tree_hash
from demopilot.quotation_release import ReleaseRegistry
from demopilot.quotation_loop import write_json


def main():
    out=ROOT/'docs/quotation-reliability-v2/bundle-race'
    if (out/'result.json').exists():raise RuntimeError('Preserve existing fault-injection evidence')
    reg=ReleaseRegistry(out/'controlled-registry');source=out/'source';source.mkdir(parents=True)
    def publish(version):
        (source/'index.html').write_text(f'<h1>HTML v{version}</h1><script src="app.js"></script>')
        (source/'app.js').write_text(f'const releaseVersion={version};')
        reg.set_intent('quote',version,dict(controlled_goal=version));job=reg.claim('quote',version,f'j{version}')
        # The unit fixture supplies a trusted check to isolate delivery semantics.
        # This is not an actual CLI/browser business-acceptance result.
        report=dict(status='passed',source_sha256=tree_hash(source),source_unchanged=True,planned_journeys=1,executed_journeys=1,passed_journeys=1,controlled_fixture=True)
        check=reg.record_check(job['id'],job['token'],tree_hash(source),report);reg.publish(job['id'],job['token'],check,source)
    publish(1)
    legacy=FastAPI()
    @legacy.get('/demo/{file_path}')
    def legacy_file(file_path:str):
        # Minimal exact old behavior: independently resolve current on every GET.
        return FileResponse(Path(reg.resolve('quote')['path'])/file_path)
    old=TestClient(legacy);fixed=TestClient(create_app(reg.root))
    old_html=old.get('/demo/index.html').text
    pinned=fixed.get('/projects/quote/demo/index.html',follow_redirects=False).headers['location']
    publish(2)
    old_js=old.get('/demo/app.js').text
    pinned_js=fixed.get(pinned.rsplit('/',1)[0]+'/app.js').text
    current_js=fixed.get('/projects/quote/demo/app.js').text
    report=dict(kind='controlled-http-interleaving-not-model-score',legacy=dict(html=old_html,subsequent_js=old_js,mixed_versions='HTML v1' in old_html and 'releaseVersion=2' in old_js),
                fixed=dict(pinned_html_url=pinned,pinned_js=pinned_js,current_js=current_js,correct='releaseVersion=1' in pinned_js and 'releaseVersion=2' in current_js))
    assert report['legacy']['mixed_versions'] and report['fixed']['correct']
    write_json(out/'result.json',report);print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
