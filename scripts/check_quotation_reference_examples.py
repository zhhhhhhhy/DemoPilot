"""Hand-calculated reference examples, separate from model evaluation trials."""
import sys
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend/src'))
from demopilot.quotation_contract import DEFAULTS,price
from demopilot.quotation_loop import write_json

EXAMPLES=[
 ('quantity_tiers',{'quantity':'5'},dict(subtotal='500.00',discount='50.00',tax='0.00',total='450.00')),
 ('customer_scope',{'quantity':'2','customer':'partner'},dict(total='190.00',discount='10.00')),
 ('validity_dates',{'date':'2026-04-01'},dict(total='100.00',discount='0.00')),
 ('validity_dates',{'date':'2026-03-31'},dict(total='75.00',discount='25.00')),
 ('compound_discounts',{'second_quantity':'1'},dict(subtotal='160.00',discount='44.80',total='115.20')),
 ('overlap_priority',{'quantity':'5','customer':'vip'},dict(total='450.00',discount='50.00')),
 ('mixed_threshold',{'quantity':'3','second_quantity':'2'},dict(subtotal='420.00',discount='42.00',total='378.00')),
 ('rate_override',{'quantity':'2','customer':'partner'},dict(subtotal='200.00',discount='24.00',total='176.00')),
 ('tax_inclusive',{},dict(subtotal='90.91',tax='9.09',total='100.00')),
 ('net_total_discount',{},dict(subtotal='100.00',discount='30.00',tax='7.00',total='77.00')),
 ('free_items',{'quantity':'3'},dict(total='300.00',free_quantity='1')),
 ('compound_discounts',{'second_quantity':'1','shipping':'express'},dict(total='165.20',freight='50.00')),
]

if __name__=='__main__':
    cfg=json.loads((ROOT/'testdata/qflow-01/contract-v2.json').read_text('utf-8'));rows=[]
    for kind,inputs,expected in EXAMPLES:
        actual=price(cfg,dict(DEFAULTS,profile=kind,**inputs))
        assert all(actual[k]==v for k,v in expected.items()),(kind,inputs,expected,actual)
        rows.append(dict(profile=kind,inputs=inputs,hand_calculated_expected=expected,actual=actual,passed=True))
    write_json(ROOT/'docs/quotation-reliability-v2/rule-calibration.json',dict(kind='literal-hand-calculated-examples-not-human-labelled-customer-data',rows=rows,count=len(rows)))
    print(json.dumps(dict(passed=len(rows),families=len({r['profile'] for r in rows}))))
