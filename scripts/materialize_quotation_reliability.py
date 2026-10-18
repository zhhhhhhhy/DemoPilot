"""Build100 source-backed combinations in10 distinct workflow application groups."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend/src'))
from demopilot.quotation_contract import compile_acceptance
DATASET=ROOT/'evaluation_sets/quotation-reliability-v2'
FAMILIES=[('single_manager','单级审批'),('two_stage','经理及财务两级审批'),('threshold','按报价金额分流审批'),('dual_manager','两个不同经理会签'),('rejection_reason','驳回原因及修改重提'),('cancel_amend','取消后修订重提'),('customer_owner','指定客户确认及越权拦截'),('expiry','有效期内客户确认'),('record_persistence','多报价隔离及刷新恢复'),('manual_override','手工价格与定价规则协同')]


def write_json(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def materialize():
    if (DATASET/'manifest.json').exists():
        raise RuntimeError('Dataset already frozen; refuse overwrite')
    originals=json.loads((ROOT/'evaluation_sets/quotation-intent-v1/cases.json').read_text('utf-8'))['cases']
    profiles={}
    pricing_sources={}
    for case in originals:
        private=json.loads((ROOT/'evaluation_sets/quotation-intent-v1'/case['private_acceptance']).read_text('utf-8'))
        profiles[case['family']]=private['rule_config']
        pricing_sources[case['family']]=case['source_urls']
    catalogue=json.loads((ROOT/'testdata/quotation-01/inputs.json').read_text('utf-8'))['fixtures']['catalogue']
    apps=[];cases=[]
    common_sources=['https://docs.frappe.io/erpnext/workflows','https://docs.frappe.io/erpnext/quotation','https://docs.frappe.io/erpnext/role-based-permissions']
    specific={'rejection_reason':'https://discuss.frappe.io/t/workflow-for-quotation-approval/34258','cancel_amend':'https://discuss.frappe.io/t/i-need-amend-button-when-cancel-the-document-for-quotation-doctype-when-in-workflow/144642','customer_owner':'https://discuss.frappe.io/t/client-approval-workflow-for-quotations/148297','manual_override':'https://discuss.frappe.io/t/how-to-override-pricing-rule-for-individual-quotation-items/146787'}
    for i,(family,title) in enumerate(FAMILIES,1):
        app_id=f'qflow-{i:02d}'
        contract=dict(schema_version='quotation-business-contract-v2',id=app_id,workflow=family,title=title,version=1,profiles=profiles,catalogue=catalogue,approval_threshold='1000.00',valid_until='2026-03-31',sources=common_sources+([specific[family]] if family in specific else []),provenance='Source-derived workflow patterns and pricing semantics; synthetic configured combinations, identities and money. No real customer records.')
        base=ROOT/'testdata'/app_id
        write_json(base/'contract-v1.json',contract)
        v2=dict(contract,version=2,shipping=dict(pickup='0',standard='20',express='50'))
        write_json(base/'contract-v2.json',v2)
        (base/'CONTRACT.md').write_text(CONTRACT,encoding='utf-8')
        for version,cfg in ((1,contract),(2,v2)):
            write_json(base/f'public-tests-v{version}.json',compile_acceptance(cfg,private=False))
            write_json(DATASET/'private'/f'{app_id}-v{version}.json',compile_acceptance(cfg,private=True))
        app=dict(id=app_id,workflow=family,title=title,split='development' if i<=3 else 'heldout',testdata_path=f'testdata/{app_id}',source_urls=contract['sources'])
        apps.append(app)
        for j,(profile,rule) in enumerate(profiles.items(),1):
            cases.append(dict(id=f'{app_id}-p{j:02d}',app_id=app_id,workflow=family,pricing_profile=profile,split=app['split'],source_urls=list(dict.fromkeys(app['source_urls']+pricing_sources[profile])),acceptance='Exact visible price + normal approval/acceptance + edit-invalidates-approval regression + invalid input/role preservation + workflow-specific sequence; v2 additionally shipping with regression of v1.',independence_group=app_id))
    write_json(DATASET/'apps.json',dict(apps=apps))
    write_json(DATASET/'cases.json',dict(cases=cases,combination_count=100,independent_application_groups=10,development_groups=3,heldout_groups=7))
    sources=list(dict.fromkeys(u for c in cases for u in c['source_urls']))
    write_json(DATASET/'sources.json',dict(source_urls=sources,reviewed_at='2026-10-16',scope='Public documentation and firsthand feature requests ground workflow patterns; all configured combinations are authored, not collected customer requirements. Historical forum issues are not assertions about present ERPNext bugs.'))
    files=[DATASET/'apps.json',DATASET/'cases.json',DATASET/'sources.json']+[p for a in apps for p in (ROOT/a['testdata_path']).iterdir()]+list((DATASET/'private').glob('*.json'))
    write_json(DATASET/'manifest.json',dict(files={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},combination_count=100,group_count=10))
    print(json.dumps(dict(apps=10,combinations=100,development=30,heldout=70)))


CONTRACT='''# Complete quotation goal and executable interface

Build a clean offline Chinese quotation application from scratch using vanilla index.html, app.js and styles.css. Implement ALL ten price profiles in contract-v1.json. A profile is selected per quote, never combined with other profiles. No dependencies or network. Product A=100, B=60, C=200; duplicate item rows aggregate before discounts. Minimum quantity first row1 second0, both integers; invalid input or wrong role cannot change any committed price, state, revision or history. No currency symbols in numeric output nodes, always two decimals with half-up monetary rounding at the final aggregate. Subtotal is the original catalogue/manual-rate extended amount BEFORE discounts, including the rate_override profile: represent that customer-specific rate difference as Discount, keeping original Subtotal. Only tax_inclusive instead displays the tax-exclusive net Subtotal rounded before computing the residual Tax. Total=Subtotal-Discount+Tax (plus v2 freight). Profiles have their full business configuration in JSON; do not load evaluator code or private vectors.

UI contract (these IDs, values and exact output codes are functional interoperability requirements):
- select #profile values are the ten profiles' keys. #product and #second-product values A/B/C. #customer standard/vip/partner. Number inputs #quantity=1, #second-quantity=0; date #date=2026-03-15. #calculate commits staged form edits.
- #record select Q1/Q2, initially Q1; independent records. select #role seller/manager/finance/customer initially seller; select #actor seller1/manager1/manager2/finance1/client1/intruder initially seller1. They are local role simulations, not production authentication.
- input #reason initially empty; input date #today=2026-03-15 is simulated current time, not quote date, and does not mutate a quote.
- buttons #submit, #approve, #reject, #accept, #cancel, #amend. Wrong, repeated or out-of-order actions must preserve committed state, revision, totals and history; disabled buttons are acceptable. UI message #error explains rejections. No actual submit to any external service.
- Outputs #subtotal, #discount, #tax, #total (exact two decimals), #free-quantity(integer), #state, #revision, #approved-revision, #history-count (integers). Start Draft, revision0, approved-revision -1, history-count0, base calculation for default fields/profile. State exact English codes: Draft/PendingManager/PendingFinance/Approved/Rejected/Accepted/Cancelled. Text labels elsewhere may be Chinese.

State semantics shared by all applications:
Calculate allowed only seller except Accepted/Cancelled. Committing ANY changed quote field (profile, item, quantity, customer, quote date, optional manual rate, v2 shipping) increments revision and history by1, resets to Draft, clears approvals (approved-revision=-1). Recalculating unchanged values is a no-op, must never accumulate discounts. Inputs are staged until Calculate, switching record restores that record's committed values.
Seller Submit from Draft/Rejected -> PendingManager, clears prior approvers/approval, increments history1. Manager approves PendingManager -> Approved unless the selected workflow says otherwise. Finance cannot replace manager. Approval sets approved-revision=current revision only when finally Approved. Manager can Reject PendingManager, finance can Reject PendingFinance -> Rejected, clears approvals; history+1. Customer Accept only Approved -> Accepted. Seller Cancel any state except Accepted/Cancelled -> Cancelled, clears approvals. Seller cannot edit Accepted/Cancelled. Other actions are rejected. Every successful state-changing action increments history exactly1; partial manager approval counts1. A rejected action adds nothing. Same manager actor cannot approve twice. Changing role, actor, reason, today or selected record never increments quote history.

The JSON workflow selects exactly one extra rule (other applications retain the shared behavior):
single_manager: shared manager flow.
two_stage: manager -> PendingFinance, finance -> Approved.
threshold: after manager approval, total >= approval_threshold -> PendingFinance else Approved; v2 includes shipping in total.
dual_manager: two DIFFERENT manager actors must approve; first remains PendingManager, second Approved; repeat by same actor is denied.
rejection_reason: reject requires a nonempty trimmed reason; correcting and resubmitting clears previous approval.
cancel_amend: only this workflow permits seller Amend from Cancelled -> Draft, revision+1 and history+1, retains quote fields, clears approvals.
customer_owner: Accept requires customer role AND actor client1; intruder denied.
expiry: Accept requires today <= valid_until, inclusive boundary. Moving simulated time alone does not change the approved quote.
record_persistence: Q1 and Q2 independently survive page reload (input values, price, state, history, revision and approvers); reload resets selected record/role/actor to Q1/seller/seller1. Other workflows require in-page record isolation but persistence is optional.
manual_override: add input #manual-rate, initially blank. Positive manual rate replaces A base unit rate before ANY profile calculations and persists through recalculation and other input changes. For rate_override profile, configured customer-specific rate still takes precedence when applicable. Nonpositive manual rates denied.

Subsequent version2 request (do not implement until requested): shipping select #shipping pickup/standard/express, default pickup, charges from contract-v2.json; add exactly once per whole quote AFTER pricing discount and tax. It participates in total, approval routing and change invalidation. Existing pickup results and ALL v1 functionality must remain correct. Use local JSON rule data embedded in your source or copy it into card-web; do not fetch outside card-web.

Self acceptance: run your own browser/script checks of all ten profiles, wrong-role action denial, repeated calculation, edit after approval, cross-record isolation and this workflow's extra rule. A read-only acceptance child may help; report actual commands/results in card/acceptance.md. The parent can independently execute public browser journeys using the external probe command supplied in the goal. Its same public checks are available to both comparison arms. Fix problems inside your call budget. No claims based solely on prose.
'''

if __name__=='__main__':materialize()
