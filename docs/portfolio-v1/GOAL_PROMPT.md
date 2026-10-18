> 历史材料保留：本页记录v1阶段。当前升级请看[报价可靠性v2](../quotation-reliability-v2/方案.md)，最新结果与原实验分开统计。

# DemoPilot 长期工作目标

你负责把 `D:/worker/DemoPilot` 建设成一个经得起 AI Agent / 后端岗位面试追问的个人项目。最终目的包括产品效果与贡献证据：销售从模糊需求得到经过验收的可操作 Demo；项目负责人能够解释自己的设计、实现决策与改进带来了什么结果。

## 上下文

- 项目身份：`D:/worker/DemoPilot`，原始代码、AI 辅助实现与个人决策需要如实区分。
- 当前范围与验收：`docs/portfolio-v1/目标与验收.md`。
- 产品与贡献：`docs/portfolio-v1/项目说明与个人贡献.md`。
- 实现入口：`backend/src/demopilot/{main,runtime,storage,core_loop,core_harness,core_acceptance,run_metrics}.py` 和 `providers/codex_cli.py`。
- 基础评测：`evaluation_sets/codex-cli-v1/cases.json`、根目录 `testdata/<case-id>/`；20 例，simple/medium/hard = 10/5/5。
- 困难流程评测：`evaluation_sets/codex-cli-v2-hard/`；8 例，与前面的 20 例分开统计。
- 意图实验：`scripts/run_sales_intent_paired_real.py`、`scripts/run_sales_intent_agent_pilot.py`；销售回答放在 runner-only 的 `evaluation_sets/sales-intent-v1/sales-clarifications/`。
- 指标复算：`scripts/collect_portfolio_evidence.py`；输出 `docs/portfolio-v1/evidence/portfolio-evidence.json`。
- 失败历史：`docs/ITERATION_METHODS.md` 和 `docs/engineering/failure-analysis-2026-10-07.md`；不要用旧报告代替当前运行事实。
- 面试交付：`docs/portfolio-v1/简历项目描述.md`、`面试讲稿与追问.md`、`指标与实验报告.md`、`项目总览.md`。

## 工作方式

先核对当前代码和进程，再从当前工程状态接续。完成可以自主执行的内部修复，不把常规调试、日志路径和协议状态作为用户的决策负担。用户应看到目标、贡献、已得到的效果和距离目标的实际差距。

Core 的目标输入必须包含：context 和测试数据位置、销售确认的目标、预期页面行为、功能验收方式、允许修改的目录。Core 在内部持续生成、测试、修复；中间自行恢复的失败记录为返工，不能冒充最终任务失败。独立评分之后不能悄悄修页面再覆盖原评分。

## 具体产出

1. 三模块目标架构与当前实现边界，明确意图问询实验链路和产品页面接入的区别。
2. 可运行的后端与 Core，包含持久化状态、真实 CLI 调用、取消/超时、过程记录和测试决定的发布状态。
3. 可重算的评测报告，至少给出最终业务通过率、首次通过率、Core 返工、CLI 调用、可见 token、耗时与失败环节。
4. 一页项目介绍、简历 3 条、30 秒/2 分钟讲稿、常见追问与证据入口。
5. 下一阶段路线，每项包含原因、可交付结果、验收方式与停止条件；不为了丰富简历任意堆积框架。

## 怎么评价目标是否达成

- 贡献是否闭合：每项均有“原先问题 → 本人设计/改进 → 工程产出 → 可验证结果”，能打开代码与原始结果对应。
- 评测是否有效：初始话术相同，有无询问是唯一目标差异；Core 模型、fixture、预算和检查规则相同；完整分母、所有 fixture、输出记录都保留。B 的询问成本也计入。
- 后端是否可靠：真实进程超时/取消有界结束；已有输出保存；终态不重复执行；隐藏结果不能通过发布文件路由获得。
- 面试是否诚实：不将增量补测称作单批 100%，不将 prompt 小样本称作意图准确率，不将 token 缺失称作零，也不声称未测量的客户收益、并发规模或强隔离。
- 最终效果允许提升、持平或下降。无法得出提升时，明确结论与原因，给出下一次可区分原因的实验，不制造有利指标。
- 完成与否取决于这些用户可检验的产出，不能单凭内部流程文档的 completed 字段宣布全部目标实现。
