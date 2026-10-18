"""Read-only reconciliation of quotation evidence; no model, browser or rescoring."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evaluation_sets/quotation-intent-v1"
DOCS = ROOT / "docs/quotation-intent-v1"
HELD = DATA / "results/heldout-20261016"
DEV = DATA / "results/development-v2-20261016"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks = []

    def check(name, condition, detail):
        checks.append(dict(name=name, passed=bool(condition), detail=detail))

    cases = load(DATA / "cases.json")["cases"]
    source_urls = {s["url"] for s in load(DATA / "sources.json")["sources"]}
    check("ten_distinct_source_backed_tasks", len(cases) == 10 and len({c["family"] for c in cases}) == 10
          and len(source_urls) == 4 and all(set(c["source_urls"]) <= source_urls for c in cases),
          dict(tasks=len(cases), rule_families=len({c["family"] for c in cases}), official_sources=len(source_urls)))
    check("fixed_development_holdout_split", sum(c["split"] == "development" for c in cases) == 4
          and sum(c["split"] == "heldout" for c in cases) == 6,
          {split: [c["id"] for c in cases if c["split"] == split] for split in ("development", "heldout")})
    manifest = load(DATA / "manifest.json")["files"]
    mismatches = [name for name, digest in manifest.items() if not (ROOT / name).is_file() or sha(ROOT / name) != digest]
    check("all_manifest_artifacts_unchanged", not mismatches, dict(files=len(manifest), mismatches=mismatches))
    context = load(HELD / "context.json")
    changed_code = [name for name, digest in context["code_sha256"].items()
                    if sha(ROOT / name) != digest or sha(HELD / "frozen-code" / name) != digest]
    check("final_runtime_code_still_frozen", not changed_code, dict(files=len(context["code_sha256"]), changed=changed_code))
    check("dataset_and_sources_match_freeze", sha(DATA / "manifest.json") == context["data_manifest_sha256"]
          and sha(DATA / "sources.json") == context["source_registry_sha256"], "Current manifest and sources match held-out context")
    changed_gold = []
    original = DATA / "results/development-20261016/frozen-data/evaluation_sets/quotation-intent-v1/private"
    for case in cases:
        current = DATA / "private" / (case["id"] + ".json")
        for frozen in (original / current.name, HELD / "frozen-data/evaluation_sets/quotation-intent-v1/private" / current.name):
            if sha(current) != sha(frozen):
                changed_gold.append(str(frozen))
    check("numerical_gold_unchanged_since_initial_pilot", not changed_gold, changed_gold)
    lock = load(DOCS / "development-decision.json")
    result_rows = load(DEV / "results.json")["results"] + load(HELD / "results.json")["results"]
    check("twenty_unique_planned_terminal_arms", len(result_rows) == 20
          and len({(r["case_id"], r["arm"]) for r in result_rows}) == 20
          and len({r["run_id"] for r in result_rows}) == 20
          and all(r["status"] in ("completed", "failed", "cancelled") for r in result_rows),
          dict(planned=20, terminal=len(result_rows), separate_pilot_and_regression_excluded=True))
    held_rows = load(HELD / "results.json")["results"]
    check("freeze_precedes_every_heldout_run", all(datetime.fromisoformat(r["started_at"]) > datetime.fromisoformat(lock["timestamp"])
          for r in held_rows) and lock["primary_test_model_runs_so_far"] == 0, lock["timestamp"])
    request_errors, mounted_errors, trace_errors = [], [], []
    for row in result_rows:
        run = Path(row["run_dir"])
        request = load(run / "run.json")["request"]
        case = next(c for c in cases if c["id"] == row["case_id"])
        if request["scenario"] != case["raw_sales_brief"]:
            request_errors.append(row["run_id"])
        # The one failed development intent never entered Core; its ordinary input was not mounted.
        if not (run / "core-workspace").exists():
            continue
        for filename in ("inputs.json", "acceptance.json"):
            mounted = run / "core-workspace/testdata" / case["id"] / filename
            canonical = ROOT / case["testdata_path"] / filename
            if not mounted.exists() or sha(mounted) != sha(canonical):
                mounted_errors.append(str(mounted))
        iterations = list((run / "artifacts/evidence/core").glob("iteration-*"))
        if not iterations or any(not (p / "prompt.txt").exists() or not (p / "stdout.jsonl").exists() for p in iterations):
            trace_errors.append(str(run))
    check("same_raw_sales_text", not request_errors, request_errors)
    check("ordinary_fixtures_delivered_without_mutation", not mounted_errors, mounted_errors)
    check("core_prompts_and_outputs_retained", not trace_errors, trace_errors)
    initial_contexts = list(HELD.glob("quotation-*/clarify/intent/turn-01-context.json"))
    check("first_intent_turn_does_not_contain_answers", len(initial_contexts) == 6
          and all(load(p)["clarification_answers"] == [] for p in initial_contexts), len(initial_contexts))
    audit = load(HELD / "business-audit.json")
    rows = audit["rows"]
    check("all_twelve_arms_independently_scored", len(rows) == 12 and len({(r["case_id"], r["arm"]) for r in rows}) == 12
          and not audit["feedback_to_builder"], dict(rows=len(rows), feedback_to_builder=audit["feedback_to_builder"]))
    recalculated = {}
    missing_images, modified_demos = [], []
    for arm in ("direct", "clarify"):
        selected = [r for r in rows if r["arm"] == arm]
        journeys = [j for r in selected for j in r["journeys"]]
        recalculated[arm] = dict(cases=len(selected), complete_pass=sum(r["end_to_end_pass"] for r in selected),
                                planned=sum(r["planned_journeys"] for r in selected), executed=len(journeys),
                                passed=sum(j["status"] == "passed" for j in journeys))
        check(arm + "_full_browser_denominator", len(journeys) == 68
              and all(j["status"] != "not_run" and j["fresh_context"] for j in journeys), recalculated[arm])
        for row in selected:
            expected_pass = row["publication_status"] == "published" and all(j["status"] == "passed" for j in row["journeys"])
            check(row["case_id"] + "_" + arm + "_outcome_consistent", row["end_to_end_pass"] == expected_pass,
                  dict(complete_pass=row["end_to_end_pass"]))
            if not row["original_unchanged"] or row["source_sha256_before"] != row["source_sha256_after"]:
                modified_demos.append(row["run_id"])
            for journey in row["journeys"]:
                if journey.get("screenshot") and not (ROOT / journey["screenshot"]).is_file():
                    missing_images.append(journey["screenshot"])
    check("all_original_pages_unchanged_and_images_present", not modified_demos and not missing_images,
          dict(modified_demos=modified_demos, missing_images=missing_images))
    check("primary_effect_recomputed_from_rows", recalculated["direct"]["complete_pass"] == 1
          and recalculated["clarify"]["complete_pass"] == 5, recalculated)
    metrics = load(DOCS / "metrics.json")
    check("report_uses_primary_audit", metrics["heldout"] == audit["summary"], "No replacement by diagnostic replay or development regression")
    diagnostic = load(HELD / "post-score-diagnostics/quotation-08-return-replay.json")
    original_digest = load(DOCS / "measurement-notes.json")["primary_audit_sha256"]
    check("diagnostic_preserves_primary_score_and_source", sha(HELD / "business-audit.json") == original_digest
          == diagnostic["primary_audit_sha256_before"] == diagnostic["primary_audit_sha256_after"]
          and diagnostic["original_demo_unchanged"] and diagnostic["new_model_calls"] == 0,
          dict(primary_audit_sha256=original_digest, diagnostic_not_merged=True))
    missing_links = []
    for md in (DOCS / "结果与贡献.md", DOCS / "案例说明.md", DOCS / "measurement-notes.md",
               DATA / "需求与验收.md", ROOT / "docs/portfolio-v1/简历项目描述.md"):
        for link in re.findall(r"\]\(([^)]+)\)", md.read_text(encoding="utf-8")):
            if re.match(r"https?://|#", link):
                continue
            path = Path(link) if Path(link).is_absolute() else md.parent / link
            if not path.exists():
                missing_links.append(dict(document=str(md.relative_to(ROOT)), link=link))
    check("delivery_document_links_resolve", not missing_links, missing_links)
    result = dict(checked_at=datetime.now(UTC).isoformat(), status="passed" if all(c["passed"] for c in checks) else "failed",
                  method="Read-only reconciliation of hashes, retained runs, first-turn contexts, scored journeys and delivered report. No new generation or browser rerun.",
                  model=load(HELD / "context.json")["model"], checks=checks,
                  boundaries="AC completion means the requested evaluation and reporting are complete. It does not mean every generated demo passed or real-world sales benefit was proven.")
    (DOCS / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=result["status"], checks=len(checks), failed=[c for c in checks if not c["passed"]]), ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
