"""Bounded real-product B-arm pilot; refuses every ID outside the sealed20.

Same production HTTP API, interview, Core and release registry. The scripted
seller releases facts only in response to matching actual questions. Independent
final checks run after ALL cases are terminal and never feed back to Builder.
"""

from __future__ import annotations

# ruff: noqa: E402 -- these repository scripts load the local backend explicitly.
import argparse
import asyncio
import hashlib
import json
import re
import socket
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from sales_benchmark_data import DATASET, read, sha, validate

from demopilot.config import Settings
from demopilot.main import create_app
from demopilot.quotation_browser import audit_application, tree_hash
from demopilot.quotation_loop import write_json
from demopilot.sales_contract import QuotePlan
from demopilot.sales_core import SalesCoreManager


def semantics(value):
    from decimal import Decimal, InvalidOperation

    if isinstance(value, dict):
        return {k: semantics(v) for k, v in value.items() if k != "title"}
    if isinstance(value, list):
        # Product order is not a business difference; identifiers and names are.
        if value and all(isinstance(v, dict) and "id" in v for v in value):
            value = sorted(value, key=lambda v: v["id"])
        return [semantics(v) for v in value]
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        try:
            return str(Decimal(str(value)).normalize())
        except InvalidOperation:
            return value
    return value


def answers_for(questions, case, released):
    text = " ".join(questions)
    all_requested = any(
        x in text for x in ["完整业务规则", "全部规则", "所有规则", "完整需求", "所有业务信息"]
    )
    selected = []
    common_manager = {
        "single_manager",
        "rejection_reason",
        "cancel_amend",
        "expiry",
        "record_persistence",
        "manual_override",
        "customer_owner",
    }
    for answer in case["seller_answers"]:
        matched = all_requested or any(x.lower() in text.lower() for x in answer["aliases"])
        if not matched:
            continue
        item = dict(answer)
        if (
            item["topic"] == "workflow"
            and case.get("expected_plan", {}).get("workflow") in common_manager
        ):
            # Deliver the existing current-case public CONTRACT.md manager flow;
            # no new policy, numbers or private acceptance answer is invented.
            item["answer"] = (
                "补齐本场景公共接口已定义的审批起点与终点：销售提交，经理审批，最后客户确认。"
                + item["answer"]
            )
            if (
                item["topic"] in released
                and any(x in text for x in ("谁", "审批人", "顺序", "角色"))
                and "workflow_common" not in released
            ):
                item["topic"] = "workflow_common"
        if item["topic"] not in released:
            selected.append(item)
    return selected


def code_manifest():
    files = [
        *sorted((ROOT / "backend/src/demopilot").rglob("*.py")),
        ROOT / "scripts/quotation_business_probe.py",
        Path(__file__),
        ROOT / "scripts/sales_benchmark_data.py",
        ROOT / "scripts/run_with_awake.py",
    ]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in files}


def freeze(output, args):
    if (output / "context.json").exists():
        raise RuntimeError("Use a fresh cohort; never overwrite/relaunch an old pilot")
    validation = validate()
    split = read(DATASET / "split.json")
    pilot = read(DATASET / "pilot-20.json")["case_ids"]
    assert (
        len(pilot) == 20
        and set(pilot).issubset(split["development"])
        and not set(pilot) & set(split["heldout"])
    )
    original_pilot = list(pilot)
    regression = getattr(args, "regression_ids", None)
    if regression:
        if (
            not 1 <= len(regression) <= 3
            or len(set(regression)) != len(regression)
            or not set(regression).issubset(original_pilot)
        ):
            raise ValueError(
                "Regression permits at most3 distinct IDs from the original20development cases"
            )
        pilot = list(regression)
    context = dict(
        schema_version="sales-benchmark-v3-product-pilot2",
        created_at=datetime.now(UTC).isoformat(),
        pilot_ids=pilot,
        original_sealed_pilot_ids=original_pilot,
        targeted_regression=bool(regression),
        change_boundary="General workflow capability context and complete delivery of existing shared approval semantics; original dataset/gold unchanged. Two integration fixes together, not isolated prompt attribution.",
        dataset_manifest_sha256=sha(DATASET / "manifest.json"),
        code_sha256=code_manifest(),
        model=args.model,
        reasoning_effort="medium",
        cli_timeout_seconds=300,
        core_call_cap=3,
        intake_call_cap=3,
        max_parallel=2,
        case_deadline_seconds=2100,
        arm="current-product-clarify-only",
        information_policy="Scripted seller releases only facts matched by actual questions; ready draft must match seller contract before scripted confirmation.",
        denominator="All20preselected development tasks, including pre-Core and infrastructure failures. Intermediate Core repairs are separate.",
        independent_scoring="After all terminal outcomes, fresh Chromium against frozen expected seller contract; no final-score feedback or manual app edits.",
        holdout_policy="100heldout remain unused for model execution/debugging; static construction validation and hash checks are allowed.",
        cost_boundary="Configured caps are equal ceilings, not forced consumption. Actual root CLI token reports/counts are retained; billing and exhaustive native-child cost are unavailable.",
        construction_validation=validation,
    )
    write_json(output / "context.json", context)
    return context


def verify_frozen(output):
    c = read(output / "context.json")
    if c["dataset_manifest_sha256"] != sha(DATASET / "manifest.json"):
        raise RuntimeError("Dataset manifest changed")
    if c["code_sha256"] != code_manifest():
        raise RuntimeError("Frozen pilot source changed; stop model launches")
    return c


async def wait_idle(client, identifier, deadline):
    while time.monotonic() < deadline:
        response = await client.get(f"/api/sales-core/sessions/{identifier}")
        response.raise_for_status()
        s = response.json()
        if not s["active"]:
            return s
        await asyncio.sleep(2)
    await client.post(f"/api/sales-core/sessions/{identifier}/cancel")
    raise TimeoutError("Whole-task deadline reached; cancelled through production API")


def trace_cost(directory):
    calls = []
    flags = []
    for path in sorted(directory.rglob("stdout.jsonl")):
        usages = []
        commands = {}
        event_types = []
        for line in path.read_text("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            event_types.append(event.get("type"))
            if isinstance(event.get("usage"), dict):
                usages.append(event["usage"])
            item = event.get("item", {})
            if item.get("type") == "command_execution":
                commands[item.get("id", str(len(commands)))] = item.get("command", "")
        totals = {
            k: sum(u.get(k, 0) for u in usages)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        }
        calls.append(
            dict(
                trace=path.relative_to(directory).as_posix(),
                reported_usage=totals if usages else None,
                completed="turn.completed" in event_types,
                commands=len(commands),
            )
        )
        for command in commands.values():
            normalized = command.replace("\\", "/")
            if re.search(
                r"/private/|sales_benchmark_data\.py|sales-benchmark-v3/(?:cases|split|manifest)\.json|backend/src/demopilot/quotation_contract\.py|demopilot\.quotation_contract",
                normalized,
                re.I,
            ):
                flags.append(
                    dict(
                        trace=path.relative_to(directory).as_posix(),
                        reason="possible evaluator/private/dataset access; manually review retained raw command",
                        command_sha256=hashlib.sha256(command.encode()).hexdigest(),
                    )
                )
    usage = [c["reported_usage"] for c in calls if c["reported_usage"] is not None]
    return dict(
        cli_process_calls=len(calls),
        intake_calls=sum(c["trace"].startswith("intent/") for c in calls),
        core_calls=sum("/cli/" in c["trace"] for c in calls),
        calls_with_reported_usage=len(usage),
        calls_without_reported_usage=len(calls) - len(usage),
        reported_root_tokens={
            k: sum(c[k] for c in usage)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        monetary_cost=None,
        billing="ChatGPT CLI login provides no per-task bill; tokens/calls/seconds are proxies, not money.",
        observed_input_flags=flags,
        read_isolation="Returned root command events only; native child/OS reads not exhaustively observable.",
        calls=calls,
    )


async def run_cases(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    frozen = freeze(output, args)
    cases_by_id = {
        c["id"]: c for c in read(DATASET / "cases.json")["cases"] if c["id"] in frozen["pilot_ids"]
    }
    settings = Settings(
        data_dir=output,
        codex_model=frozen["model"],
        codex_reasoning_effort="medium",
        codex_timeout_seconds=300,
    )
    manager = SalesCoreManager(settings)
    manager.slots = asyncio.Semaphore(
        2
    )  # Explicit isolated pilot config; production default remains1.
    app = create_app(settings, sales_core=manager)
    app.mount(
        "/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="isolated-pilot-ui"
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    )
    service = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if service.done():
            await service
            raise RuntimeError("Acceptance service did not start")
        await asyncio.sleep(0.1)
    write_json(
        output / "service.json",
        dict(
            url=f"http://127.0.0.1:{args.port}",
            isolated=True,
            started_at=datetime.now(UTC).isoformat(),
        ),
    )
    rows = []
    slots = asyncio.Semaphore(2)

    async def one(identifier, client):
        async with slots:
            verify_frozen(output)
            if (
                identifier not in frozen["pilot_ids"]
                or cases_by_id[identifier]["split"] != "development"
            ):
                raise RuntimeError("Forbidden non-pilot case")
            case = cases_by_id[identifier]
            started = time.monotonic()
            deadline = started + frozen["case_deadline_seconds"]
            session_id = None
            target = output / "case-results" / identifier
            target.mkdir(parents=True, exist_ok=False)
            row = dict(
                case_id=identifier,
                family=case["family"],
                difficulty=case["difficulty"],
                status="running",
                stage="intake",
                session_id=None,
                confirmation_semantics_match=False,
                question_rounds=[],
                final_functional_pass=False,
                delivery_pass=False,
            )
            write_json(
                target / "launch.json",
                dict(
                    case_id=identifier,
                    started_at=datetime.now(UTC).isoformat(),
                    model=frozen["model"],
                ),
            )
            try:
                response = await client.post(
                    "/api/sales-core/sessions",
                    json=dict(brief=case["raw_sales_brief"], request_key="pilot-" + identifier),
                )
                response.raise_for_status()
                s = response.json()
                session_id = s["id"]
                row["session_id"] = session_id
                write_json(
                    target / "session-link.json", dict(session_id=session_id, case_id=identifier)
                )
                released = {
                    a["topic"]
                    for a in case["seller_answers"]
                    if a["answer"] in case["raw_sales_brief"]
                }
                s = await wait_idle(client, session_id, deadline)
                for _ in range(frozen["intake_call_cap"] - 1):
                    if s["status"] != "needs_details":
                        break
                    selected = answers_for(s["questions"], case, released)
                    answer = "\n".join(a["answer"] for a in selected)
                    if not answer:
                        answer = "请具体询问仍缺少的价格、优惠、审批或配送信息；不要猜测。"
                    else:
                        answer += "\n" + case["common_conventions"]
                    row["question_rounds"].append(
                        dict(
                            questions=s["questions"],
                            released_topics=[a["topic"] for a in selected],
                            answer=answer,
                        )
                    )
                    released.update(a["topic"] for a in selected)
                    response = await client.post(
                        f"/api/sales-core/sessions/{session_id}/answers", json=dict(answer=answer)
                    )
                    response.raise_for_status()
                    s = await wait_idle(client, session_id, deadline)
                if s["status"] != "ready":
                    row.update(
                        status="failed",
                        stage="intake",
                        failure_reason="Intake not ready within declared3calls",
                        session_status=s["status"],
                        remaining_questions=s["questions"],
                    )
                else:
                    actual = QuotePlan.model_validate(s["draft"]).model_dump(mode="json")
                    match = semantics(actual) == semantics(case["expected_plan"])
                    row["confirmation_semantics_match"] = match
                    write_json(
                        target / "confirmation.json",
                        dict(match=match, actual=actual, expected=case["expected_plan"]),
                    )
                    if not match:
                        row.update(
                            status="failed",
                            stage="intent_contract",
                            failure_reason="User-confirmation boundary: model proposal differs from actual seller facts; no automatic rule overwrite or Core launch",
                        )
                    else:
                        row["stage"] = "core"
                        response = await client.post(
                            f"/api/sales-core/sessions/{session_id}/confirm",
                            json=dict(draft_hash=s["draft_hash"]),
                        )
                        response.raise_for_status()
                        s = await wait_idle(client, session_id, deadline)
                        # The publish event precedes terminal result file by milliseconds.
                        result_file = (
                            output
                            / "sales-core/sessions"
                            / session_id
                            / f"revision-{s['revision']}"
                            / "result.json"
                        )
                        for _ in range(50):
                            if result_file.exists() or s["status"] != "published":
                                break
                            await asyncio.sleep(0.1)
                        if result_file.exists():
                            result = read(result_file)
                            row.update(
                                core_status=result["status"],
                                core_calls=result["cli_calls"],
                                internal_core_repairs=result["internal_repair_rounds"],
                                iterations=[
                                    dict(
                                        round=r["iteration"] + 1,
                                        cli_error=r["cli_error"],
                                        engineering=r["engineering"],
                                        check_status=r["check"]["status"],
                                        issues=r["check"].get("issues", [])[:6],
                                    )
                                    for r in result["iterations"]
                                ],
                            )
                        row.update(
                            status="published" if s["status"] == "published" else "failed",
                            stage="publication" if s["status"] == "published" else "core",
                            session_status=s["status"],
                            demo_url=s["demo_url"],
                        )
                        if s["status"] != "published":
                            row["failure_reason"] = s.get("error") or s["stage"]
                write_json(target / "session-terminal.json", s)
            except Exception as exc:
                row.update(
                    status="failed",
                    stage=row.get("stage", "infrastructure"),
                    failure_reason=type(exc).__name__ + ": " + str(exc),
                )
                if session_id:
                    try:
                        await client.post(f"/api/sales-core/sessions/{session_id}/cancel")
                    except Exception:
                        pass
            row["elapsed_seconds"] = round(time.monotonic() - started, 2)
            if session_id:
                row["cost"] = trace_cost(output / "sales-core/sessions" / session_id)
            write_json(target / "terminal.json", row)
            rows.append(row)
            write_json(
                output / "progress.json",
                dict(
                    phase="generation",
                    planned=len(frozen["pilot_ids"]),
                    terminal=len(rows),
                    rows=rows,
                ),
            )
            print(
                json.dumps(
                    dict(
                        event="case_terminal",
                        case_id=identifier,
                        status=row["status"],
                        stage=row["stage"],
                        elapsed=row["elapsed_seconds"],
                        calls=row.get("cost", {}).get("cli_process_calls"),
                    ),
                    ensure_ascii=False,
                ),
                flush=True,
            )

    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{args.port}", trust_env=False, timeout=30
        ) as client:
            await asyncio.gather(*(one(i, client) for i in frozen["pilot_ids"]))
            write_json(
                output / "terminal-results.json",
                dict(
                    rows=rows,
                    planned=len(frozen["pilot_ids"]),
                    all_terminal=len(rows) == len(frozen["pilot_ids"]),
                ),
            )
            # Do not score/repair a selected early output while others still build.
            verify_frozen(output)
            for row in rows:
                case = cases_by_id[row["case_id"]]
                target = output / "case-results" / row["case_id"]
                contract = QuotePlan.model_validate(case["expected_plan"]).contract(
                    row["session_id"] or case["id"]
                )
                artifact = None
                if row["session_id"]:
                    session = read(
                        output / "sales-core/sessions" / row["session_id"] / "session.json"
                    )
                    if session["status"] == "published":
                        artifact = (
                            output
                            / "sales-core/registry/artifacts"
                            / session["versions"][-1]["artifact"]
                        )
                    else:
                        candidate = (
                            output
                            / "sales-core/sessions"
                            / row["session_id"]
                            / f"revision-{session['revision']}"
                            / "workspace/card-web"
                        )
                        if (candidate / "index.html").exists():
                            artifact = candidate
                if artifact:
                    before = tree_hash(artifact)
                    audit = await audit_application(
                        artifact, contract, target / "independent-final", private=True
                    )
                    row["final_functional_pass"] = audit[
                        "status"
                    ] == "passed" and before == tree_hash(artifact)
                    row["independent_check"] = dict(
                        status=audit["status"],
                        planned=audit["planned_journeys"],
                        executed=audit["executed_journeys"],
                        passed=audit["passed_journeys"],
                        issues=audit["issues"][:8],
                        source_unchanged=before == tree_hash(artifact),
                    )
                    if row["status"] == "published":
                        root_url = row["demo_url"].rsplit("/", 1)[0]
                        exact = []
                        for name in ["index.html", "app.js", "styles.css"]:
                            response = await client.get(root_url + "/" + name)
                            if (
                                response.status_code == 200
                                and response.content == (artifact / name).read_bytes()
                            ):
                                exact.append(name)
                        row["exact_served_assets"] = exact
                    row["delivery_pass"] = (
                        row["status"] == "published"
                        and row["final_functional_pass"]
                        and len(row.get("exact_served_assets", [])) == 3
                    )
                else:
                    row["independent_check"] = dict(
                        status="not_run_no_generated_app",
                        planned=len(read(DATASET / "private" / f"{case['id']}.json")["journeys"]),
                        executed=0,
                        passed=0,
                    )
                write_json(target / "scored.json", row)
                print(
                    json.dumps(
                        dict(
                            event="case_scored",
                            case_id=row["case_id"],
                            delivery_pass=row["delivery_pass"],
                            check=row["independent_check"]["status"],
                        )
                    ),
                    flush=True,
                )
            result = summarize(rows, frozen)
            write_json(output / "results.json", dict(summary=result, rows=rows))
            write_json(
                output / "progress.json",
                dict(
                    phase="completed",
                    planned=len(frozen["pilot_ids"]),
                    terminal=len(rows),
                    summary=result,
                ),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        server.should_exit = True
        await service
        sock.close()


def summarize(rows, context):
    costs = [r.get("cost", {}) for r in rows]
    elapsed = sorted(r["elapsed_seconds"] for r in rows)
    return dict(
        planned=len(context["pilot_ids"]),
        terminal=len(rows),
        published=sum(r["status"] == "published" for r in rows),
        delivered=sum(r["delivery_pass"] for r in rows),
        failure_stages=dict(Counter(r["stage"] for r in rows if not r["delivery_pass"])),
        published_functional_defects=sum(
            r["status"] == "published" and not r["final_functional_pass"] for r in rows
        ),
        final_browser_paths={
            k: sum(r["independent_check"][k] for r in rows)
            for k in ("planned", "executed", "passed")
        },
        actual_cli_calls=sum(c.get("cli_process_calls", 0) for c in costs),
        intake_calls=sum(c.get("intake_calls", 0) for c in costs),
        core_calls=sum(c.get("core_calls", 0) for c in costs),
        internal_core_repairs=sum(r.get("internal_core_repairs", 0) for r in rows),
        calls_with_usage=sum(c.get("calls_with_reported_usage", 0) for c in costs),
        reported_root_tokens={
            k: sum(c.get("reported_root_tokens", {}).get(k, 0) for c in costs)
            for k in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        median_task_elapsed_seconds=round(
            (elapsed[(len(elapsed) - 1) // 2] + elapsed[len(elapsed) // 2]) / 2, 2
        )
        if elapsed
        else None,
        sum_task_elapsed_seconds=round(sum(elapsed), 2),
        model=context["model"],
        monetary_cost=None,
        billing_boundary="CLI ChatGPT login gives no per-task monetary bill; reported root tokens may not exhaust native-child usage.",
        observed_input_flags=sum(len(c.get("observed_input_flags", [])) for c in costs),
        heldout_executed=0,
        comparison="Development calibration of current full product only, not A/B/C effect evidence; original failures never replaced.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6.1-sol")
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument(
        "--regression-ids",
        nargs="+",
        help="At most3 observed failing development IDs from the original frozen20; no other batch allowed",
    )
    args = parser.parse_args()
    asyncio.run(run_cases(args))
