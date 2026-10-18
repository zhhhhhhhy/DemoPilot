"""Controlled real-CLI repair integration; seeded fault, not model accuracy."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))

from demopilot.core_harness import CodexCliHarness
from demopilot.quotation_browser import audit_application, tree_hash
from demopilot.quotation_cli import IsolatedCodexProvider
from demopilot.quotation_loop import QuotationGoalLoop, write_json
from demopilot.quotation_release import ReleaseRegistry


class ControlledFaultHarness:
    name = 'real_codex_cli_controlled_intermediate_fault'

    def __init__(self, delegate, registry, output):
        self.delegate = delegate
        self.registry = registry
        self.output = output
        self.calls = 0
        self.injected = False
        self.hidden_before_repair = None

    async def build(self, **kwargs):
        self.calls += 1
        if self.injected:
            self.hidden_before_repair = self.registry.resolve('qflow-01') is None
            if not self.hidden_before_repair:
                raise AssertionError('An incorrect candidate became visible before repair')
        kwargs['prompt'] += '''
Controlled recovery integration setup: a previously generated and independently accepted implementation is already in card-web as a starting fixture. Validate and preserve it; do not unnecessarily regenerate the application. This supplied starting code overrides the generic from-scratch statement above. All current goals and public test rules remain authoritative. On a later call, repair concrete parent findings within this same workspace. This is not an independent generation-accuracy trial.
'''
        result = await self.delegate.build(**kwargs)
        if not self.injected:
            path = kwargs['workspace'] / 'card-web/app.js'
            before = tree_hash(kwargs['workspace'] / 'card-web')
            # Deliberate test-driver corruption AFTER the real CLI returned.
            # We do not claim that the model itself naturally made this error.
            with path.open('a', encoding='utf-8') as handle:
                handle.write("\n/* CONTROLLED_INTERMEDIATE_FAULT */\nwindow.addEventListener('click',()=>{document.getElementById('total').textContent='0.00'});\n")
            self.injected = True
            write_json(self.output / 'injection.json', dict(
                kind='test_driver_seeded_semantic_error_not_natural_model_failure',
                after_real_cli_call=self.calls, before_sha256=before,
                after_sha256=tree_hash(kwargs['workspace'] / 'card-web'),
                modified_only='isolated workspace/card-web/app.js',
            ))
        return result

    async def acceptance_check(self, **kwargs):
        return await self.delegate.acceptance_check(**kwargs)


async def main(output):
    if output.exists():
        raise RuntimeError('Use a fresh controlled-test output; preserve every attempt')
    app = json.loads((ROOT / 'evaluation_sets/quotation-reliability-v2/apps.json').read_text('utf-8'))['apps'][0]
    seed = ROOT / 'evaluation_sets/quotation-reliability-v2/results/development-v2-20261016/qflow-01/reliable/terminal-v1'
    workspace = output / 'workspace'
    workspace.mkdir(parents=True)
    shutil.copytree(seed, workspace / 'card-web')
    registry = ReleaseRegistry(output / 'registry')
    provider = IsolatedCodexProvider(command='codex', model='gpt-6.1-sol', reasoning_effort='medium', timeout_seconds=300, cwd=ROOT)
    harness = ControlledFaultHarness(CodexCliHarness(provider), registry, output)
    loop = QuotationGoalLoop(harness, registry, project_root=ROOT, call_cap=3)
    result = await loop.execute_version(app=app, version=1, arm='reliable', workspace=workspace, result_dir=output / 'execution')
    if result['status'] != 'published':
        write_json(output / 'summary.json', dict(status='failed', real_cli_calls=harness.calls, result=result, boundary='Controlled integration failure, never a primary score.'))
        raise RuntimeError('Controlled recovery did not finish within the declared cap')
    failures = [row for row in result['iterations'] if row['check']['status'] == 'failed' and row['cli_error'] is None]
    if not failures or not harness.injected or harness.hidden_before_repair is not True:
        raise AssertionError('Required hidden -> business rejection -> CLI repair sequence not observed')
    contract = json.loads((ROOT / 'testdata/qflow-01/contract-v1.json').read_text('utf-8'))
    final = await audit_application(result['terminal_candidate_path'], contract, output / 'independent-final-audit', private=True)
    if final['status'] != 'passed':
        raise AssertionError('Final repaired artifact failed independent full-data acceptance')
    summary = dict(
        status='passed', kind='controlled_real_cli_repair_integration_not_generation_accuracy',
        actual_cli_calls=harness.calls, configured_cap=3, timeout_seconds=300,
        error_origin='Deliberate test-driver corruption after a real CLI return; no natural model failure claim.',
        initial_candidate_hidden_before_repair=harness.hidden_before_repair,
        trusted_business_rejections=len(failures), final_publication=result['status'],
        independent_planned=final['planned_journeys'], independent_passed=final['passed_journeys'],
        benchmark_artifacts_modified=False, primary_scores_changed=False,
        source_fixture=str(seed), seed_sha256=tree_hash(seed), terminal_sha256=result['terminal_sha256'],
    )
    write_json(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(main(args.output.resolve()))
