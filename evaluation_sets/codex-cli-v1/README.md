# DemoPilot Codex CLI Agent Core 评测集 v1

这个评测集只测一件事：本地已登录的 Codex CLI 能否把明确的 Goal Prompt 和本地测试数据变成可运行、可复核的静态 Demo。它不是生产系统接入测试，也不把“模型说自己完成了”当成证据。

## 规模与难度

| 层级 | 数量 | 判定依据 |
| --- | ---: | --- |
| simple | 10 | 1–2 个业务阶段；选择输入不单独增加难度 |
| medium | 5 | 3–5 个业务操作，含筛选、详情或一次状态联动 |
| hard | 5 | 至少 6 个操作，并含分支、错误阻断、跨实体状态或审计 |

`cases.json` 为每个用例固定了 `intent`、`goal`、`flow_steps`、`must_haves`、`acceptance_criteria` 和 `evaluation_method`。运行器把这些字段写入 `DemoRequest.evaluation_*`，再完整放入 Core Builder 的 Goal Prompt。

## 根目录 testdata

项目根目录的 [`testdata/`](../../testdata/) 是唯一的运行时测试数据入口。每个用例都有独立目录：

```text
testdata/<case-id>/
├── inputs.json       # 本地输入、fixture 清单和相对路径
├── acceptance.json   # 可执行的可见 UI 验收契约
├── manifest.json     # 输入、契约和图片的 SHA-256
└── assets/           # 该用例需要的公开合成素材
```

`acceptance.json` 至少包含意图、目标、流程、预期结果、评估方式、控件、测试步骤和安全策略。每个测试步骤必须使用安全 selector 和 `click`、`fill`、`select` 之一；每个 assertion 必须检查可见 UI。`scripts/materialize_testdata.py --check` 会检查 20 个目录、10/5/5 分层、契约字段、selector/action、fixture 存在性和 SHA-256；当前检查结果为 `passed`。

发票用例的 10 张 JPG 来自公开的合成发票数据集，文件按 SHA-256 固定在 `invoice-manifest.json` 并复制进对应的 `testdata` 目录。`invoice-gold.json` 只用于以后单独的数据抽取实验，不会进入 Goal Prompt、`testdata` 运行副本或 CLI 子进程。

## Core Builder loop

`evaluation_mode=core_generation` 只走三段：

```text
意图获取 → Core Builder Goal Prompt 循环 → 前端展示
```

每一轮 Codex CLI 的工作目录是 `.data/runs/<run-id>/core-workspace/`，只允许写：

```text
card/
card-web/
testdata/<case-id>/   # 仅用于派生显示数据，inputs.json、acceptance.json 和素材受 hash 保护
```

Prompt 会给出准确的 `inputs.json`、`acceptance.json` 和素材路径，要求使用本地数据，不得调用外部 OCR、API、数据库或网络。CLI 对话的 `prompt.txt`、原始 `stdout.jsonl`、`stderr.log`、每轮验收 JSON 和 Chromium 截图全部保存在运行证据目录中。

验收顺序是：

1. Core Builder 先按 Goal Prompt 生成或修复 `card-web`。
2. 优先要求 CLI 原生 `spawn_agent` 运行项目内的 `acceptance_checker`。
3. 如果当前非交互 CLI 只返回空 `wait`、没有真实 spawn 事件，或者 spawn 事件没有伴随验收命令证据，Harness 会在同一轮启动只读的 Codex CLI acceptance child；该子进程必须实际执行 `python scripts/core_acceptance_cli.py --workspace ... --case-id ...`，退出码和 JSONL command event 会被解析，子进程不能写文件。
4. 受信任的 Core Acceptance Runner 再用 Playwright Chromium 执行 `testdata/<case-id>/acceptance.json` 中的每个路径，并检查控制台错误、文件范围、素材 hash 和最新源 hash。
5. 任何一项失败都保留当前文件与全部对话/验收证据，带着具体反馈进入下一轮。超过最大轮次则状态为 `cannot_complete`，保持隐藏。

只有真实 CLI 文件落盘、验收子智能体证据、静态安全检查和 Chromium 全部通过，才会复制到 `artifacts/demo` 并把 `publication_status` 设为 `published`。Core loop 不使用独立 Reviewer；验收 child 和确定性 Runner 就是发布门禁。其他 Harness 只需实现 `HarnessAdapter` 的 Builder 与 read-only acceptance child 接口即可接入。

## 运行

先只检查数据集，不启动模型：

```powershell
uv run --project backend python scripts/materialize_testdata.py --check
uv run --project backend python scripts/run_codex_cli_eval_set.py --dry-run
```

启动 DemoPilot 后运行一个真实用例：

```powershell
uv run --project backend python scripts/run_codex_cli_eval_set.py --case-id simple-receipt-summary-01 --real
```

也可以按层级或完整 20 个用例顺序运行：

```powershell
uv run --project backend python scripts/run_codex_cli_eval_set.py --tier simple --real
uv run --project backend python scripts/run_codex_cli_eval_set.py --real
```

运行器拒绝 Mock，要求后端报告 `codex_cli=true`，每个用例写入新的结果 JSON；失败、超时、隐藏和返工记录都保留在结果与 `.data/runs/` 中。结果中的 `publication_status`、`browser_status`、`subagent_execution_mode` 和 `subagent_spawn_count` 用来区分真实证据与未完成状态，不能手工把失败 JSON 改成通过。
