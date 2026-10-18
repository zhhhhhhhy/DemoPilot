# Codex CLI Core Prompt A/B v1

这个目录冻结 Prompt A/B 实验的输入、变体和结果格式。当前状态是 `pilot_ready`；不会把历史 15/20、增量合并 20/20 或 hard-v2 的 8/8 冒充成 A/B 结果。

## 研究问题

在同一 Codex CLI、同一案例、同一 testdata、同一 acceptance contract 和同一浏览器环境下，结构化意图与 Goal Prompt 是否比只给场景、优先级和 must-have 的弱 Prompt 带来更高的最终可发布率？

## 变体

- `variants/control-legacy.md`：可执行的最小 Prompt，只提供场景、优先级和 must-have，不提供结构化 intent/goal/flow/method 字段；Common file and acceptance rules remain unchanged。
- `variants/treatment-current.md`：当前结构化 Goal Prompt，提供 intent、goal、flow、expected result、evaluation method，并保留完整安全和返工约束。

## 固定条件

- 同一 `evaluation_sets/codex-cli-v1/cases.json`：simple 10、medium 5、hard 5。
- 同一根目录 `testdata/<case-id>` 和同一 `acceptance.json`。
- 同一 Codex CLI 版本、账号、模型、timeout、最大迭代次数和 server revision。
- 每个变体使用全新的 run-scoped workspace；不复用另一变体的产物。
- 结果 JSON、prompt、stdout JSONL、stderr、acceptance、浏览器截图和发布后审计分别保存。

## 主指标

```text
release_success =
publication_status == published
and post_publish_audit_status == passed
and post_publish_fresh_browser_context == true
```

CLI routing、acceptance child/Python 和其他 Harness 阻塞单独统计，不能计入 Builder 能力失败。只有 CLI 已启动、产物进入验收且最终没有发布，才计为 Core Builder output failure。

## 结果目录

```text
results/
├── control-legacy-20261007.json
├── treatment-current-20261007.json
└── report-20261007.md
```

实验计划和停止条件见 [`docs/engineering/ab-evaluation-plan-2026-10-07.json`](../../docs/engineering/ab-evaluation-plan-2026-10-07.json)。执行入口是 `scripts/run_codex_cli_eval_set.py --prompt-profile control-legacy|treatment-current`。
