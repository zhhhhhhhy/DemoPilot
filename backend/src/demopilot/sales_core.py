"""Persistent, single-machine sales sessions around the shared quotation Core."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .core_harness import CodexCliHarness
from .quotation_cli import IsolatedCodexProvider
from .quotation_contract import compile_acceptance, price
from .quotation_loop import QuotationGoalLoop, write_json
from .quotation_release import ReleaseRegistry, canonical_hash
from .sales_contract import INTAKE_INSTRUCTION, IntakeResult, QuotePlan

ACTIVE = {"analyzing", "queued", "building", "testing"}
IDENTIFIER = re.compile(r"^[a-f0-9]{16}$")

UI_CONTRACT = """# Confirmed quotation application interface

Implement the exact catalogue, pricing profile(s), workflow and optional shipping in JSON. Profile keys and product IDs are selector values; display friendly Chinese labels and the confirmed product names. There are no other discounts or taxes. Prices use full precision then independent half-up two-decimal display rounding. Tax-inclusive subtotal is rounded before residual tax. Quantity tiers apply to all paid units, not progressive bands. Free units do not add charged units.

Required interface:
- selects #profile (only JSON profiles), #product/#second-product (A/B/C), #customer (standard/vip/partner), #record (Q1/Q2), #role (seller/manager/finance/customer), #actor (seller1/manager1/manager2/finance1/client1/intruder).
- inputs #quantity initially1, #second-quantity initially0, #date initially2026-03-15, #reason initiallyempty, #today initially2026-03-15 (simulated current day, separate from quote date).
- Initial profile is the FIRST declared JSON profile; productA, second-productB, customerstandard, recordQ1, roleseller, actorseller1. All amounts reflect initial values; stateDraft, revision0, approved-revision -1, history-count0.
- buttons #calculate, #submit, #approve, #reject, #accept, #cancel, #amend. Wrong/repeated/out-of-order actions preserve all committed values and history, showing #error; disabled actions are acceptable. No external submission.
- visible outputs #subtotal, #discount, #tax, #total with EXACT two-decimal money strings and no currency symbols; #free-quantity, #revision, #approved-revision, #history-count integer strings; #state uses exact codes Draft/PendingManager/PendingFinance/Approved/Rejected/Accepted/Cancelled.
- If contract version2, #shipping select pickup/standard/express initiallypickup and output #freight. Use confirmed charges, once per quote AFTER discounts and tax, include in approval threshold. Otherwise do not add shipping requirements. manual_override alone adds #manual-rate input initiallyempty.

Shared state rules:
Two independently stored quotes Q1/Q2; form changes are STAGED until Calculate. Switching record restores that quote. Product/quantity/customer/profile/date/manual-rate/shipping changes commit only via Calculate by seller; quantity integers, first>=1/second>=0; invalid or wrong-role commits change nothing. A genuinely changed quote increments revision AND history once, resets Draft, clears all approval, approved-revision=-1. Same-value recalculation does not accumulate discounts or history. Editing Accepted/Cancelled is forbidden.
Seller Submit from Draft/Rejected ->PendingManager, history+1, clears approvals. Manager Approve PendingManager ->Approved (or workflow's next step); finance cannot substitute for manager. Final approval sets approved-revision=current revision. Manager Reject PendingManager or finance Reject PendingFinance ->Rejected, clears approvals; history+1. Customer Accept only Approved ->Accepted. Seller Cancel except Accepted/Cancelled ->Cancelled and clears approvals. Each successful state transition including a partial manager approval adds exactly1 history; rejection/duplicate actions add0. Same manager actor cannot approve twice. Role/actor/reason/today/selected-record changes alone never alter quote history.

Selected workflow only:
single_manager: shared manager flow.
two_stage: manager ->PendingFinance, finance ->Approved.
threshold: after manager, total>=approval_threshold ->PendingFinance elseApproved.
dual_manager: manager1 first remainsPendingManager; repeating manager1 denied; manager2 completesApproved.
rejection_reason: Reject requires a nonempty trimmed reason; fixing/resubmitting clears approvals.
cancel_amend: seller Amend fromCancelled ->Draft, revision+1/history+1, retain fields and clear approvals.
customer_owner: Accept requires customer role AND client1 actor; intruder denied.
expiry: Accept requires today<=valid_until, including boundary; changing today alone does not mutate quote.
record_persistence: persist each quote's fields, amounts, state, revisions, history, approvers across reload; reload resets selected record/role/actor toQ1/seller/seller1. Other workflows need in-page isolation; persistence optional.
manual_override: positive manual-rate replaces A unit rate before pricing and persists on later recalculation; configured customer protocol rate takes precedence for rate_override; nonpositive manual rate invalid.

Pricing details are in JSON. For rate_override, Subtotal uses original catalogue/manual prices, the rate difference appears in Discount. Do not change confirmed prices or business rules to satisfy a test. Use only local files, no remote requests. Keep scripts in app.js, styles in styles.css, no inline event handlers. The parent owns trusted tests and publishing; implement and self-test until those checks pass or report the unmet goal.
"""


def now():
    return datetime.now(UTC).isoformat()


class SessionConflict(ValueError):
    pass


class SalesSessions:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def directory(self, identifier):
        if not IDENTIFIER.fullmatch(identifier):
            raise KeyError(identifier)
        return self.root / identifier

    def get(self, identifier):
        with self.lock:
            path = self.directory(identifier) / "session.json"
            if not path.is_file():
                raise KeyError(identifier)
            return json.loads(path.read_text("utf-8"))

    def save(self, session):
        with self.lock:
            session["updated_at"] = now()
            write_json(self.directory(session["id"]) / "session.json", session)

    def change(self, identifier, mutate):
        with self.lock:
            session = self.get(identifier)
            mutate(session)
            self.save(session)
            return session

    def list(self):
        with self.lock:
            result = [self.get(p.name) for p in self.root.iterdir() if p.is_dir() and IDENTIFIER.fullmatch(p.name) and (p / "session.json").is_file()]
        return sorted(result, key=lambda s: s["updated_at"], reverse=True)


def add_event(session, kind, message, **details):
    session["events"].append(dict(sequence=len(session["events"]) + 1, time=now(), kind=kind, message=message, **details))


def final_object(result):
    messages = []
    events = list(result.get("events", []))
    stdout = result.get("transcript", {}).get("stdout")
    if stdout:
        path = Path(stdout)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("需求识别输出超过允许长度")
        for line in path.read_text("utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    for event in events:
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            messages.append(item.get("text", ""))
    for text in reversed(messages):
        try:
            value = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            if isinstance(value, dict) and isinstance(value.get("payload"), str):
                value = json.loads(value["payload"])
            return value
        except (ValueError, TypeError):
            continue
    raise ValueError("模型没有返回有效的需求结构")


class SalesCoreManager:
    def __init__(self, settings, *, harness=None, interviewer=None, project_root=None, checker=None):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3])
        self.root = Path(settings.data_dir) / "sales-core"
        self.store = SalesSessions(self.root / "sessions")
        self.registry = ReleaseRegistry(self.root / "registry")
        self.provider = IsolatedCodexProvider(
            command=settings.codex_command, model=settings.codex_model,
            reasoning_effort=settings.codex_reasoning_effort,
            timeout_seconds=settings.codex_timeout_seconds,
        )
        self.harness = harness or CodexCliHarness(self.provider)
        self.interviewer = interviewer
        self.checker = checker
        self.tasks = {}
        self.slots = asyncio.Semaphore(1)
        self.activity = {}

    def public(self, identifier):
        session = self.store.get(identifier)
        session["active"] = session["status"] in ACTIVE
        session["call_cap"] = 3
        return session

    def create(self, brief, request_key=None):
        if request_key:
            for existing in self.store.list():
                if existing.get("request_key") == request_key:
                    if existing["messages"][0]["content"] != brief:
                        raise SessionConflict("同一提交编号不能用于不同需求")
                    return self.public(existing["id"])
        identifier = uuid.uuid4().hex[:16]
        session = dict(id=identifier, title=brief[:60], status="analyzing", stage="正在理解需求", revision=0,
                       messages=[dict(role="user", content=brief)], questions=[], draft=None, draft_hash=None,
                       summary=[], examples=[], events=[], versions=[], demo_url=None,
                       iteration=0, checks=None, error=None, request_key=request_key, created_at=now(), updated_at=now())
        add_event(session, "created", "已收到一句话需求，等待模型识别缺失信息")
        self.store.save(session)
        self._schedule(identifier, self._analyze(identifier))
        return self.public(identifier)

    def _schedule(self, identifier, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks[identifier] = task

        def done(completed):
            if self.tasks.get(identifier) is completed:
                self.tasks.pop(identifier, None)

        task.add_done_callback(done)

    def reply(self, identifier, answer):
        session = self.store.get(identifier)
        if session["status"] in ACTIVE:
            raise SessionConflict("任务正在执行，请先取消，再修改需求")
        if len(session["messages"]) >= 30:
            raise SessionConflict("本次需求对话已达上限，请新建任务")
        session["messages"].append(dict(role="user", content=answer))
        session.update(status="analyzing", stage="正在核对补充信息", error=None, demo_url=None, questions=[], draft=None, draft_hash=None, summary=[], examples=[])
        add_event(session, "answer", "已保存补充信息，重新核对需求")
        self.store.save(session)
        self._schedule(identifier, self._analyze(identifier))
        return self.public(identifier)

    def confirm(self, identifier, draft_hash):
        session = self.store.get(identifier)
        if draft_hash != session["draft_hash"] or not session["draft"]:
            raise SessionConflict("需求已变化，请重新查看并确认最新规则")
        if session["status"] in {"queued", "building", "testing", "published"}:
            return self.public(identifier)
        if session["status"] != "ready":
            raise SessionConflict("请先回答所有问题并确认完整需求")
        plan = QuotePlan.model_validate(session["draft"])
        session["revision"] += 1
        contract = plan.contract(identifier)
        self.registry.set_intent(identifier, session["revision"], contract)
        session.update(status="queued", stage="等待 Core Builder", demo_url=None, error=None, iteration=0, checks=None)
        add_event(session, "confirmed", f"已确认需求第 {session['revision']} 版，未通过测试前保持隐藏")
        self.store.save(session)
        self._schedule(identifier, self._build(identifier, session["revision"], plan))
        return self.public(identifier)

    async def _analyze(self, identifier):
        try:
            async with self.slots:
                session = self.store.get(identifier)
                self._progress(identifier, "analyzing", "模型正在核对商品、计价和审批规则")
                history = session["messages"]
                transcript = self.store.directory(identifier) / "intent" / f"turn-{len(history)}"
                workspace = self.store.directory(identifier) / "intent-workspace"
                workspace.mkdir(parents=True, exist_ok=True)
                prompt = INTAKE_INSTRUCTION + json.dumps(IntakeResult.model_json_schema(), ensure_ascii=False) + "\n用户对话：\n" + json.dumps(history, ensure_ascii=False)
                if self.interviewer:
                    raw = await self.interviewer(prompt, history, transcript)
                else:
                    raw = final_object(await self.provider.run_workspace_acceptance(
                        prompt=prompt, workspace=workspace, transcript_dir=transcript,
                        readable_roots=[workspace], on_event=lambda e: self._activity(identifier, e),
                    ))
                output = IntakeResult.model_validate(raw)
                source = "\n".join(m["content"] for m in history if m["role"] == "user")
                if output.status == "ready" and any(not quote.strip() or quote not in source for quote in output.source_quotes):
                    raise ValueError("需求引用不在用户提供的信息中")

                def apply(current):
                    current.update(title=output.title, status=output.status,
                                   stage="请确认规则" if output.status == "ready" else "等待补充信息",
                                   questions=output.questions, error=None)
                    if output.proposal:
                        plan = output.proposal
                        current["draft"] = plan.model_dump(mode="json")
                        current["draft_hash"] = canonical_hash(current["draft"])
                        current["summary"] = plan.summary()
                        current["examples"] = self._examples(plan, identifier)
                        current["source_quotes"] = output.source_quotes
                    else:
                        current.update(draft=None, draft_hash=None, summary=[], examples=[])
                    if output.questions:
                        current["messages"].append(dict(role="assistant", content="\n".join(output.questions)))
                        add_event(current, "questions", f"模型提出 {len(output.questions)} 个需要确认的问题")
                    else:
                        add_event(current, "ready", "业务规则已整理，等待用户确认；尚未调用 Builder")

                self.store.change(identifier, apply)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._error(identifier, exc, "需求识别未完成，可从页面重试或补充信息")

    def _examples(self, plan, identifier):
        contract = plan.contract(identifier)
        profile = next(iter(contract["profiles"]))
        return [dict(label=f"{q} 件 A，普通客户、无第二款商品", quantity=q, total=price(contract, dict(
            profile=profile, product="A", quantity=str(q), second_product="B", second_quantity="0",
            customer="standard", date="2026-03-15", manual_rate="", shipping="pickup",
        ))["total"]) for q in (1, 5, 10)]

    def _activity(self, identifier, event):
        moment = time.monotonic()
        if moment - self.activity.get(identifier, 0) < 2:
            return
        self.activity[identifier] = moment
        self.store.change(identifier, lambda s: s.update(last_activity_at=now(), last_activity_type=event.get("type", "activity")))

    def _progress(self, identifier, status, message, **values):
        def apply(session):
            if session["status"] in {"cancelled", "interrupted"}:
                return
            session.update(status=status, stage=message, **values)
            add_event(session, status, message)

        self.store.change(identifier, apply)

    async def _build(self, identifier, revision, plan):
        try:
            async with self.slots:
                directory = self.store.directory(identifier) / f"revision-{revision}"
                inputs = directory / "inputs"
                inputs.mkdir(parents=True, exist_ok=True)
                contract = plan.contract(identifier)
                version = contract["version"]
                write_json(inputs / f"contract-v{version}.json", contract)
                write_json(inputs / f"public-tests-v{version}.json", compile_acceptance(contract))
                (inputs / "CONTRACT.md").write_text(UI_CONTRACT, encoding="utf-8")
                workspace = directory / "workspace"
                workspace.mkdir(exist_ok=True)
                previous = self.store.get(identifier)["versions"]
                if previous:
                    old = previous[-1]
                    bundle = self.registry.resolve_accepted_bundle(identifier, old["revision"], old["artifact"])
                    if bundle:
                        shutil.copytree(bundle["path"], workspace / "card-web")
                session = self.store.get(identifier)
                app = dict(id=identifier, workflow=plan.workflow, split="interactive", testdata_path=str(inputs.resolve()))
                goal = dict(title=plan.title, revision=revision, contract_version=version, messages=session["messages"])
                loop = QuotationGoalLoop(self.harness, self.registry, project_root=self.project_root, call_cap=3)
                result = await loop.execute_goal(app=app, goal=goal, workspace=workspace, result_dir=directory / "evidence", on_progress=lambda e: self._core_event(identifier, revision, e))
                write_json(directory / "result.json", result)
                if result["status"] != "published":
                    self._progress(identifier, "failed", "三轮预算内未通过完整检查，本版保持隐藏", error="请查看检查结果，补充或修改需求后可从页面重新生成")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_job(identifier, revision, "Controller did not finish")
            self._error(identifier, exc, "构建未完成，本版未发布；可从页面重试")

    def _core_event(self, identifier, revision, event):
        kind = event["kind"]
        current = self.store.get(identifier)
        if current["revision"] != revision or current["status"] in {"cancelled", "interrupted"}:
            return
        if kind == "cli_activity":
            self._activity(identifier, dict(type=event["event_type"]))
        elif kind == "iteration_started":
            self._progress(identifier, "building", f"Core Builder 第 {event['iteration'] + 1} 轮构建", iteration=event["iteration"] + 1)
        elif kind == "testing":
            self._progress(identifier, "testing", "正在真实浏览器中检查金额、审批和负向操作")
        elif kind == "checked":
            def checked(session):
                session["checks"] = dict(status=event["status"], passed=event["passed_journeys"], planned=event["planned_journeys"], issues=event["issues"][:12])
                add_event(session, "checked", f"第 {event['iteration'] + 1} 轮检查：{'通过' if event['status'] == 'passed' else '未通过'}", **session["checks"])
            self.store.change(identifier, checked)
        elif kind == "repair_queued":
            self._progress(identifier, "building", "检查未通过，问题已反馈给同一 Core 修复；页面保持隐藏")
        elif kind == "published":
            release = event["release"]
            def publish(session):
                url = f"/api/sales-core/accepted/{identifier}/{revision}/{release['artifact']}/index.html"
                session.update(status="published", stage="已通过业务检查，发布到本机展示区", demo_url=url, error=None)
                session["versions"].append(dict(revision=revision, artifact=release["artifact"], url=url, published_at=now(), title=session["title"]))
                add_event(session, "published", f"需求第 {revision} 版已发布，页面与脚本固定到同一验收版本")
            self.store.change(identifier, publish)

    def _fail_job(self, identifier, revision, reason):
        job_id = f"{identifier}-reliable-v{revision}"
        for job in self.registry.snapshot()["jobs"]:
            if job["id"] == job_id and job["status"] == "running":
                self.registry.fail(job_id, job["token"], reason)

    def _error(self, identifier, exc, message):
        directory = self.store.directory(identifier) / "diagnostics"
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / f"error-{time.time_ns()}.json", dict(type=type(exc).__name__, message=str(exc)))
        self._progress(identifier, "failed", message, error=message)

    async def cancel(self, identifier):
        session = self.store.get(identifier)
        if session["status"] not in ACTIVE:
            return self.public(identifier)
        self._fail_job(identifier, session["revision"], "Cancelled by user")
        self._progress(identifier, "cancelled", "已取消，当前候选不会发布", demo_url=None)
        task = self.tasks.get(identifier)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.public(identifier)

    def retry(self, identifier):
        session = self.store.get(identifier)
        if session["status"] not in {"failed", "cancelled", "interrupted"}:
            raise SessionConflict("当前状态不需要重试")
        if session["draft"]:
            self.store.change(identifier, lambda s: s.update(status="ready"))
            return self.confirm(identifier, session["draft_hash"])
        self.store.change(identifier, lambda s: s.update(status="analyzing", error=None, stage="重新识别需求"))
        self._schedule(identifier, self._analyze(identifier))
        return self.public(identifier)

    def recover(self):
        for session in self.store.list():
            if session["status"] in ACTIVE:
                self._fail_job(session["id"], session["revision"], "Service interrupted")
                self._progress(session["id"], "interrupted", "服务曾中断，已有对话和结果已保留；可点击恢复", demo_url=None)

    async def shutdown(self):
        for session in self.store.list():
            if session["status"] in ACTIVE:
                self._fail_job(session["id"], session["revision"], "Service stopped")
                self._progress(session["id"], "interrupted", "服务已停止，可从页面恢复", demo_url=None)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
