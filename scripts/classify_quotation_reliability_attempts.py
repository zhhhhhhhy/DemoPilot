"""Locate failures in internal execution, gate or terminal independent audit."""
import argparse
import json
from pathlib import Path


def classify(directory):
    attempts = []
    for path in sorted(directory.glob('qflow-*/*/v*/iteration-*/iteration.json')):
        row = json.loads(path.read_text('utf-8'))
        check = row['check']
        public_complete = (
            check.get('planned_journeys', 0) > 0
            and check.get('passed_journeys') == check.get('planned_journeys')
        )
        if row.get('cli_error'):
            kind = (
                'internal_cli_execution_public_business_passed'
                if public_complete else 'internal_cli_execution_business_unobserved'
            )
        elif row['engineering']['status'] != 'passed':
            kind = 'internal_engineering_or_write_boundary'
        elif check['status'] != 'passed':
            kind = 'internal_business_repair'
        else:
            kind = 'internal_acceptance_passed'
        attempts.append(dict(
            path=str(path), kind=kind, artifact_sha256=row['artifact_sha256'],
            complete_public_business_observed=public_complete,
            cli_error=row.get('cli_error'), issues=check.get('issues', []),
            counts_as_final_business_failure=False,
        ))
    terminal = []
    audit_path = directory / 'independent-audit.json'
    if audit_path.exists():
        for row in json.loads(audit_path.read_text('utf-8'))['rows']:
            if row['end_to_end_pass']:
                stage = 'final_pass'
            elif row['published']:
                stage = 'published_then_failed_independent_business_audit'
            elif row['status'] == 'passed':
                stage = 'correct_candidate_not_published_execution_or_gate_failure'
            else:
                stage = 'core_terminal_unfulfilled_and_hidden'
            terminal.append(dict(
                app_id=row['app_id'], arm=row['arm'], version=row['version'],
                stage=stage, planned=row['planned_journeys'], passed=row['passed_journeys'],
                failed_journeys=[
                    dict(profile=r['profile'], journey=r['journey'], failure=r['failure'])
                    for r in row['rows'] if not r['passed']
                ],
            ))
    return dict(
        internal_attempts=attempts, final_outcomes=terminal,
        final_audit_available=audit_path.exists(),
        boundary='Internal errors are never counted as final business failures; final outcome requires terminal independent full-data audit.',
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = {d.name: classify(d) for d in args.directories}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: dict(internal_attempts=len(v['internal_attempts']), final_outcomes=len(v['final_outcomes'])) for k, v in result.items()}))
