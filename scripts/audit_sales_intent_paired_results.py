"""Frozen, evaluator-only audit of published sales-intent experiment outputs.

This does not invoke a model or repair artifacts. It exercises every authored
fixture value through fresh local Chromium contexts after the generation loop
has finished. It preserves failed/skipped cases in the planned denominator.
The three-supplier requirement uses the common frozen sales clarification. UI
discovery failures remain UNVERIFIED; two purchase entities are never vendors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CASE_IDS = (
    "simple-quote-generator-01",
    "medium-lead-followup-01",
    "hard-procurement-approval-01",
)
ARMS = ("raw-sales", "intent-agent")
SUPPLIERS = (("A", 100, 5), ("B", 110, 3), ("C", 95, 7))


class UnverifiedRequirement(RuntimeError):
    """The evaluator cannot safely establish a semantic UI result."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_protocol() -> dict[str, Any]:
    return {
        "schema_version": "sales-intent-external-audit-v1",
        "case_ids": list(CASE_IDS),
        "arms": list(ARMS),
        "case_denominator_per_arm": len(CASE_IDS),
        "browser_channel": "local Playwright Chromium, headless, fresh context for each journey",
        "model_calls": 0,
        "feedback_to_builder": False,
        "fixture_policy": "Every authored plan, lead, entity and owner; fixed equivalent checks for both arms.",
        "checks": {
            CASE_IDS[0]: [
                "each of two plans at seats 1,3,4,7; exact computed total",
                "rendered demo-estimate boundary",
                "source goal subtotal and discount display",
            ],
            CASE_IDS[1]: [
                "each of two leads x two owners: industry filter, current detail, associated follow-up",
                "switching to the other lead does not relabel an existing follow-up",
            ],
            CASE_IDS[2]: [
                "each of two purchase entities x two owners: all seven ordered transitions",
                "audit history retains prior transitions and owner; other entity stays isolated",
                "terminal rollback rejected; reset restores every entity and clears history",
                "each entity: out-of-order transition blocked, missing reason blocked",
                "each entity: reject after submission leaves separate state and audit reason",
                "three demo suppliers A/B/C with quotes100/110/95 and delivery5/3/7, selecting B produces a visible chosen-plan result",
            ],
        },
        "limitations": [
            "Three cases are development cases, not an unseen representative sample.",
            "These are static demonstration fixtures, not a production CRM/procurement integration.",
            "Procurement source fixture has only two purchase entities; supplier A/B/C facts come from a shared, explicitly marked demo sales clarification.",
            "The procurement source contract includes order/receive steps absent from the original raw brief.",
            "A passed known contract does not establish all business goals; unverified semantic requirements never count as passed.",
        ],
        "source_hashes": {
            case_id: {
                name: sha256(ROOT / "testdata" / case_id / name)
                for name in ("inputs.json", "acceptance.json")
            }
            for case_id in CASE_IDS
        },
        "auditor_sha256": sha256(Path(__file__)),
    }


def summarize_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count all planned cases, including skipped or missing publication."""
    output: dict[str, Any] = {}
    for arm in ARMS:
        selected = {row["case_id"]: row for row in rows if row.get("arm") == arm}
        missing = [case_id for case_id in CASE_IDS if case_id not in selected]
        fixture_pass = sum(selected.get(case_id, {}).get("fixture_coverage_status") == "passed" for case_id in CASE_IDS)
        complete_pass = sum(selected.get(case_id, {}).get("business_status") == "passed" for case_id in CASE_IDS)
        output[arm] = {
            "planned_cases": len(CASE_IDS),
            "fixture_coverage_pass_count": fixture_pass,
            "fixture_coverage_pass_rate": f"{fixture_pass}/{len(CASE_IDS)}",
            "business_pass_count": complete_pass,
            "business_pass_rate": f"{complete_pass}/{len(CASE_IDS)}",
            "missing_cases": missing,
            "published_defect_cases": [case_id for case_id in CASE_IDS if selected.get(case_id, {}).get("published_defect")],
            "unverified_business_cases": [case_id for case_id in CASE_IDS if selected.get(case_id, {}).get("business_status") == "unverified"],
        }
    return output


def select(page: Any, selector: str, value: str) -> None:
    control = page.locator(selector).first
    try:
        control.select_option(label=str(value), timeout=3000)
    except Exception:
        control.select_option(value=str(value), timeout=3000)


def visible(page: Any, selector: str) -> str:
    locator = page.locator(selector)
    if not locator.count() or not locator.first.is_visible():
        raise AssertionError(f"Missing visible result: {selector}")
    return locator.inner_text()


def require_text(page: Any, selector: str, contains: list[str], excludes: list[str] | None = None) -> str:
    actual = visible(page, selector)
    missing = [word for word in contains if word not in actual]
    present = [word for word in (excludes or []) if word in actual]
    if missing or present:
        raise AssertionError(f"{selector}: missing={missing}, unexpected={present}, actual={actual[:300]}")
    return actual


def click(page: Any, selector: str) -> None:
    page.locator(selector).first.click(timeout=3000)


def audit_one(browser: Any, row: dict[str, Any], output_dir: Path, base_url: str) -> dict[str, Any]:
    case_id = row["case_id"]
    inputs = json.loads((ROOT / "testdata" / case_id / "inputs.json").read_text(encoding="utf-8"))
    fixture = inputs["fixtures"]
    result = {
        "case_id": case_id, "arm": row["arm"], "run_id": row.get("run_id"),
        "original_publication_status": row.get("publication_status"),
        "fixture_coverage_status": "not_run", "business_status": "not_run",
        "published_defect": False, "journeys": [], "semantic_requirements": [],
    }
    if row.get("publication_status") != "published" or not row.get("run_id"):
        result["reason"] = "No published result to audit; retained in denominator."
        return result
    url = f"{base_url.rstrip('/')}/api/runs/{row['run_id']}/files/artifacts/demo/index.html"
    result["url"] = url
    result["fixture_sha256"] = sha256(ROOT / "testdata" / case_id / "inputs.json")
    destination = output_dir / row["arm"] / case_id
    destination.mkdir(parents=True, exist_ok=True)

    def journey(name: str, action: Callable[[Any], None], semantic: bool = False) -> None:
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        observation: dict[str, Any] = {"id": name, "status": "failed", "fresh_browser_context": True, "semantic": semantic}
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            response = page.goto(url, wait_until="load", timeout=15000)
            if response is None or not response.ok:
                raise AssertionError(f"Published page HTTP status={response.status if response else 'none'}")
            action(page)
            if errors:
                raise AssertionError(f"JavaScript errors={errors}")
            observation["status"] = "passed"
        except UnverifiedRequirement as exc:
            observation["status"] = "unverified"
            observation["issue"] = str(exc)
        except Exception as exc:
            observation["issue"] = f"{type(exc).__name__}: {exc}"
        finally:
            observation["visible_text"] = page.locator("body").inner_text()[:12000] if page.locator("body").count() else ""
            if semantic:
                observation["dom_html"] = page.content()[:50000]
            observation["page_errors"] = errors
            shot = destination / f"{name}.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                observation["screenshot"] = str(shot)
            except Exception as exc:
                observation["screenshot_error"] = str(exc)
            context.close()
            result["journeys"].append(observation)

    if case_id == CASE_IDS[0]:
        for index, (plan, price) in enumerate(fixture["prices_per_seat"].items()):
            for seats in (1, 3, 4, 7):
                def quote(page: Any, plan: str = plan, price: int = price, seats: int = seats) -> None:
                    select(page, "#plan", plan)
                    page.locator("#seats").fill(str(seats))
                    click(page, "#calculate")
                    total = visible(page, "#total")
                    numbers = [float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", total)]
                    expected = price * seats
                    if expected not in numbers:
                        raise AssertionError(f"Expected exact quote {expected}; total={total}")
                    require_text(page, "body", [fixture["boundary"]])
                journey(f"plan-{index}-seats-{seats}", quote)
        def source_goal(page: Any) -> None:
            text = visible(page, "body")
            if not re.search(r"小计|subtotal", text, re.I) or not re.search(r"折扣|discount", text, re.I):
                raise AssertionError("Source goal requires both subtotal and discount displays; visible labels missing.")
        journey("source-subtotal-discount-display", source_goal)
    elif case_id == CASE_IDS[1]:
        leads = fixture["leads"]
        for index, lead in enumerate(leads):
            other = leads[(index + 1) % len(leads)]
            for owner_index, owner in enumerate(fixture["owners"]):
                def followup(page: Any, lead: dict[str, Any] = lead, other: dict[str, Any] = other, owner: str = owner) -> None:
                    select(page, "#industry", lead["industry"])
                    require_text(page, "#list", [lead["name"]], [other["name"]])
                    select(page, "#lead", lead["id"])
                    require_text(page, "#detail", [lead["name"]], [other["name"]])
                    select(page, "#owner", owner)
                    click(page, "#create")
                    require_text(page, "#tasks", [lead["id"], owner, "待跟进"], [other["id"]])
                    select(page, "#industry", other["industry"])
                    select(page, "#lead", other["id"])
                    require_text(page, "#detail", [other["name"]], [lead["name"]])
                    require_text(page, "#tasks", [lead["id"], owner], [other["id"]])
                journey(f"lead-{index}-owner-{owner_index}", followup)
    else:
        entities = fixture["entities"]
        transitions = fixture["ordered_transitions"]
        initial = fixture["initial_state"]
        for entity_index, entity in enumerate(entities):
            other = entities[(entity_index + 1) % len(entities)]
            for owner_index, owner in enumerate(fixture["owners"]):
                def main_path(page: Any, entity: dict[str, Any] = entity, other: dict[str, Any] = other, owner: str = owner) -> None:
                    reason = "独立验收：采购演示理由"
                    select(page, "#entity", entity["id"])
                    select(page, "#owner", owner)
                    page.locator("#reason").fill(reason)
                    visited: list[str] = []
                    for transition, state in transitions:
                        click(page, f"#{transition}")
                        require_text(page, "#status", [entity["id"], owner, state])
                        visited.append(state)
                        require_text(page, "#timeline", visited + [owner])
                    before = visible(page, "#status")
                    click(page, "#illegal")
                    if visible(page, "#status") != before:
                        raise AssertionError("Terminal-state rollback changed current state.")
                    require_text(page, "#errors", ["不可回退"])
                    select(page, "#entity", other["id"])
                    require_text(page, "#status", [other["id"], initial], [transitions[-1][1]])
                    require_text(page, "#timeline", [], visited + [reason])
                    click(page, "#reset")
                    for reset_entity in entities:
                        select(page, "#entity", reset_entity["id"])
                        require_text(page, "#status", [initial], [transitions[-1][1]])
                        require_text(page, "#timeline", [], visited + [reason])
                journey(f"entity-{entity_index}-owner-{owner_index}-main", main_path)
            def out_of_order(page: Any, entity: dict[str, Any] = entity) -> None:
                select(page, "#entity", entity["id"])
                click(page, f"#{transitions[-1][0]}")
                require_text(page, "#status", [initial], [transitions[-1][1]])
                require_text(page, "#errors", ["前置步骤未完成"])
            journey(f"entity-{entity_index}-out-of-order", out_of_order)
            def missing_reason(page: Any, entity: dict[str, Any] = entity) -> None:
                select(page, "#entity", entity["id"])
                select(page, "#owner", fixture["owners"][0])
                page.locator("#reason").fill("")
                control = page.locator(f"#{transitions[0][0]}").first
                if control.is_disabled():
                    require_text(page, "#status", [initial], [transitions[0][1]])
                    return  # A disabled transition also prevents an invalid write.
                click(page, f"#{transitions[0][0]}")
                require_text(page, "#status", [initial], [transitions[0][1]])
                if not visible(page, "#errors").strip():
                    raise AssertionError("Missing reason must produce visible rejection.")
            journey(f"entity-{entity_index}-missing-reason", missing_reason)
            def rejection(page: Any, entity: dict[str, Any] = entity) -> None:
                owner = fixture["owners"][entity_index % len(fixture["owners"])]
                reason = "独立验收：预算需要复核"
                select(page, "#entity", entity["id"])
                select(page, "#owner", owner)
                page.locator("#reason").fill(reason)
                for transition, _ in transitions[:4]:
                    click(page, f"#{transition}")
                click(page, "#reject")
                require_text(page, "#status", ["已退回", reason], ["已批准"])
                require_text(page, "#timeline", ["已退回", owner, reason])
            journey(f"entity-{entity_index}-reject-after-submit", rejection)
        def supplier_comparison(page: Any) -> None:
            select(page, "#entity", entities[0]["id"])
            select(page, "#owner", fixture["owners"][0])
            page.locator("#reason").fill("独立验收：比较供应商后选择B")
            click(page, "#create-request")
            click(page, "#compare")
            body = visible(page, "body")
            for letter, price, days in SUPPLIERS:
                supplier = re.compile(rf"(?:供应商|supplier)\s*{letter}\b", re.I)
                if not supplier.search(body):
                    raise AssertionError(f"Visible supplier {letter} is absent after comparison.")
                rows = page.locator("tr, li, article, [data-supplier], .supplier-card, .supplier")
                row_texts = [node.inner_text() for node in rows.all() if node.is_visible() and supplier.search(node.inner_text())]
                if not row_texts:
                    # Preserve DOM for independent manual discovery. Do not
                    # claim cross-row numbers prove this vendor's facts.
                    raise UnverifiedRequirement(f"Supplier {letter} is visible but no individual comparison row/card can be identified.")
                if not any(re.search(rf"(?<!\d){price}(?!\d)", text) and re.search(rf"(?<!\d){days}(?!\d)", text) for text in row_texts):
                    raise AssertionError(f"Supplier {letter} must visibly associate quote={price} and delivery={days}; rows={row_texts[:3]}")
            chosen = False
            for control in page.locator("select").all():
                options = control.locator("option").all()
                names = [(option.get_attribute("value"), option.inner_text()) for option in options]
                if all(any(re.search(rf"(?:供应商|supplier)\s*{letter}\b", label, re.I) for _, label in names) for letter, _, _ in SUPPLIERS):
                    value, label = next((value, label) for value, label in names if re.search(r"(?:供应商|supplier)\s*B\b", label, re.I))
                    control.select_option(value=value) if value is not None else control.select_option(label=label)
                    chosen = True
                    break
            if not chosen:
                vendor_b = re.compile(r"(?:供应商|supplier)\s*B\b", re.I)
                candidates = page.get_by_role("button", name=vendor_b)
                if candidates.count() and candidates.first.is_visible():
                    candidates.first.click()
                    chosen = True
                else:
                    for vendor_row in page.locator("tr, li, article, [data-supplier], .supplier-card, .supplier").all():
                        if vendor_row.is_visible() and vendor_b.search(vendor_row.inner_text()):
                            button = vendor_row.get_by_role("button")
                            if button.count() and button.first.is_visible():
                                button.first.click()
                                chosen = True
                                break
            if not chosen:
                raise UnverifiedRequirement("Three suppliers are visible, but no native select or per-supplier button can establish a selection of B.")
            if "方案已选" not in visible(page, "#status"):
                click(page, "#choose")
            result_locations = page.locator("#status, #timeline, #selectedSupplier, #selected-supplier, #selected-plan, #selection, #summary")
            chosen_text = "\n".join(node.inner_text() for node in result_locations.all() if node.is_visible())
            if not re.search(r"(?:供应商|supplier)\s*B\b", chosen_text, re.I):
                raise UnverifiedRequirement(f"Selection of B was performed, but visible result/audit does not identify B: {chosen_text[:400]}")
        journey("three-supplier-comparison-and-selection", supplier_comparison, semantic=True)
        observation = result["journeys"][-1]
        result["semantic_requirements"].append({
            "id": observation["id"], "status": observation["status"],
            "reason": observation.get("issue", "Three suppliers and the chosen B result independently observed in rendered UI."),
            "screenshot": observation.get("screenshot"),
        })
    failures = [item for item in result["journeys"] if item["status"] == "failed"]
    fixture_failures = [item for item in failures if not item.get("semantic")]
    unresolved = [item for item in result["journeys"] if item["status"] == "unverified"]
    result["fixture_coverage_status"] = "failed" if fixture_failures else "passed"
    result["published_defect"] = bool(failures)
    result["business_status"] = "failed" if failures else "unverified" if unresolved else "passed"
    result["journey_count"] = len(result["journeys"])
    result["failed_journey_count"] = len(failures)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8091")
    parser.add_argument("--freeze-protocol", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = args.output_dir / "external-audit-protocol.json"
    if args.freeze_protocol:
        if protocol_path.exists():
            raise SystemExit("Protocol already exists; refusing to overwrite frozen evidence.")
        protocol_path.write_text(json.dumps(frozen_protocol(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(str(protocol_path))
        return 0
    if not args.results or not protocol_path.exists():
        raise SystemExit("Supply --results and freeze --output-dir protocol before experimental runs.")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol["auditor_sha256"] != sha256(Path(__file__)):
        raise SystemExit("Auditor changed since protocol freeze; audit is not authorized.")
    for case_id, files in protocol["source_hashes"].items():
        for name, value in files.items():
            if sha256(ROOT / "testdata" / case_id / name) != value:
                raise SystemExit(f"Frozen source changed: {case_id}/{name}")
    results = json.loads(args.results.read_text(encoding="utf-8"))["results"]
    result_by_key = {(row["case_id"], row["arm"]): row for row in results}
    report: dict[str, Any] = {
        "schema_version": protocol["schema_version"], "created_at": datetime.now(UTC).isoformat(),
        "protocol": protocol, "source_results": str(args.results.resolve()),
        "rows": [], "metrics": {}, "feedback_to_builder": False,
    }
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for arm in ARMS:
                for case_id in CASE_IDS:
                    row = result_by_key.get((case_id, arm), {"case_id": case_id, "arm": arm})
                    report["rows"].append(audit_one(browser, row, args.output_dir, args.base_url))
                    report["metrics"] = summarize_audit(report["rows"])
                    (args.output_dir / "external-business-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            browser.close()
    print(json.dumps(report["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
