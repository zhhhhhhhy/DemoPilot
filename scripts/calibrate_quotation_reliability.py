"""Controlled checker faults on a copied real CLI artifact; not model scores."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend/src'))
from demopilot.quotation_browser import audit_application,tree_hash
from demopilot.quotation_loop import write_json

MUTATIONS={
 'wrong_total':"window.addEventListener('click',()=>{document.getElementById('total').textContent='0.00'})",
 'missing_discount':"window.addEventListener('click',()=>{document.getElementById('discount').textContent='0.00'})",
 'wrong_tax':"window.addEventListener('click',()=>{document.getElementById('tax').textContent='0.00'})",
 'history_double_write':"window.addEventListener('click',()=>{const e=document.getElementById('history-count');e.textContent=String(Number(e.textContent)+1)})",
 'stale_approval':"window.addEventListener('click',e=>{if(e.target.id==='calculate'){document.getElementById('state').textContent='Approved';document.getElementById('approved-revision').textContent=document.getElementById('revision').textContent}})",
 'cross_record_leak':"window.addEventListener('change',e=>{if(e.target.id==='record')document.getElementById('total').textContent='0.00'})",
 'freight_twice':"window.addEventListener('click',e=>{if(e.target.id==='calculate'){const t=document.getElementById('total');t.textContent=(Number(t.textContent)+Number(document.getElementById('freight').textContent)).toFixed(2)}})",
 'hidden_fake_output':"document.getElementById('total').style.display='none'",
}


async def main(source,out,*,private=True):
    if (out/'summary.json').exists():raise RuntimeError('Refuse calibration overwrite')
    original=tree_hash(source)
    contract=json.loads((ROOT/'testdata/qflow-01/contract-v2.json').read_text('utf-8'))
    contract['profiles']={key:contract['profiles'][key] for key in ('quantity_tiers','tax_inclusive')}
    rows=[]
    for name,patch in [('valid_control',None),*MUTATIONS.items()]:
        target=out/name/'app';target.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(source,target)
        if patch:
            path=target/'app.js';path.write_text(path.read_text('utf-8')+'\n;'+patch+';\n',encoding='utf-8')
        report=await audit_application(target,contract,out/name/'evidence',private=private)
        expected='passed' if patch is None else 'failed'
        row=dict(name=name,expected=expected,actual=report['status'],correct=expected==report['status'],planned=report['planned_journeys'],executed=report['executed_journeys'],passed=report['passed_journeys'])
        rows.append(row);write_json(out/'progress.json',dict(rows=rows));print(json.dumps(row),flush=True)
    summary=dict(kind='controlled-checker-calibration-not-cli-accuracy',vector_mode='private' if private else 'public-prepublication',source_cli_artifact=str(source),source_sha256=original,source_unchanged=tree_hash(source)==original,
                 valid_controls=1,valid_controls_accepted=sum(r['name']=='valid_control' and r['actual']=='passed' for r in rows),
                 seeded_fault_classes=len(MUTATIONS),seeded_faults_rejected=sum(r['name']!='valid_control' and r['actual']=='failed' for r in rows),
                 all_expected=sum(r['correct'] for r in rows)==len(rows),rows=rows,
                 boundary='Synthetic seeded corruptions on copied development artifact; not real independent requirements, not model trials or estimated real-world detection rate.')
    write_json(out/'summary.json',summary)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--public',action='store_true');a=p.parse_args()
    asyncio.run(main(a.source.resolve(),a.output.resolve(),private=not a.public))
