"""Reread exact CLI prompts and mounted fixtures; no business-score feedback."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend/src'))
from demopilot.quotation_browser import tree_hash
from demopilot.quotation_loop import write_json


def verify(directory):
    context=json.loads((directory/'context.json').read_text('utf-8'));rows=[]
    for app in context['apps']:
        for version in (1,2):
            values={}
            for arm in ('direct','reliable'):
                base=directory/app['id']/arm
                prompt=(base/f'v{version}/iteration-0/cli/prompt.txt').read_text('utf-8')
                values[arm]=prompt.replace(str((base/'workspace').resolve()),'<WORKSPACE>')
            equal=values['direct']==values['reliable']
            rows.append(dict(app_id=app['id'],version=version,identical_goal_after_workspace_normalization=equal))
    for app in context['apps']:
        roots={arm:directory/app['id']/arm/'workspace/testdata' for arm in ('direct','reliable')}
        equal=tree_hash(roots['direct'])==tree_hash(roots['reliable'])
        rows.append(dict(app_id=app['id'],identical_public_fixture_bytes=equal))
    assert all(r.get('identical_goal_after_workspace_normalization',r.get('identical_public_fixture_bytes')) for r in rows),rows
    return dict(split=context['split'],all_equal=True,model=context['model'],reasoning=context['reasoning_effort'],call_cap=context['call_cap_per_version'],timeout=context['cli_timeout_seconds'],rows=rows,
                boundary='Goal and public fixture parity; subsequent generated code differs naturally. Equal configured caps do not force identical consumed tokens or internal subagent use.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    write_json(a.output,{d.name:verify(d.resolve()) for d in a.directories});print('exact information/model/budget parity checks passed')
