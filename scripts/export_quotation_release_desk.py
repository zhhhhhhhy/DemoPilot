"""Export already independently accepted bytes; never repairs or rescores runs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend/src'))

from demopilot.quotation_browser import tree_hash
from demopilot.quotation_loop import write_json
from demopilot.quotation_release import ReleaseRegistry, canonical_hash


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(directories, output):
    if output.exists():
        raise RuntimeError('Delivery export must use a fresh directory; preserve prior exports')
    sources = []
    for directory in directories:
        context = read(directory / 'context.json')
        results = read(directory / 'results.json')['rows']
        audit = read(directory / 'independent-audit.json')['rows']
        expected = len(context['arm_order']) * 2
        if len(results) != expected or len(audit) != expected:
            raise RuntimeError('Every planned app/version must be terminal and audited')
        for relative, digest in context['source_sha256'].items():
            if sha(directory / 'frozen-code' / relative) != digest:
                raise RuntimeError('Archived runtime source changed: ' + relative)
        sources.append((directory, context, results, audit))

    registry = ReleaseRegistry(output)
    imports, excluded = [], []
    for directory, context, results, audit in sources:
        source_root = directory / 'registries/reliable'
        source_db = source_root / 'release.sqlite3'
        before_db = sha(source_db)
        connection = sqlite3.connect(source_db.resolve().as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute('SELECT business_required FROM policy').fetchone()[0] != 1:
                raise RuntimeError('Only the business-gated arm is eligible for delivery')
            evidence = {
                (row['app_id'], row['version']): row
                for row in audit if row['arm'] == 'reliable'
            }
            passing = {key for key, row in evidence.items() if row['end_to_end_pass']}
            data = {
                table: [dict(row) for row in connection.execute('SELECT * FROM ' + table)]
                for table in ('intents', 'jobs', 'checks', 'releases', 'release_history', 'events')
            }
        finally:
            connection.close()
        checks = {row['id']: row for row in data['checks']}
        for release in data['release_history']:
            key = (release['project'], release['revision'])
            if key not in passing:
                excluded.append(dict(source=str(directory), project=key[0], revision=key[1], reason='Independent final audit did not accept this release'))
                continue
            digest = release['artifact']
            if not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise RuntimeError('Invalid artifact digest')
            row = evidence[key]
            if not row['source_unchanged'] or row['source_sha256'] != digest:
                raise RuntimeError('Independent score does not describe the released bytes')
            check = checks[release['check_id']]
            report = json.loads(check['report'])
            calculated = canonical_hash(dict(job=check['job'], artifact=digest, report=report, kind=check['kind']))
            if calculated != check['id'] or not check['passed'] or check['kind'] != 'business':
                raise RuntimeError('Trusted public acceptance record is invalid')
            source = source_root / 'artifacts' / digest
            target = registry.artifacts / digest
            if tree_hash(source) != digest:
                raise RuntimeError('Source immutable artifact changed')
            if not target.exists():
                shutil.copytree(source, target)
            if tree_hash(target) != digest:
                raise RuntimeError('Copied artifact does not match accepted bytes')

        with registry.transaction() as dest:
            for table in ('intents', 'jobs', 'checks'):
                for row in data[table]:
                    columns = list(row)
                    dest.execute(
                        'INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                        [row[column] for column in columns],
                    )
            for table in ('releases', 'release_history'):
                for row in data[table]:
                    if (row['project'], row['revision']) not in passing:
                        continue
                    columns = list(row)
                    dest.execute(
                        'INSERT INTO ' + table + '(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
                        [row[column] for column in columns],
                    )
            for event in data['events']:
                dest.execute('INSERT INTO events(time,kind,payload) VALUES(?,?,?)', (event['time'], event['kind'], event['payload']))
            for job in data['jobs']:
                key = (job['project'], job['revision'])
                if job['status'] == 'published' and key not in passing:
                    dest.execute("UPDATE jobs SET status='quarantined_after_independent_audit' WHERE id=?", (job['id'],))
            registry._event(dest, 'independent_audit_export', dict(source=str(directory), accepted_versions=len(passing), raw_scores_unchanged=True))
        if sha(source_db) != before_db:
            raise RuntimeError('Read-only export changed the original runtime database')
        imports.append(dict(source=str(directory), split=context['split'], accepted_versions=len(passing), context_sha256=sha(directory / 'context.json'), audit_sha256=sha(directory / 'independent-audit.json'), original_db_unchanged=True))

    snapshot = registry.snapshot()
    current = [registry.resolve(row['project']) for row in snapshot['intents']]
    report = dict(
        created_at=datetime.now(UTC).isoformat(), application_groups=len(snapshot['intents']),
        current_visible=sum(row is not None for row in current),
        current_hidden=sum(row is None for row in current), imports=imports, excluded=excluded,
        private_audit_feedback_to_builder=False, manual_page_repairs=False,
        original_experiment_scores_changed=False,
        boundary='Separate delivery copy. Only byte-identical releases accepted in original terminal independent scoring are exposed; any originally incorrect publication remains a failure in the immutable experiment.',
    )
    write_json(output / 'delivery-manifest.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = export([path.resolve() for path in args.directories], args.output.resolve())
    print(json.dumps(result, ensure_ascii=False))
