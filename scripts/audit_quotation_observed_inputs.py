"""Inspect returned CLI command events, without claiming OS read isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def inspect(directory):
    calls, flagged, source_flags, count = [], [], [], 0
    for path in sorted(directory.glob('qflow-*/*/v*/iteration-*/cli/stdout.jsonl')):
        commands = {}
        malformed = 0
        for line in path.read_text('utf-8').splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            item = event.get('item', {})
            if item.get('type') == 'command_execution':
                commands[item.get('id', str(len(commands)))] = item.get('command', '')
        count += len(commands)
        for item_id, command in commands.items():
            normalized = command.replace('\\\\', '/').replace('\\', '/')
            reasons = []
            if re.search(r'quotation[_./]contract|quotation_oracle|private\s*=\s*True|/private/', normalized, re.I):
                reasons.append('possible_private_or_reference_implementation_access')
            if re.search(r'(?:verify|audit|calibrate|materialize|report|run)_quotation_(?:reliability|live_delivery|real_repair)', normalized, re.I):
                reasons.append('possible_evaluation_driver_access')
            arm = path.relative_to(directory).parts[1]
            other = 'reliable' if arm == 'direct' else 'direct'
            if re.search(r'qflow-\d+/' + other + '/', normalized, re.I):
                reasons.append('possible_other_arm_access')
            if reasons:
                flagged.append(dict(trace=str(path), item_id=item_id, command=command, reasons=reasons))
        calls.append(dict(trace=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          command_events=len(commands), malformed_lines=malformed))
    for workspace in directory.glob('qflow-*/*/workspace'):
        for folder in ('card', 'card-web'):
            for path in (workspace / folder).rglob('*'):
                if not path.is_file() or path.suffix.lower() not in ('.py', '.js', '.ts', '.mjs', '.cjs', '.ps1', '.sh', '.md'):
                    continue
                body = path.read_text('utf-8', errors='replace')
                if re.search(r'demopilot\.quotation_contract|quotation_oracle|private\s*=\s*True|[/\\]private[/\\]', body):
                    source_flags.append(dict(file=str(path), reason='possible_private_or_reference_access_in_authored_helper'))
    return dict(scope=str(directory), calls_with_returned_traces=len(calls), commands_checked=count,
                flags_requiring_manual_review=flagged, authored_source_flags=source_flags, traces=calls,
                boundary='Only root CLI returned command events were inspected. Internal native child-agent reads and arbitrary OS reads are not exhaustively observable; no OS read-isolation claim. Running the explicitly supplied public probe is allowed. No audit feedback was supplied to the builder.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = {d.name: inspect(d.resolve()) for d in args.directories}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: dict(calls=v['calls_with_returned_traces'], commands=v['commands_checked'],
                             flags=len(v['flags_requiring_manual_review']), source_flags=len(v['authored_source_flags'])) for k, v in result.items()}))
