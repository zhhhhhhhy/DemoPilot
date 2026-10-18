import time

from playwright.sync_api import sync_playwright

from demopilot.core_acceptance import _run_browser


def exercise(tmp_path, options, selection, expected):
    path = tmp_path / "select.html"
    path.write_text('<select id="choice">' + options + '</select><div id="result"></div><script>document.getElementById("choice").addEventListener("change",event=>{document.getElementById("result").textContent=event.target.value})</script>', encoding="utf-8")
    contract = {"tests": [{"id": "selection", "steps": [{"action": "select", "selector": "#choice", "value": selection, "assertions": {"#result": {"contains": [expected]}}}]}]}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        started = time.perf_counter()
        checks, issues, errors = _run_browser(page, path.as_uri(), contract)
        duration = time.perf_counter() - started
        browser.close()
    print(f"selection={selection!r}, elapsed={duration:.3f}s")
    assert checks and not issues and not errors
    return duration


def test_value_does_not_wait_for_a_nonexistent_label(tmp_path):
    duration = exercise(tmp_path, '<option value="L-01">星港制造</option><option value="L-02">云帆零售</option>', "L-02", "L-02")
    assert duration < 3.0, "Known option values must not incur the five-second label timeout"


def test_label_keeps_priority_when_another_option_has_the_same_value(tmp_path):
    exercise(tmp_path, '<option value="zero">Zero</option><option value="A">B</option><option value="B">C</option>', "B", "A")
