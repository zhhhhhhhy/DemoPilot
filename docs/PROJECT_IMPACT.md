# DemoPilot 项目影响与简历证据

> 2026-10-16：下面保留早期项目说明。当前面向简历的主入口为 [项目总览](portfolio-v1/项目总览.md)，个人贡献与实现边界见 [项目说明](portfolio-v1/项目说明与个人贡献.md)，数字以 [指标报告](portfolio-v1/指标与实验报告.md) 和可复算 JSON 为准。早期“尚未测量”等状态需要按新报告核对。

## 项目背景

一次性让模型生成一个能点击的页面，并不能证明它完成了业务目标。模型可能没有读取测试数据，页面可能只在当前环境中能运行，也可能在修复一个问题时破坏已经通过的流程。DemoPilot 要解决的是：如何把一个自然语言目标交给本地 Codex CLI，让它在受限工作区内生成静态 Demo，并用真实浏览器、可执行验收合同和发布后复测判断结果是否真的可交付。

本项目的评测对象是 Agent Core 的生成能力，不把 Mock 运行当作模型质量证据。评测集包含 20 个真实 CLI 案例：10 个 simple、5 个 medium、5 个 hard，并为每个案例固定意图、目标、流程、测试数据和可见 UI 验收方式。

## 当前架构

本项目保留两条执行模式：完整售前 Demo 的旧链路包含 Brief、Manager、Discovery、Product、Experience、Contract、Builder、Runner 和 Reviewer；本项目当前关注的 Core 评测链路是：

```text
意图与评测集
→ Goal Prompt
→ Codex CLI Core Builder loop
→ 子验收证据 + 父进程 Chromium Builder Gate
→ candidate 隔离
→ 新浏览器上下文 post-publish audit
→ published / hidden / cannot_complete
```

Core Builder 通过 `HarnessAdapter` 接入 Codex CLI，因此未来可以替换其他 CLI 或 Agent 框架。运行时声明三根允许写入目录 `card/`、`card-web/`、`testdata/<case-id>/`，结束后再做路径审计和哈希校验。每轮保留 `prompt.txt`、`stdout.jsonl`、`stderr.log`、验收 JSON 和 Chromium 截图。只有 Builder Gate 与发布后新浏览器审计都通过，产物才进入 `published`。

## 真正的工程难点

1. **生成结果不能靠模型自报完成。** 必须把自然语言目标编译成可执行的 selector、动作和可见结果，并让受信任的 Harness 决定发布状态。
2. **离线数据和安全边界必须同时成立。** `file://` 浏览器环境不能依赖运行时 `fetch`；允许模型写文件，但不能修改验收合同、原始素材或项目其他目录。
3. **多轮返工需要保持已通过行为。** 只修复当前报错可能让功能、静态安全和状态机在不同轮次之间互相回归。
4. **必须区分模型问题和调用链路问题。** CLI workspace routing、Python 子进程环境和 Builder 生成质量属于不同故障域，不能合并成一个模型成功率。
5. **证据必须可以复盘。** 失败案例要保留原始运行、每轮 Prompt、CLI transcript、验收结果、截图和发布状态，而不是只保留最后一句“完成”。

## 已完成的贡献与已验证结果

### 贡献一：把意图变成可验收的 Goal Prompt

为每个评测案例传入 intent、goal、flow、expected result、evaluation method 和本地 testdata 路径，建立固定的 Agent Core 评测合同。

证据：`evaluation_sets/codex-cli-v1/cases.json`、`testdata/<case-id>/acceptance.json`、`scripts/run_codex_cli_eval_set.py`。

### 贡献二：实现受限写入和 fail-closed 发布门

Core Builder 只能在 run-scoped workspace 中工作；验收合同和素材用 SHA-256 保护。Builder 失败、越权写入、静态安全问题、Chromium 失败或发布后复测失败都会保持隐藏，不允许模型自报发布。

证据：`backend/src/demopilot/core_loop.py`、`backend/src/demopilot/core_acceptance.py`、`.data/runs/<run-id>/`。

### 贡献三：把验收子智能体从“自报”改成可验证证据

当非交互 Codex CLI 没有产生真实 `spawn_agent` 事件时，Harness 启动只读 acceptance child，并解析它是否实际执行验收命令。子验收只负责静态契约证据；真实 UI 交互由父进程 Playwright Chromium 在 Builder Gate 和发布后各执行一次。

证据：`backend/src/demopilot/core_harness.py`、`scripts/core_acceptance_cli.py`、`docs/ITERATION_METHODS.md` 的 IT-004。

### 贡献四：用失败台账证明定向修复的效果

基线真实运行包含 20 个 terminal cases：15 个发布、5 个隐藏，基线发布率为 `15/20 = 75%`。其中 2 个是 Codex CLI 在生成前的 workspace routing 失败，3 个是 Builder 已生成页面后无法同时满足功能、离线和安全门禁。

针对三类 Builder 失败，Goal Prompt 增加了离线 fixture 常量、禁止运行时网络/文件读取、禁止内联脚本和内联事件、必须在安全修复后重跑完整合同并保持已通过状态机。针对一次验收子进程环境错误，改用项目虚拟环境 Python `-S`。

真实复测结果：第一批五案恢复 4/5，合并证据为 `19/20 = 95%`；最后一个补货案例在验收环境修复后通过，当前增量合并证据为 `20/20 = 100%`，相对基线提升 25 个百分点。

证据：

- [基线结果](../evaluation_sets/codex-cli-v1/results/full-real-post-audit-20261006.json)
- [第一批失败复测](../evaluation_sets/codex-cli-v1/results/failure-followup-20261007.json)
- [补货最终复测](../evaluation_sets/codex-cli-v1/results/failure-followup-replenishment-v3-20261007.json)
- [五案失败分析](engineering/failure-analysis-2026-10-07.md)

## 目前能写进简历的结论

可以写成：

> 设计并实现面向本地 Codex CLI 的 Agent Core Demo 生成与评测闭环：将 20 个分层 Goal Prompt 转换为受限 workspace 任务，通过 SHA-256 测试数据保护、只读验收子智能体、Playwright Chromium 双阶段门禁和 fail-closed 发布控制，保留每轮 CLI transcript 与浏览器证据；针对 5 个真实失败案例完成根因分型和定向修复，将增量合并发布率从基线 15/20（75%）提升到 20/20（100%）。

这句话必须带上“增量合并”限定，不能写成“修复后一次性 20/20”。也不能把 2 个 CLI 路由失败写成模型生成质量问题。

## 还不能写成已验证结论的内容

- 还没有修复后同一 server revision 下的一次性全 20 案例分数。
- 还没有完成原始 Prompt 与改进 Prompt 的严格 A/B 对照，因此不能把全部提升归因于 Prompt 改进。
- 还没有测量 token、耗时、调用次数、每层难度的稳定性和跨 Provider 泛化。
- 前端 AgentTimeline 和结果证据卡仍主要沿用旧 full_pipeline 映射，Core 的 acceptance/post-publish 事件没有完整独立展示；这是展示层债务，不影响后端门禁证据。

## 下一项值得做的工作

下一步不是继续堆 Demo，而是跑一次冻结条件下的对照实验：同一批 20 个案例、同一 Codex CLI、同一 timeout 和同一验收合同，分别使用原始 Prompt 与改进 Prompt，比较最终发布率、Core Builder 结果失败率、CLI/Harness 阻塞率、平均迭代次数、平均 CLI 调用数、浏览器门禁拦截数和每层难度通过率。只有这个实验完成后，才能把“我的 Prompt/Harness 设计带来了提升”写成强因果简历证据。

为检验更高难度的能力边界，已另建 `evaluation_sets/codex-cli-v2-hard/`，包含 8 个独立案例。每个案例有 8–10 个阶段、3 个实体、正向/非法/分支/隔离四类可执行 journey、阈值或角色规则、审计要求和终态锁定。v2 不并入 v1 的 20-case 分母；8/8 都经过真实 Codex CLI、Core acceptance、Chromium 四类 journey 和 fresh post-publish audit 后发布，6 个案例共发生 9 次 Builder 返工。这个结果证明当前闭环可运行，但由于 fixtures 和业务断言仍偏通用，不能单独证明真实业务难度，也不是 Prompt A/B 因果结论。证据见 `docs/engineering/hard-v2-ab/full-real-2026-10-07.json`。
