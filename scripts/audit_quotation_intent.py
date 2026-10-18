"""Offline fresh-browser quotation scoring. Never invokes or repairs Core."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from quotation_oracle import expected_quote

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation_sets" / "quotation-intent-v1"
OUTPUTS = dict(subtotal="#subtotal", discount="#discount", tax="#tax",
               total="#total", free_quantity="#free-quantity")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def numeric(text):
    # Exact numbers, never substring matching (e.g. 90 must not match 900).
    numbers = re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text)
    if len(numbers) != 1:
        raise ValueError(f"Expected one visible result number; found {len(numbers)} in {text!r}")
    value = Decimal(numbers[0].replace(",", ""))
    if not value.is_finite():
        raise ValueError("Non-finite result")
    return value


def read_outputs(page):
    for selector in OUTPUTS.values():
        if not page.locator(selector).is_visible():
            raise AssertionError(f"Result is not visible: {selector}")
    text = {field: page.locator(selector).inner_text(timeout=2000)
            for field, selector in OUTPUTS.items()}
    values = {field: numeric(value) for field, value in text.items()}
    return text, values


def compare_outputs(values, expected):
    return [dict(field=field, expected=str(expected[field]), observed=str(values[field]))
            for field in OUTPUTS
            if (values[field] != Decimal(str(expected[field])) if field == "free_quantity"
                else abs(values[field] - Decimal(str(expected[field]))) >= Decimal("0.005"))]


def fill_vector(page, vector):
    for selector, key in (("#product", "product"), ("#second-product", "second_product"),
                          ("#customer", "customer")):
        page.locator(selector).select_option(value=vector[key], timeout=2000)
    for selector, key in (("#quantity", "quantity"), ("#second-quantity", "second_quantity"),
                          ("#quote-date", "date")):
        page.locator(selector).fill(str(vector[key]), timeout=2000)
    page.locator("#calculate").click(timeout=2000)


def sha_files(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.iterdir()) if p.is_file()}


def input_boundary_audit(row, results_dir):
    markers = ("evaluation_sets", "seller-answers", "quotation_oracle.py",
               "materialize_quotation_intent.py", "/private/")
    paths = list((Path(row["run_dir"]) / "artifacts" / "evidence" / "core").glob("**/stdout.jsonl"))
    paths += list((results_dir / row["case_id"] / row["arm"] / "intent").glob("*-stdout.jsonl"))
    findings, tool_count = [], 0
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "item.completed":
                continue
            item = event.get("item", {})
            kind = item.get("type")
            if kind not in {"command_execution", "mcp_tool_call", "web_search"}:
                continue
            tool_count += 1
            command = str(item.get("command", item.get("arguments", "")))
            normalized = re.sub(r"/+", "/", command.lower().replace("\\", "/"))
            # The allowed current workspace itself is below evaluation_sets.
            # Strip only this run's exact prefix before checking private reads.
            allowed = re.sub(r"/+", "/", str(Path(row["run_dir"]).resolve()).lower().replace("\\", "/"))
            normalized = normalized.replace(allowed, "<current-run>")
            matched = [marker for marker in markers if marker in normalized]
            if "../" in normalized:
                matched.append("parent-directory-traversal")
            text_only_violation = path.parent.name == "intent"
            if matched or text_only_violation or kind == "web_search":
                findings.append(dict(transcript=str(path), event_id=item.get("id"),
                                     kind=kind, command=command[:1000], matched=matched,
                                     text_only_violation=text_only_violation))
    return dict(status="passed" if not findings else "contaminated", retained_tool_events=tool_count,
                findings=findings, boundary="Prompt policy plus retained-tool audit; not an OS-level read-isolation proof.")


def audit_row(browser, row, output_dir):
    spec = load(DATASET / "private" / f"{row['case_id']}.json")
    planned = len(spec["vectors"]) + len(spec["negative_vectors"]) + 2
    report = dict(case_id=row["case_id"], arm=row["arm"], run_id=row["run_id"], split=row["split"],
                  publication_status=row["publication_status"], planned_journeys=planned,
                  journeys=[], business_status="not_run", end_to_end_pass=False)
    report["input_boundary"] = input_boundary_audit(row, output_dir.parent)
    demo = Path(row["run_dir"]) / "artifacts" / "demo"
    if row["publication_status"] != "published" or not (demo / "index.html").is_file():
        report["reason"] = "Not published; no successful delivery; stays in full denominator."
        report["not_run_journeys"] = planned
        return report
    before = sha_files(demo)
    report["source_sha256_before"] = before
    target = output_dir / row["case_id"] / row["arm"]
    target.mkdir(parents=True, exist_ok=True)
    jobs = [(vector["id"], "positive", vector) for vector in spec["vectors"]]
    jobs += [(vector["id"], "negative", vector) for vector in spec["negative_vectors"]]
    jobs += [("repeat-calculate", "repeat", spec["vectors"][-1]),
             ("change-and-return", "return", spec["vectors"][0])]
    for name, kind, vector in jobs:
        context = browser.new_context(viewport=dict(width=1360, height=900))
        # Generated demos are offline. External network access cannot help scores.
        context.route(re.compile(r"^https?://"), lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        journey = dict(id=name, kind=kind, status="failed", fresh_context=True, input=vector)
        try:
            page.goto((demo / "index.html").as_uri(), wait_until="load", timeout=10000)
            if kind == "negative":
                baseline = spec["vectors"][0]
                fill_vector(page, baseline)
                _, baseline_values = read_outputs(page)
                validation_before = page.locator("#validation").inner_text(timeout=2000)
                if validation_before.strip():
                    raise AssertionError("Valid baseline did not clear quantity validation")
                for selector, key in (("#quantity", "quantity"), ("#second-quantity", "second_quantity")):
                    page.locator(selector).fill(vector[key], timeout=2000)
                page.locator("#calculate").click(timeout=2000)
                validation = page.locator("#validation").inner_text(timeout=2000)
                journey["validation"] = validation
                if not page.locator("#validation").is_visible() or "数量" not in validation:
                    raise AssertionError("Invalid quantity lacks visible validation")
                _, invalid_values = read_outputs(page)
                if invalid_values != baseline_values:
                    raise AssertionError("Invalid input replaced the last valid quote")
                fill_vector(page, baseline)
                _, recovered_values = read_outputs(page)
                if page.locator("#validation").inner_text().strip() or recovered_values != baseline_values:
                    raise AssertionError("Valid input did not recover after validation error")
            else:
                fill_vector(page, vector)
                if kind == "repeat":
                    text_before, values_before = read_outputs(page)
                    page.locator("#calculate").click(timeout=2000)
                    text_after, values_after = read_outputs(page)
                    if values_before != values_after:
                        raise AssertionError("Repeated calculation accumulates or changes amounts")
                elif kind == "return":
                    fill_vector(page, spec["vectors"][-1])
                    fill_vector(page, vector)
                expected = expected_quote(spec, vector)
                if not page.locator("#rule").is_visible() or not page.locator("#rule").inner_text().strip():
                    raise AssertionError("Pricing explanation is missing or hidden")
                text, values = read_outputs(page)
                mismatches = compare_outputs(values, expected)
                journey.update(expected=expected, visible=text,
                               observed={k: str(v) for k, v in values.items()}, mismatches=mismatches)
                if mismatches:
                    raise AssertionError("Business amount or free-quantity mismatch")
            if errors:
                raise AssertionError("Runtime page errors: " + " | ".join(errors))
            journey["status"] = "passed"
        except Exception as exc:
            journey["error"] = f"{type(exc).__name__}: {str(exc)[:600]}"
        finally:
            journey["page_errors"] = errors
            screenshot = target / f"{name}.png"
            try:
                page.screenshot(path=str(screenshot), full_page=True, timeout=5000)
                journey["screenshot"] = str(screenshot)
            except Exception as exc:
                journey["screenshot_error"] = str(exc)[:200]
            context.close()
        report["journeys"].append(journey)
        write(target / "audit.json", report)
    report["source_sha256_after"] = sha_files(demo)
    report["original_unchanged"] = before == report["source_sha256_after"]
    report["passed_journeys"] = sum(j["status"] == "passed" for j in report["journeys"])
    report["not_run_journeys"] = planned - len(report["journeys"])
    report["end_to_end_pass"] = (
        report["passed_journeys"] == planned and report["original_unchanged"]
        and row["status"] == "completed" and row["quality_gate"] == "passed"
        and report["input_boundary"]["status"] == "passed"
    )
    report["business_status"] = "passed" if report["end_to_end_pass"] else "failed"
    write(target / "audit.json", report)
    return report


def summarize(rows, audits):
    arms = {}
    for arm in ("direct", "clarify"):
        arm_rows = [r for r in rows if r["arm"] == arm]
        arm_audits = [r for r in audits if r["arm"] == arm]
        elapsed = sorted(r["elapsed_seconds"] for r in arm_rows)
        n = len(arm_rows)
        arms[arm] = dict(
            planned_cases=n, published=sum(r["publication_status"] == "published" for r in arm_rows),
            business_pass=sum(r["end_to_end_pass"] for r in arm_audits),
            published_but_business_failed=sum(r["publication_status"] == "published" and not r["end_to_end_pass"] for r in arm_audits),
            core_revisions=sum(r["revision_count"] for r in arm_rows),
            first_pass_business=sum(r["end_to_end_pass"] and next(x for x in arm_rows if x["case_id"] == r["case_id"])["revision_count"] == 0 for r in arm_audits),
            total_cli_calls=sum(r["total_cli_calls"] for r in arm_rows),
            intent_cli_calls=sum(r["intent_cli_calls"] for r in arm_rows),
            total_elapsed_seconds=round(sum(elapsed), 3),
            median_elapsed_seconds=round((elapsed[(n-1)//2] + elapsed[n//2]) / 2, 3) if n else None,
            planned_journeys=sum(r["planned_journeys"] for r in arm_audits),
            passed_journeys=sum(r.get("passed_journeys", 0) for r in arm_audits),
            not_run_journeys=sum(r.get("not_run_journeys", 0) for r in arm_audits),
        )
    paired = []
    for case_id in sorted({r["case_id"] for r in rows}):
        mapping = {r["arm"]: r for r in audits if r["case_id"] == case_id}
        paired.append(dict(case_id=case_id, direct_pass=mapping["direct"]["end_to_end_pass"],
                           clarify_pass=mapping["clarify"]["end_to_end_pass"]))
    wins = sum(p["clarify_pass"] and not p["direct_pass"] for p in paired)
    losses = sum(p["direct_pass"] and not p["clarify_pass"] for p in paired)
    discordant = wins + losses
    # Exact paired sign/McNemar test on independent case outcomes, not journeys.
    p_value = min(1, 2 * sum(math.comb(discordant, k) for k in range(min(wins, losses) + 1))
                  / (2 ** discordant)) if discordant else 1.0
    return dict(arms=arms, paired=paired, clarification_only_wins=wins, direct_only_wins=losses,
                exact_paired_two_sided_p=p_value,
                observed_pass_difference=arms["clarify"]["business_pass"] - arms["direct"]["business_pass"],
                uncertainty="Small authored task set, single vendor rule families, single paired execution; journeys are dependent checks, not independent customer samples.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args()
    context = load(args.results_dir / "context.json")
    from run_quotation_intent_ab import FROZEN_CODE, sha
    if any(sha(ROOT / path) != context["code_sha256"][path] for path in FROZEN_CODE):
        raise RuntimeError("Frozen runner or evaluator changed; do not score mixed revisions")
    if sha(DATASET / "manifest.json") != context["data_manifest_sha256"]:
        raise RuntimeError("Frozen dataset manifest changed")
    for relative, expected in load(DATASET / "manifest.json")["files"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError(f"Frozen data changed: {relative}")
    results = load(args.results_dir / "results.json")
    rows = results["results"]
    if len(rows) != results["planned_arm_count"]:
        raise RuntimeError("Every planned arm must reach a recorded outcome before audit")
    report_path = args.results_dir / "business-audit.json"
    if report_path.exists():
        raise RuntimeError("Refusing to overwrite final independent scoring")
    from playwright.sync_api import sync_playwright
    audits = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for row in rows:
                audits.append(audit_row(browser, row, args.results_dir / "business-audit"))
                write(args.results_dir / "business-audit-progress.json", dict(rows=audits, feedback_to_builder=False))
        finally:
            browser.close()
    report = dict(created_at=datetime.now(UTC).isoformat(), split=context["split"],
                  rows=audits, feedback_to_builder=False, full_planned_denominator=True,
                  summary=summarize(rows, audits))
    write(report_path, report)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
