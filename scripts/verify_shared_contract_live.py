"""Predeclared DEVELOPMENT-only field-dialogue and real Core/browser regression.

Never resumes a final campaign. No expected journeys are fed to intake. Facts
come from the already authored seller plan; final audits never request repairs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "scripts")]

from demopilot.business_fields import BusinessFacts  # noqa: E402
from demopilot.config import Settings  # noqa: E402
from demopilot.main import create_app  # noqa: E402
from demopilot.quotation_browser import audit_application, tree_hash  # noqa: E402
from demopilot.quotation_capabilities import BUSINESS_FIELDS, capability_identity  # noqa: E402
from demopilot.quotation_contract import compile_acceptance  # noqa: E402
from demopilot.quotation_loop import write_json  # noqa: E402
from demopilot.sales_contract import QuotePlan  # noqa: E402
from demopilot.sales_core import SalesCoreManager  # noqa: E402
from run_sales_benchmark_pilot import code_manifest, semantics, trace_cost, wait_idle  # noqa: E402
from sales_benchmark_data import DATASET, read, sha  # noqa: E402

# Capability coverage declared before any model output; no special production
# branch uses these IDs. Two tasks per complexity, two partial conversations.
SCENARIOS = [
    dict(id="sales-v3-002", core=True, partial=False,
         brief="想要一个下单前给客户看的耗材报价页。多拿几件要便宜些，具体档位请问我，别自己定。主管点头后客户才能同意。"),
    dict(id="sales-v3-012", core=False, partial=True,
         brief="帮我做展会期间的报价：同一个东西只有特定日期才便宜。先走主管签字，再由客户确认；起止日、折让多少请向我核实。"),
    dict(id="sales-v3-062", core=True, partial=False,
         brief="做一个批量采购报价，被主管打回时必须写明为什么，改好可以再送审，最后客户确认。数量越多折让越多，档位请向我确认。"),
    dict(id="sales-v3-127", core=False, partial=True,
         brief="销售报价里，一类客户拿到的是事先谈定的单件金额。另一个需求是业务员能手填A的售价，重算别丢掉，填零或负数不行，改动要让主管重新看再由客户确认。请向我确认具体客户及约定金额。"),
    dict(id="sales-v3-172", core=True, partial=False,
         brief="需要一个有活动日期的报价，过了另一个客户确认期限就不能接受。活动日期和确认期限各管各的，要能模拟今天是哪天。主管先批再给客户，还需要配送收费；具体日期、折让及配送金额请向我核实。"),
    dict(id="sales-v3-192", core=True, partial=False,
         brief="做个把已含税价格拆成未税额和税额的报价演示，别再往上加一次税。两份单子的内容和签批进度在网页重新打开后都得回来，默认回第一份和销售身份。主管批完客户确认，还要配送，税率和配送单价请问我。"),
]
NEGATIVES = [
    dict(id="negative-conflict", brief="只做离线报价，A叫基础包单价100，B叫扩展包单价60，C叫专业包单价200。A满3件减10%，经理审批后客户确认，不要配送。同时另一张有效价目表说A单价120，两张表同样有效，我还不能确认用哪张，不能任选或取平均。",
         answer="两张价目表仍然同时有效，A是100还是120我尚未决定，先别生成。", expected="needs_details"),
    dict(id="negative-unsupported", brief="我要真实微信和支付宝收款，把到账结果写进公司生产财务系统，并连接生产身份认证。必须真实扣款和回写，离线模拟不接受。", expected="unsupported"),
]


def source_manifest():
    return {**code_manifest(), Path(__file__).relative_to(ROOT).as_posix(): sha(Path(__file__))}


def predeclare(output, readiness, only=None, inject_status_read=False):
    if output.exists():
        raise RuntimeError("Fresh output required; never replace or silently resume a run")
    cases = {c["id"]: c for c in read(DATASET / "cases.json")["cases"] if c["split"] == "development"}
    split = read(DATASET / "split.json")
    ids = [s["id"] for s in SCENARIOS]
    if len(set(ids)) != 6 or not set(ids).issubset(split["development"]) or set(ids) & (set(split["heldout"]) | set(split["validation"])):
        raise ValueError("Only six predeclared development cases are allowed")
    available = {s["id"] for s in SCENARIOS + NEGATIVES}
    if only and (not set(only).issubset(available) or len(set(only)) != len(only)):
        raise ValueError("Selection is limited to the already predeclared development controls")
    selected = set(only or available)
    ready = read(readiness)
    if (ready.get("status") != "passed" or ready.get("code_sha256") != code_manifest()
        or ready.get("model") != "gpt-6.1-sol" or ready.get("reasoning_effort") != "medium"
        or not ready.get("browser_preflight", {}).get("passed")
        or not all(r.get("passed") for r in ready.get("rows", []))):
        raise RuntimeError("Require current real CLI read/write and Chromium readiness")
    for relative, digest in ready["trace_sha256"].items():
        if sha(Path(readiness).parent / relative) != digest:
            raise RuntimeError("Readiness trace changed")
    fixtures = [DATASET / "cases.json", DATASET / "split.json"]
    for identifier in ids:
        data = ROOT / cases[identifier]["testdata_path"]
        contract_path = data / "contract.json"
        contract = read(contract_path)
        fixtures.append(contract_path)
        for private, path in ((False, data / "public-tests.json"), (True, DATASET / "private" / f"{identifier}.json")):
            if compile_acceptance(contract, private=private) != read(path):
                raise RuntimeError("Existing expected actions/results drifted; do not run")
            fixtures.append(path)
    context = dict(created_at=datetime.now(UTC).isoformat(), kind="development-mechanism-regression-not-final-score",
                   scenarios=[s for s in SCENARIOS if s["id"] in selected],
                   negatives=[s for s in NEGATIVES if s["id"] in selected],
                   inject_status_read=inject_status_read, model="gpt-6.1-sol", reasoning_effort="medium",
                   cli_timeout_seconds=300, intake_call_cap=3, core_call_cap=3, max_parallel=2,
                   capabilities=capability_identity(), code_sha256=source_manifest(),
                   input_sha256={p.relative_to(ROOT).as_posix(): sha(p) for p in fixtures},
                   readiness=str(readiness), readiness_sha256=sha(Path(readiness)),
                   policy="Same existing seller facts/standards, paraphrased brief; partial reply is predeclared. Correct typed facts are not a model answer oracle. No final cases or new pass thresholds.")
    output.mkdir(parents=True)
    write_json(output / "context.json", context)
    return cases, context


def verify(context):
    if source_manifest() != context["code_sha256"] or any(sha(ROOT / p) != h for p, h in context["input_sha256"].items()):
        raise RuntimeError("Frozen development source/input changed; stop new calls")


def seller_reply(store, requests, partial):
    reply = store.reply(requests)
    if partial:
        # Deliberately provide only part of a compound answer, without changing
        # its content. Model must retain these facts and ask for the rest.
        facts = []
        for fact in reply["facts"]:
            value, field = fact["value"], fact["field_id"]
            if isinstance(value, dict) and fact["status"] == "known":
                child_ids = [field + "." + key for key in value if field + "." + key in BUSINESS_FIELDS]
                facts.extend(store.reply([dict(question="部分业务事实", field_ids=[child], reason="missing")])["facts"][0] for child in child_ids)
            else:
                facts.append(fact)
        reply["facts"] = facts[:1]
    return reply


class StatusReadFault:
    """Optional detector calibration: lose one GET after actual Core starts.

    All requests reach the real HTTP service. Only observation fails; the
    generated code, model inputs, server and non-idempotent requests are intact.
    """
    def __init__(self, client, row, target, enabled):
        self.client, self.row, self.target, self.enabled = client, row, target, enabled

    async def get(self, url):
        response = await self.client.get(url)
        if self.enabled and not self.row["injected_status_reads"] and response.status_code == 200:
            session = response.json()
            if session["status"] == "building":
                self.row["injected_status_reads"].append(dict(session_id=session["id"], status=session["status"], iteration=session["iteration"]))
                write_json(self.target / "status-read-control.json", dict(injected=self.row["injected_status_reads"]))
                raise httpx.RemoteProtocolError("Controlled loss of one status GET after real Core started")
        return response

    async def post(self, *args, **kwargs):
        return await self.client.post(*args, **kwargs)


async def run(args):
    output = args.output.resolve()
    cases, context = predeclare(output, args.readiness.resolve(), args.only, args.inject_status_read)
    planned = len(context["scenarios"]) + len(context["negatives"])
    settings = Settings(data_dir=output, codex_model=context["model"], codex_reasoning_effort="medium", codex_timeout_seconds=300)
    manager = SalesCoreManager(settings)
    manager.slots = asyncio.Semaphore(2)
    app = create_app(settings, sales_core=manager)
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False))
    service = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if service.done():
            await service
            raise RuntimeError("Service failed to start")
        await asyncio.sleep(.1)
    rows = []
    slots = asyncio.Semaphore(2)
    started = time.monotonic()

    async def one(spec, client):
        async with slots:
            verify(context)
            identifier = spec["id"]
            target = output / "case-results" / identifier
            target.mkdir(parents=True, exist_ok=False)
            row = dict(id=identifier, core_requested=spec.get("core", False), question_rounds=[], passed=False, stage="intake",
                       status_read_retries=[], injected_status_reads=[])
            poller = StatusReadFault(client, row, target, args.inject_status_read and spec.get("core", False))

            def read_retry(event):
                row["status_read_retries"].append(event)
                write_json(target / "status-read-retries.json", row["status_read_retries"])

            async def observe():
                return await wait_idle(poller, session_id, deadline, on_read_retry=read_retry)
            session_id = None
            begin = time.monotonic()
            deadline = begin + 2100
            try:
                case = cases.get(identifier)
                brief = spec["brief"]
                if case:
                    brief += "\n" + next(a["answer"] for a in case["seller_answers"] if a["topic"] == "catalogue")
                    store = BusinessFacts(case["expected_plan"], {a["topic"]: a["answer"] for a in case["seller_answers"]})
                row["brief"] = brief
                response = await client.post("/api/sales-core/sessions", json=dict(brief=brief, request_key=identifier))
                response.raise_for_status()
                session_id = response.json()["id"]
                row["session_id"] = session_id
                session = await observe()
                for turn in range(2):
                    if session["status"] != "needs_details":
                        break
                    row["question_rounds"].append(dict(questions=session["questions"], clarifications=session["clarifications"]))
                    if case:
                        reply = seller_reply(store, session["clarifications"], spec["partial"] and turn == 0)
                        answer = json.dumps(reply, ensure_ascii=False) + "\n" + case["common_conventions"]
                        if spec["partial"] and turn == 0:
                            answer += "\n本轮只先回答以上字段，其余仍请追问，不能猜测。"
                        row["question_rounds"][-1]["field_reply"] = reply
                    elif turn == 0 and "answer" in spec:
                        answer = spec["answer"]
                    else:
                        break
                    row["question_rounds"][-1]["answer"] = answer
                    response = await client.post(f"/api/sales-core/sessions/{session_id}/answers", json=dict(answer=answer))
                    response.raise_for_status()
                    session = await observe()
                row["intake_status"] = session["status"]
                row["failure_category"] = session.get("failure_category")
                if not case:
                    row["passed"] = session["status"] == spec["expected"] and session["draft"] is None and not session["demo_url"]
                    if identifier == "negative-conflict":
                        row["passed"] &= any(c["reason"] == "conflict" and any(f.startswith("catalogue") for f in c["field_ids"]) for c in session["clarifications"])
                    row["stage"] = "negative_control"
                elif session["status"] == "ready":
                    actual = QuotePlan.model_validate(session["draft"]).model_dump(mode="json")
                    row["intent_match"] = semantics(actual) == semantics(case["expected_plan"])
                    write_json(target / "confirmation.json", dict(match=row["intent_match"], actual=actual, expected=case["expected_plan"]))
                    if row["intent_match"]:
                        row["passed"] = True
                        if spec["core"]:
                            row.update(passed=False, stage="core")
                            response = await client.post(f"/api/sales-core/sessions/{session_id}/confirm", json=dict(draft_hash=session["draft_hash"]))
                            response.raise_for_status()
                            session = await observe()
                            result = output / "sales-core/sessions" / session_id / f"revision-{session['revision']}" / "result.json"
                            for _ in range(30):
                                if result.exists() or session["status"] != "published":
                                    break
                                await asyncio.sleep(.1)
                            if result.exists():
                                terminal = read(result)
                                row["core_calls"] = terminal["cli_calls"]
                                row["internal_repair_rounds"] = terminal["internal_repair_rounds"]
                            row["demo_url"] = session["demo_url"]
                row["status"] = session["status"]
                row["error"] = session.get("error")
                write_json(target / "session-terminal.json", session)
            except Exception as exc:
                row.update(error=f"{type(exc).__name__}: {exc}", status="failed")
                if session_id:
                    await client.post(f"/api/sales-core/sessions/{session_id}/cancel")
            row["elapsed_seconds"] = round(time.monotonic() - begin, 2)
            if session_id:
                row["cost"] = trace_cost(output / "sales-core/sessions" / session_id)
            rows.append(row)
            write_json(target / "terminal.json", row)
            write_json(output / "progress.json", dict(phase="generation", terminal=len(rows), rows=rows))
            print(json.dumps(dict(event="terminal", id=identifier, status=row["status"], stage=row["stage"], error=row.get("error")), ensure_ascii=False), flush=True)

    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", trust_env=False, timeout=30) as client:
            await asyncio.gather(*(one(spec, client) for spec in context["scenarios"] + context["negatives"]))
            write_json(output / "terminal-results.json", dict(all_terminal=len(rows) == planned, rows=rows))
            verify(context)
            for row in rows:
                if not row["core_requested"]:
                    continue
                target = output / "case-results" / row["id"]
                if row["status"] != "published":
                    row["independent_check"] = dict(status="not_run_no_published_app")
                    continue
                session = manager.public(row["session_id"])
                artifact = output / "sales-core/registry/artifacts" / session["versions"][-1]["artifact"]
                before = tree_hash(artifact)
                contract = QuotePlan.model_validate(cases[row["id"]]["expected_plan"]).contract(row["session_id"])
                audit = await audit_application(artifact, contract, target / "independent-final", private=True)
                row["independent_check"] = {key: audit[key] for key in ("status", "planned_journeys", "executed_journeys", "passed_journeys", "issues")}
                row["source_unchanged"] = tree_hash(artifact) == before
                exact = []
                for name in ("index.html", "app.js", "styles.css"):
                    response = await client.get(row["demo_url"].rsplit("/", 1)[0] + "/" + name)
                    if response.status_code == 200 and response.content == (artifact / name).read_bytes():
                        exact.append(name)
                row["exact_served_assets"] = exact
                row["passed"] = audit["status"] == "passed" and row["source_unchanged"] and len(exact) == 3
                if args.inject_status_read:
                    row["passed"] &= len(row["injected_status_reads"]) == 1 and len(row["status_read_retries"]) >= 1
                write_json(target / "scored.json", row)
                print(json.dumps(dict(event="scored", id=row["id"], passed=row["passed"], browser=row["independent_check"])), flush=True)
            cost = dict(cli_process_calls=sum(r.get("cost", {}).get("cli_process_calls", 0) for r in rows),
                        intake_calls=sum(r.get("cost", {}).get("intake_calls", 0) for r in rows),
                        core_calls=sum(r.get("cost", {}).get("core_calls", 0) for r in rows),
                        reported_root_tokens={k: sum(r.get("cost", {}).get("reported_root_tokens", {}).get(k, 0) for r in rows) for k in ("input_tokens", "cached_input_tokens", "output_tokens")},
                        calls_with_reported_usage=sum(r.get("cost", {}).get("calls_with_reported_usage", 0) for r in rows),
                        monetary_cost=None)
            result = dict(passed=sum(r["passed"] for r in rows), planned=planned, positive_intent=sum(r.get("intent_match", False) for r in rows),
                          full_delivery=sum(r["passed"] and r["core_requested"] for r in rows), negative_controls=sum(r["passed"] and r["stage"] == "negative_control" for r in rows),
                          elapsed_seconds=round(time.monotonic() - started, 2), cost=cost, rows=rows,
                          final_cases_executed=0, source_unchanged=source_manifest() == context["code_sha256"])
            write_json(output / "results.json", result)
            write_json(output / "progress.json", dict(phase="completed", passed=result["passed"], planned=planned))
            print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False), flush=True)
            return result["passed"] == planned
    finally:
        server.should_exit = True
        await service


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--only", nargs="+", help="Subset of predeclared development controls, recorded separately")
    parser.add_argument("--inject-status-read", action="store_true", help="Calibrate read recovery once during each actual Core build")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(run(args)) else 1)
