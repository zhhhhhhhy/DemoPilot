"""Report independent grouped success, unsafe releases and change regression."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(directory):
    directory=Path(directory);audit=json.loads((directory/'independent-audit.json').read_text('utf-8'))
    rows=audit['rows'];metrics={}
    for arm in ('direct','reliable'):
        metrics[arm]={}
        for version in (1,2):
            group=[r for r in rows if r['arm']==arm and r['version']==version]
            by_combo={}
            for row in group:
                profiles={r['profile'] for r in row['rows']}
                for profile in profiles:
                    tests=[r for r in row['rows'] if r['profile']==profile]
                    by_combo[row['app_id']+'/'+profile]=row['published'] and all(r['passed'] for r in tests)
            metrics[arm][f'v{version}']=dict(application_groups=len(group),complete_application_success=sum(r['end_to_end_pass'] for r in group),
                combinations=len(by_combo),complete_combination_success=sum(by_combo.values()),
                published=sum(r['published'] for r in group),incorrectly_published=sum(r['published'] and r['status']!='passed' for r in group),
                functionally_correct_but_hidden=sum(not r['published'] and r['status']=='passed' for r in group),
                planned_journeys=sum(r['planned_journeys'] for r in group),executed_journeys=sum(r['executed_journeys'] for r in group),passed_journeys=sum(r['passed_journeys'] for r in group),
                cli_calls=sum(r['cli_calls'] for r in group),internal_repair_rounds=sum(r['internal_repairs'] for r in group))
        regressions=[];eligible=[]
        first={r['app_id']:r for r in rows if r['arm']==arm and r['version']==1}
        for second in [r for r in rows if r['arm']==arm and r['version']==2]:
            old=first[second['app_id']]
            for profile in {r['profile'] for r in old['rows']}:
                v1=[r for r in old['rows'] if r['profile']==profile]
                v2=[r for r in second['rows'] if r['profile']==profile and r['journey']!='new_shipping']
                if all(r['passed'] for r in v1):
                    key=second['app_id']+'/'+profile;eligible.append(key)
                    if not all(r['passed'] for r in v2):regressions.append(key)
        metrics[arm]['change_regression']=dict(previously_correct_combinations=len(eligible),regressed_combinations=len(regressions),regressed_ids=regressions,
            boundary='Compare prior correct business behavior only; new shipping UI failures stay in new-feature metric, and all incomplete runs remain in overall denominator.')
    return dict(schema_version='quotation-reliability-v2-summary',metrics=metrics,
        limitations=['Combinations within each workflow are correlated; application-group count is the independent task denominator.',
                     'Synthetic configured cases grounded in public docs/requests, not real customers or real financial transactions.',
                     'One trial per arm/group/version. No statistical significance, generalization or token-cost claim from this sample.',
                     'Equal configured caps do not imply equal consumed tokens, same service latency or same number of internal native tool turns.'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directories',nargs='+',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result={d.name:summarize(d) for d in a.directories};a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
