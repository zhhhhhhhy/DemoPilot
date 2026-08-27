from __future__ import annotations

import html
import json
from pathlib import Path

from .harness import SandboxWorkspace
from .interaction_contract import contract_tests
from .models import Artifact, DemoRun


def _safe(value: str) -> str:
    return html.escape(value, quote=True)


def _label(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("title", "name", "label", "step", "action", "feature", "summary", "description"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _labels(value: object, fallback: list[str], *, maximum: int = 12) -> list[str]:
    if isinstance(value, dict):
        acts = [
            item
            for key, item in value.items()
            if str(key).lower().replace("_", "").startswith("act")
        ]
        value = acts or list(value.values())
    if not isinstance(value, list):
        return fallback
    expanded: list[object] = []
    for item in value:
        if isinstance(item, dict) and item and all(str(key).startswith("act") for key in item):
            expanded.extend(item.values())
        else:
            expanded.append(item)
    labels = [_label(item)[:160] for item in expanded]
    cleaned = [item for item in labels if item]
    return cleaned[:maximum] or fallback


def _contract_fallback_parts(run: DemoRun) -> tuple[str, str, str]:
    contract = run.outputs.get("interaction_contract", {})
    requirements = (
        contract.get("requirements", []) if isinstance(contract, dict) else []
    )
    nav_items: list[str] = []
    views: list[str] = []
    for item in requirements if isinstance(requirements, list) else []:
        if not isinstance(item, dict):
            continue
        requirement = _safe(str(item.get("requirement", "业务能力")))
        screen = _safe(str(item.get("screen", "业务工作台")))
        route = item.get("route", {})
        nav_id = str(route.get("nav_selector", "")).removeprefix("#")
        view_id = str(route.get("view_selector", "")).removeprefix("#")
        if not nav_id or not view_id:
            continue
        nav_items.append(
            f'<button id="{_safe(nav_id)}" class="nav-item contract-nav" '
            f'data-contract-view="{_safe(view_id)}">{requirement}</button>'
        )
        controls: list[str] = []
        for element in item.get("elements", []):
            if not isinstance(element, dict):
                continue
            element_id = str(element.get("selector", "")).removeprefix("#")
            action = str(element.get("control", "click"))
            purpose = _safe(str(element.get("purpose", "执行业务动作")))
            value = _safe(str(element.get("value", "演示值")))
            if action == "fill":
                controls.append(
                    f'<label>{purpose}<input id="{_safe(element_id)}" '
                    f'aria-label="{purpose}" placeholder="请输入演示值" /></label>'
                )
            elif action == "select":
                controls.append(
                    f'<label>{purpose}<select id="{_safe(element_id)}" '
                    f'aria-label="{purpose}"><option value="">请选择</option>'
                    f'<option value="{value}">{value}</option></select></label>'
                )
            else:
                controls.append(
                    f'<button id="{_safe(element_id)}" class="contract-action">'
                    f'{purpose}</button>'
                )
        test = item.get("test", {})
        assertion = test.get("assertion", {}) if isinstance(test, dict) else {}
        result_id = str(assertion.get("selector", "")).removeprefix("#")
        views.append(
            f'<article id="{_safe(view_id)}" class="panel contract-view">'
            f'<span class="eyebrow">SHARED CONTRACT</span><h3>{screen}</h3>'
            f'<p>{requirement}</p><div class="contract-controls">{"".join(controls)}</div>'
            f'<div id="{_safe(result_id)}" class="contract-result">等待操作</div></article>'
        )
    runtime = json.dumps(contract_tests(contract), ensure_ascii=False)
    return "".join(nav_items), "".join(views), runtime


def generate_artifacts(
    run: DemoRun,
    run_dir: Path,
    workspace: SandboxWorkspace | None = None,
) -> list[Artifact]:
    workspace = workspace or SandboxWorkspace(run, run_dir)
    request = run.request
    product = run.outputs.get("product", {})
    builder = run.outputs.get("builder", {})
    reviewer = run.outputs.get("reviewer") or run.outputs.get("qa", {})
    features = _labels(
        product.get("features"),
        request.must_haves or ["数据总览", "核心流程", "结果导出"],
    )
    story = _labels(
        product.get("demo_story"),
        ["发现问题", "执行任务", "验证价值"],
        maximum=6,
    )
    contract_nav_html, contract_views_html, contract_runtime = _contract_fallback_parts(run)

    index_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="DemoPilot 为 {_safe(request.client_name)} 生成的受控演示" />
  <title>{_safe(request.project_name)} · 客户演示</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <div class="demo-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">D</span><span>DemoPilot</span></div>
      <nav aria-label="演示导航">
        <button class="nav-item active" data-view="overview">概览</button>
        <button class="nav-item" data-view="workspace">工作区</button>
        <button class="nav-item" data-view="insights">洞察</button>
        {contract_nav_html}
      </nav>
      <div class="fixture-note"><strong>演示数据</strong><span>未连接客户生产系统</span></div>
    </aside>
    <main>
      <header>
        <div><span class="eyebrow">{_safe(request.industry)} · SALES DEMO</span>
        <h1>{_safe(request.project_name)}</h1></div>
        <button id="advanceButton" class="primary-button">推进演示</button>
      </header>
      <section class="hero-card">
        <div><span class="status-pill">方案已就绪</span>
        <h2>让复杂工作，变成清晰的下一步。</h2>
        <p>{_safe(request.scenario)}</p></div>
        <div class="score"><strong>{len(features)}</strong><span>项核心能力*</span></div>
      </section>
      <section class="metrics" aria-label="演示指标">
        <article><span>待处理事项</span><strong id="taskCount">12</strong><em>集中呈现</em></article>
        <article><span>关键流程</span><strong>{len(story)}</strong><em>一条主线</em></article>
        <article><span>方案覆盖</span><strong>{len(features)}</strong><em>核心能力</em></article>
      </section>
      <section class="content-grid">
        <article class="panel">
          <div class="panel-heading"><div><span class="eyebrow">LIVE WORKFLOW</span><h3>今日任务流</h3></div><span id="progressLabel">1 / {len(story)}</span></div>
          <div id="timeline" class="timeline"></div>
        </article>
        <article class="panel insight-panel">
          <span class="eyebrow">AI INSIGHT</span><h3>把注意力放在最有价值的节点</h3>
          <p>系统已将需求整理成一条可讲解、可操作、可验证的演示路径。</p>
          <div id="featureChips" class="chips"></div>
        </article>
      </section>
      <section class="contract-grid" aria-label="共享交互协议工作区">{contract_views_html}</section>
      <footer>* 能力数量来自本次 Demo Brief；页面使用受控样例数据，不代表真实客户收益。</footer>
    </main>
  </div>
  <script src="app.js"></script>
</body>
</html>
"""
    styles_css = f""":root {{
  color: #1d1d1f; background: #f5f5f7; font-family: -apple-system, BlinkMacSystemFont,
  "SF Pro Display", "PingFang SC", "Segoe UI", sans-serif; --accent: {request.primary_color};
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; background: radial-gradient(circle at 70% 0%, #fff 0, #f5f5f7 46%, #ececf0 100%); }}
button {{ font: inherit; }}
.demo-shell {{ min-height: 100vh; display: grid; grid-template-columns: 240px 1fr; }}
.sidebar {{ padding: 30px 20px; border-right: 1px solid rgba(0,0,0,.06); background: rgba(255,255,255,.68); backdrop-filter: blur(24px); display: flex; flex-direction: column; }}
.brand {{ display:flex; align-items:center; gap:10px; font-weight:700; letter-spacing:-.02em; padding:0 10px 34px; }}
.brand-mark {{ width:31px; height:31px; border-radius:10px; color:#fff; background:linear-gradient(145deg,var(--accent),#72b7ff); display:grid; place-items:center; box-shadow:0 8px 20px color-mix(in srgb,var(--accent) 25%,transparent); }}
nav {{ display:grid; gap:6px; }} .nav-item {{ text-align:left; border:0; background:transparent; padding:11px 13px; border-radius:11px; color:#6e6e73; cursor:pointer; }}
.nav-item.active {{ color:#1d1d1f; background:rgba(0,0,0,.055); font-weight:600; }}
.fixture-note {{ margin-top:auto; padding:14px; background:#f5f5f7; border-radius:14px; display:grid; gap:4px; font-size:12px; color:#6e6e73; }}
.fixture-note strong {{ color:#1d1d1f; }} main {{ padding:32px 5vw 22px; max-width:1440px; width:100%; margin:auto; }}
header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; }} h1 {{ font-size:32px; letter-spacing:-.04em; margin:6px 0 0; }}
.eyebrow {{ color:#86868b; font-size:11px; font-weight:700; letter-spacing:.12em; }} .primary-button {{ border:0; color:#fff; background:var(--accent); padding:11px 18px; border-radius:999px; font-weight:600; cursor:pointer; box-shadow:0 8px 24px color-mix(in srgb,var(--accent) 25%,transparent); }}
.hero-card {{ min-height:270px; padding:40px; color:#fff; border-radius:28px; background:linear-gradient(135deg,#151517,#303036 55%,color-mix(in srgb,var(--accent) 52%,#17171a)); display:flex; justify-content:space-between; align-items:flex-end; box-shadow:0 24px 60px rgba(0,0,0,.18); overflow:hidden; position:relative; }}
.hero-card:after {{ content:""; position:absolute; width:360px; height:360px; right:-90px; top:-170px; border-radius:50%; background:rgba(255,255,255,.12); filter:blur(4px); }}
.hero-card h2 {{ font-size:clamp(30px,4vw,55px); line-height:1.03; letter-spacing:-.055em; max-width:740px; margin:17px 0 12px; }} .hero-card p {{ max-width:700px; color:#d2d2d7; margin:0; line-height:1.65; }}
.status-pill {{ background:rgba(255,255,255,.14); padding:7px 11px; border-radius:999px; font-size:12px; }} .score {{ display:grid; position:relative; z-index:1; text-align:right; }} .score strong {{ font-size:48px; letter-spacing:-.06em; }} .score span {{ color:#d2d2d7; font-size:12px; }}
.metrics {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:18px 0; }} .metrics article,.panel {{ background:rgba(255,255,255,.78); border:1px solid rgba(0,0,0,.05); border-radius:20px; box-shadow:0 12px 30px rgba(0,0,0,.055); backdrop-filter:blur(18px); }}
.metrics article {{ padding:21px; display:grid; gap:7px; }} .metrics span,.metrics em {{ color:#86868b; font-size:12px; font-style:normal; }} .metrics strong {{ font-size:32px; letter-spacing:-.04em; }}
.content-grid {{ display:grid; grid-template-columns:1.35fr .65fr; gap:18px; }} .panel {{ padding:25px; min-height:280px; }} .panel-heading {{ display:flex; justify-content:space-between; align-items:start; }} h3 {{ font-size:20px; letter-spacing:-.025em; margin:7px 0 18px; }}
.timeline {{ display:grid; gap:10px; }} .timeline-item {{ display:grid; grid-template-columns:34px 1fr auto; align-items:center; gap:12px; padding:12px; border-radius:14px; background:#f5f5f7; }} .timeline-item .number {{ width:30px; height:30px; display:grid; place-items:center; border-radius:50%; background:#fff; color:#86868b; font-size:12px; }} .timeline-item.done .number {{ background:#dff7e8; color:#168447; }} .timeline-item.active {{ background:color-mix(in srgb,var(--accent) 9%,#fff); }} .timeline-item.active .number {{ background:var(--accent); color:#fff; }} .timeline-item span:last-child {{ color:#86868b; font-size:12px; }}
.insight-panel {{ background:linear-gradient(150deg,#fff,#f5f8ff); }} .insight-panel p {{ color:#6e6e73; line-height:1.65; }} .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:24px; }} .chip {{ padding:8px 10px; border-radius:10px; background:#fff; border:1px solid rgba(0,0,0,.06); font-size:12px; }}
.contract-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:18px; margin-top:18px; }} .contract-view p {{ color:#6e6e73; }} .contract-controls {{ display:grid; gap:10px; }} .contract-controls label {{ display:grid; gap:6px; color:#6e6e73; font-size:12px; }} .contract-controls input,.contract-controls select {{ width:100%; border:1px solid #d2d2d7; border-radius:10px; padding:10px; background:#fff; }} .contract-action {{ border:0; border-radius:10px; padding:11px; color:#fff; background:var(--accent); cursor:pointer; }} .contract-result {{ margin-top:14px; padding:11px; border-radius:10px; background:#f5f5f7; color:#6e6e73; }}
footer {{ padding:20px 4px 0; color:#86868b; font-size:11px; }}
@media (max-width:900px) {{ .demo-shell {{ grid-template-columns:1fr; }} .sidebar {{ display:none; }} main {{ padding:22px; }} .hero-card {{ padding:28px; align-items:start; flex-direction:column; }} .score {{ text-align:left; margin-top:28px; }} .content-grid {{ grid-template-columns:1fr; }} }}
@media (max-width:580px) {{ .metrics {{ grid-template-columns:1fr; }} header {{ align-items:flex-start; gap:14px; }} h1 {{ font-size:25px; }} .primary-button {{ white-space:nowrap; }} }}
@media (prefers-reduced-motion:no-preference) {{ .timeline-item,.primary-button {{ transition:transform .25s ease,background .25s ease; }} .primary-button:hover {{ transform:translateY(-1px); }} }}
"""
    app_data = {"story": story, "features": features}
    app_js = f"""const data = {json.dumps(app_data, ensure_ascii=False)};
let current = 0;
const timeline = document.querySelector('#timeline');
const button = document.querySelector('#advanceButton');
const label = document.querySelector('#progressLabel');
const taskCount = document.querySelector('#taskCount');
function render() {{
  timeline.replaceChildren(...data.story.map((step, index) => {{
    const row = document.createElement('div');
    row.className = `timeline-item ${{index < current ? 'done' : index === current ? 'active' : ''}}`;
    const number = document.createElement('span');
    number.className = 'number';
    number.textContent = index < current ? '✓' : String(index + 1);
    const title = document.createElement('strong');
    title.textContent = String(step);
    const status = document.createElement('span');
    status.textContent = index < current ? '已完成' : index === current ? '进行中' : '待处理';
    row.append(number, title, status);
    return row;
  }}));
  label.textContent = `${{Math.min(current + 1, data.story.length)}} / ${{data.story.length}}`;
  taskCount.textContent = String(Math.max(0, 12 - current * 4));
  button.textContent = current >= data.story.length - 1 ? '重新演示' : '推进演示';
}}
document.querySelector('#featureChips').replaceChildren(...data.features.map(item => {{
  const chip = document.createElement('span');
  chip.className = 'chip';
  chip.textContent = String(item);
  return chip;
}}));
button.addEventListener('click', () => {{ current = current >= data.story.length - 1 ? 0 : current + 1; render(); }});
document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', () => {{
  document.querySelectorAll('.nav-item').forEach(nav => nav.classList.remove('active')); item.classList.add('active');
}}));
const sharedContractTests = {contract_runtime};
sharedContractTests.forEach(test => {{
  const result = document.querySelector(test.assertion.selector);
  const successText = (test.assertion.text_contains || []).join(' · ');
  test.steps.forEach((step, index) => {{
    const control = document.querySelector(step.selector);
    if (!control) return;
    if (index === 0) {{
      control.addEventListener('click', () => {{
        const target = document.querySelector(step.selector.replace('nav', 'view'));
        if (target) target.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }});
      return;
    }}
    const eventName = step.action === 'fill' ? 'input' : step.action === 'select' ? 'change' : 'click';
    control.addEventListener(eventName, () => {{ if (result) result.textContent = successText; }});
  }});
}});
render();
"""
    builder_files = builder.get("files")
    required_builder_files = {"demo/index.html", "demo/styles.css", "demo/app.js"}
    uses_builder_files = (
        isinstance(builder_files, dict)
        and required_builder_files.issubset(builder_files)
        and all(isinstance(builder_files[name], str) for name in required_builder_files)
    )
    if uses_builder_files:
        index_html = builder_files["demo/index.html"]
        styles_css = builder_files["demo/styles.css"]
        app_js = builder_files["demo/app.js"]
        source_mode = "agent_generated_files"
    else:
        source_mode = "controlled_template_fallback"
    run.outputs["build_provenance"] = {
        "source_mode": source_mode,
        "builder_supplied_files": sorted(builder_files) if isinstance(builder_files, dict) else [],
        "execution_boundary": "run_scoped_static_web_sandbox",
    }
    workspace.write_text("artifacts/demo/index.html", index_html)
    workspace.write_text("artifacts/demo/styles.css", styles_css)
    workspace.write_text("artifacts/demo/app.js", app_js)

    spec = {
        "meta": {
            "run_id": run.id,
            "provider": request.provider,
            "data_mode": "controlled_fixture",
            "source_mode": source_mode,
        },
        "request": request.model_dump(),
        "agent_outputs": run.outputs,
    }
    workspace.write_text(
        "artifacts/demo-spec.json", json.dumps(spec, ensure_ascii=False, indent=2)
    )
    sales_script = "\n".join(
        [
            f"# {request.project_name} · 销售演示讲解词",
            "",
            f"> 客户：{request.client_name}｜受众：{request.audience}",
            "",
            "## 开场",
            "",
            f"今天我们聚焦一个问题：{request.scenario}",
            "",
            "## 三幕演示",
            "",
            *[f"{index}. {item}" for index, item in enumerate(story, start=1)],
            "",
            "## 收口",
            "",
            "本 Demo 使用受控样例数据。下一步应与客户确认数据源、权限、成功指标和试点范围。",
        ]
    )
    workspace.write_text("artifacts/sales-script.md", sales_script)
    review_issues = reviewer.get("issues", [])
    issue_lines = []
    for item in review_issues:
        if isinstance(item, dict):
            evidence = item.get("evidence") or item.get("message") or "未提供证据"
            issue_lines.append(
                f"- [{item.get('severity', 'medium')}] {evidence}；"
                f"根因：{item.get('root_cause', '待定位')}；"
                f"修复：{item.get('repair_instruction', '待制定')}；"
                f"复验：{item.get('verification', '重新运行验证')}"
            )
        else:
            issue_lines.append(f"- {item}")
    coverage_lines = [
        f"- {item.get('requirement', '未命名需求')}：{item.get('status', 'unknown')}（{item.get('evidence', '无证据')}）"
        for item in reviewer.get("requirement_coverage", [])
        if isinstance(item, dict)
    ]
    qa_report = "\n".join(
        [
            "# DemoPilot Reviewer 独立评审报告",
            "",
            f"状态：{reviewer.get('status', 'not_run')}",
            f"结论：{reviewer.get('decision', 'not_run')}",
            f"证据分：{reviewer.get('overall_score', 'not_scored')} / 100",
            f"置信度：{reviewer.get('confidence', 'not_scored')}",
            "",
            "## 需求覆盖",
            "",
            *(coverage_lines or ["- 尚未完成最终 Reviewer 评审"]),
            "",
            "## 已检查",
            "",
            *[f"- {item}" for item in reviewer.get("checks", [])],
            "",
            "## 问题、根因与复验",
            "",
            *(issue_lines or ["- 未发现触发硬门禁的问题"]),
            "",
            "## 真实交互与模拟能力",
            "",
            f"- 已验证真实交互：{'、'.join(reviewer.get('real_features', [])) or '无'}",
            f"- 样例数据模拟能力：{'、'.join(reviewer.get('simulated_features', [])) or '无'}",
            "",
            "## 演示范围说明",
            "",
            *[f"- {item}" for item in reviewer.get("scope_boundaries", [])],
            "",
            "## 未解决项",
            "",
            *[f"- {item}" for item in reviewer.get("open_gates", [])],
            *([] if reviewer.get("open_gates") else ["- 无"]),
        ]
    )
    workspace.write_text("artifacts/qa-report.md", qa_report)
    readme = (
        f"# {request.project_name}\n\n"
        "打开 `demo/index.html` 即可演示。此包由 DemoPilot 生成，使用受控样例数据，"
        "不代表已连接真实系统或达到生产质量。\n"
    )
    workspace.write_text("artifacts/README.md", readme)

    archive_path = workspace.archive_directory(
        "artifacts", f"{run.id}-demo-package.zip"
    )
    return [
        Artifact(
            name="交互式客户 Demo",
            kind="demo",
            relative_path="artifacts/demo/index.html",
            download_url=f"/api/runs/{run.id}/files/artifacts/demo/index.html",
        ),
        Artifact(
            name="需求与方案规格",
            kind="spec",
            relative_path="artifacts/demo-spec.json",
            download_url=f"/api/runs/{run.id}/files/artifacts/demo-spec.json",
        ),
        Artifact(
            name="销售讲解词",
            kind="script",
            relative_path="artifacts/sales-script.md",
            download_url=f"/api/runs/{run.id}/files/artifacts/sales-script.md",
        ),
        Artifact(
            name="QA 报告",
            kind="qa",
            relative_path="artifacts/qa-report.md",
            download_url=f"/api/runs/{run.id}/files/artifacts/qa-report.md",
        ),
        Artifact(
            name="完整 Demo 包",
            kind="archive",
            relative_path=archive_path.name,
            download_url=f"/api/runs/{run.id}/files/{archive_path.name}",
        ),
    ]
