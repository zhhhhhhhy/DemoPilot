"""Reconcile frozen inputs, complete final audits and delivery; no rescoring."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))
from demopilot.quotation_browser import tree_hash
from demopilot.quotation_contract import compile_acceptance


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(directories, delivery, output):
    checks = []

    def check(name, ok, detail):
        checks.append(dict(name=name, passed=bool(ok), detail=detail))

    data = ROOT / 'evaluation_sets/quotation-reliability-v2'
    apps = read(data / 'apps.json')['apps']
    cases = read(data / 'cases.json')['cases']
    check('explicit_grouped_100_combinations', len(apps) == 10 and len(cases) == 100
          and len({r['id'] for r in cases}) == 100
          and all(sum(c['app_id'] == app['id'] for c in cases) == 10 for app in apps),
          dict(application_groups=len(apps), combinations=len(cases), independent_primary_groups=7))
    sources = set(read(data / 'sources.json')['source_urls'])
    check('source_backed_authored_rules', all(set(c['source_urls']) <= sources for c in cases),
          dict(public_sources=len(sources), real_customer_claim=False))
    manifest = read(data / 'manifest.json')['files']
    drift = [p for p, digest in manifest.items() if sha(ROOT / p) != digest]
    check('all_frozen_data_unchanged', not drift, dict(files=len(manifest), drift=drift))
    bad_plans, identical_vectors = [], []
    for app in apps:
        for version in (1, 2):
            contract = read(ROOT / app['testdata_path'] / f'contract-v{version}.json')
            public = read(ROOT / app['testdata_path'] / f'public-tests-v{version}.json')
            private = read(data / 'private' / f'{app["id"]}-v{version}.json')
            if public != compile_acceptance(contract, private=False) or private != compile_acceptance(contract, private=True):
                bad_plans.append([app['id'], version])
            if public['journeys'] == private['journeys']:
                identical_vectors.append([app['id'], version])
    check('explicit_independent_public_and_final_plans', not bad_plans and not identical_vectors,
          dict(plan_pairs=20, drift=bad_plans, identical_vectors=identical_vectors))
    old = read(ROOT / 'evaluation_sets/quotation-intent-v1/results/heldout-20261016/context.json')
    old_drift = [p for p, digest in old['code_sha256'].items() if sha(ROOT / p) != digest]
    check('original_runtime_preserved', not old_drift, dict(files=len(old['code_sha256']), drift=old_drift))
    old_data = read(ROOT / 'evaluation_sets/quotation-intent-v1/manifest.json')['files']
    old_data_drift = [p for p, digest in old_data.items() if sha(ROOT / p) != digest]
    check('original_business_inputs_preserved', not old_data_drift,
          dict(files=len(old_data), drift=old_data_drift))
    closed = read(ROOT / 'docs/quotation-reliability-v2/original-primary-closed.json')
    check('interrupted_original_score_not_replaced',
          sha(directories[1] / 'independent-audit.json') == closed['independent_audit_sha256'], closed)
    cohorts = []
    for directory in directories:
        context = read(directory / 'context.json')
        results = read(directory / 'results.json')['rows']
        audit = read(directory / 'independent-audit.json')
        rows = audit['rows']
        expected_rows = len(context['apps']) * 4
        expected_journeys = len(context['apps']) * 260
        trace_count = sum(len(r['iterations']) for r in results)
        observed_traces = list(directory.glob('qflow-*/*/v*/iteration-*/cli/stdout.jsonl'))
        modified = [r['terminal_candidate_path'] for r in results
                    if tree_hash(r['terminal_candidate_path']) != r['terminal_sha256']]
        snapshots = [p for p, digest in context['source_sha256'].items()
                     if sha(directory / 'frozen-code' / p) != digest]
        consistent = all(r['end_to_end_pass'] == (r['published'] and r['status'] == 'passed')
                         and r['executed_journeys'] == r['planned_journeys'] == len(r['rows'])
                         and r['passed_journeys'] == sum(j['passed'] for j in r['rows'])
                         and r['source_unchanged'] for r in rows)
        check(directory.name + '_complete_original_audit',
              len(results) == len(rows) == expected_rows
              and len({(r['app_id'], r['arm'], r['version']) for r in rows}) == expected_rows
              and sum(r['executed_journeys'] for r in rows) == expected_journeys
              and consistent and not modified and not snapshots and not audit['feedback_to_builder'],
              dict(terminal_versions=len(results), expected=expected_rows, final_browser_paths=expected_journeys,
                   modified_candidates=modified, snapshot_drift=snapshots))
        check(directory.name + '_dialogue_retained', trace_count == len(observed_traces)
              and all((p.parent / 'prompt.txt').is_file() and (p.parent / 'stderr.log').is_file() for p in observed_traces),
              dict(outer_calls=sum(r['cli_calls'] for r in results), traces=len(observed_traces)))
        cohorts.append(dict(name=directory.name, independent_audit_sha256=sha(directory / 'independent-audit.json'),
                            context_sha256=sha(directory / 'context.json'), executed_journeys=expected_journeys))
    latest = read(directories[-1] / 'context.json')
    runtime_drift = [p for p, digest in latest['source_sha256'].items() if sha(ROOT / p) != digest]
    check('latest_runtime_matches_frozen_clean_cohort', not runtime_drift, runtime_drift)
    export = read(delivery / 'delivery-manifest.json')
    check('delivery_uses_exact_independent_accepted_bytes', not export['original_experiment_scores_changed']
          and not export['manual_page_repairs'] and all(r['original_db_unchanged'] for r in export['imports']), export)
    parity = read(ROOT / 'docs/quotation-reliability-v2/final-information-parity.json')
    check('exact_actual_goal_and_fixture_parity', len(parity) == 3 and all(v['all_equal'] for v in parity.values()),
          dict(cohorts=list(parity)))
    conditions = [read(ROOT / 'docs/quotation-reliability-v2' / name) for name in
                  ('clean-primary-generation-run-condition.json', 'clean-primary-audit-run-condition.json')]
    check('clean_replication_run_conditions_recorded', all(v['status'] == 'completed' and not v['heartbeat_gaps']
                                                          and v['thread_request_restored'] for v in conditions),
          dict(recorded_large_heartbeat_gaps=[v['heartbeat_gaps'] for v in conditions], manual_sleep_prevented=False))
    live = read(ROOT / 'docs/quotation-reliability-v2/live-delivery/summary.json')
    check('actual_live_delivery_routes_and_browsers', live['status'] == 'passed'
          and live['visible_projects'] == export['current_visible'] and not live['token_exposed']
          and all(len(r['exact_assets']) == 3 and not r['browser_errors'] and not r['failed_http_responses'] for r in live['rows']),
          dict(visible_projects=live['visible_projects'], actual_pinned_assets=3*live['visible_projects']))
    public_gate = read(ROOT / 'docs/quotation-reliability-v2/public-gate-calibration/summary.json')
    ablation = read(ROOT / 'docs/quotation-reliability-v2/public-gate-calibration/structural-comparison.json')
    check('public_gate_controlled_fault_detection', public_gate['all_expected']
          and public_gate['seeded_faults_rejected'] == 8 and public_gate['valid_controls_accepted'] == 1
          and ablation['business_gate_rejected'] == 8 and ablation['structural_rejected'] == 0,
          dict(seeded_faults=8, structural=ablation['structural_rejected'], business=ablation['business_gate_rejected'],
               boundary='Controlled diagnostic, not natural model accuracy.'))
    repair = read(ROOT / 'docs/quotation-reliability-v2/controlled-real-repair-20261017/summary.json')
    check('actual_cli_internal_repair_before_publication', repair['status'] == 'passed'
          and repair['actual_cli_calls'] >= 2 and repair['initial_candidate_hidden_before_repair']
          and repair['independent_planned'] == repair['independent_passed'] == 60, repair)
    result = dict(status='passed' if all(c['passed'] for c in checks) else 'failed', checks=checks, cohorts=cohorts,
                  synthetic_combinations=100, workflow_groups=10, original_customer_datasets=0,
                  boundary='Observed declared contracts only. Interrupted original cohort and reused clean replication remain separately scored. No claim of arbitrary business correctness, production scale or intent-processing accuracy gain.')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=result['status'], checks=len(checks), failed=[c['name'] for c in checks if not c['passed']]), ensure_ascii=False))
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--delivery', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify([p.resolve() for p in args.directories], args.delivery.resolve(), args.output.resolve())
