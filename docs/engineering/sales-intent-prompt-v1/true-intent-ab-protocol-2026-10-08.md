# 销售一句话与真实意图询问：A/B 实验协议

## 这次真正要回答的问题

销售只说一句不完整的话时，系统直接把这句话交给 Core Builder，和系统先向销售追问、拿到补充信息、再把整理后的意图交给 Core Builder，最终发布结果有什么差别？

比较的是完整产品链路：

```text
一句话销售描述
  ├─ A：直接交给 Core Builder
  └─ B：意图模块追问销售 → 销售回答 → 形成结构化意图 → 交给同一个 Core Builder
```

两条链路都必须经过同一套 Core 迭代、独立业务验收、真实浏览器检查和发布门槛。

## 先声明：v3 不是这次实验的有效结果

`paired-real-v3-2026-10-08.md` 中的 `raw-sales` 和 `intent-agent` 都收到了同一份已经拼接了目标、操作顺序、验收要求和样例数据的 `raw_sales_brief`。因此 v3 没有比较“未询问的一句话”和“询问后的完整意图”，只比较了“同一份已补全的文字”与“同一份文字再经过结构化整理”。

v3 的 `1/3` 与 `2/3` 不能作为本次真实意图询问效果的结论。它可以保留为历史的“结构化整理工程试验”，但不能被写成意图识别模块提升最终通过率的证据。

## 固定条件

- 同一批 case、同一版本代码、同一 Codex CLI、同一模型和 reasoning effort。
- A、B 两条链路使用相同的 Core Builder prompt、最大返工轮数、testdata、浏览器、发布规则和独立验收器。
- 每个 case 各运行一次 A 和一次 B；两条链路的执行顺序按冻结的随机顺序保存。
- `gold/intent-gold.json`、完整 `acceptance.json` 和独立验收答案只给可信 runner，不进入意图模块或 Core Builder 的上下文。
- 每个分支都保留完整对话、Core CLI JSONL、返工提示、运行状态、浏览器截图和发布状态。
- 失败分支留在分母中；意图模块追问失败、工作区路由失败、Core 失败、浏览器失败和业务功能失败必须分开标记。

## A 分支：销售只提供一句话

A 分支的 Core 输入必须是 `cases.json` 中的原始 `raw_sales_brief`，不能追加 source case 的 `goal`、`flow_steps`、`acceptance_criteria`、`clarification_answers` 或 evaluator gold。

它模拟“销售只说了一句话，系统不询问，直接开始生成”。Core 可以依据一句话和普通 demo fixture 自己做合理实现，但不能得到销售没有说出的价格规则、状态规则、审批细节或验收答案。Runner 挂载的 `inputs.json` 只保留 `schema_version`、`case_id`、`industry`、`fixtures` 和 `assets`；其中的 `scenario`、`audience` 不会重复提供给模型，避免 fixture 反向泄露完整意图。

## B 分支：真实意图模块询问销售

B 分支必须按下面的顺序运行：

1. 意图模块第一次只收到和 A 分支完全相同的原始一句话。
2. 如果关键信息缺失，意图模块必须输出 `status=needs_clarification` 和具体问题；不能自行补齐。
3. 可信 runner 根据该 case 冻结的销售回答脚本回答问题。回答脚本是“销售可提供的业务事实”，不是 evaluator gold，也不包含 selector、断言实现或隐藏验收文字。
4. 意图模块把前一轮问题和销售回答放入下一轮上下文，继续追问仍会改变 Demo 的信息。
5. 只有 `status=ready`、无未解决问题、每个关键字段有来源证据的结构化意图，才允许进入 Core Builder。
6. Core Builder 只额外收到 B 分支的结构化意图和同一份普通 fixture；它不收到完整 `acceptance.json` 或 evaluator gold。A、B 的 fixture 挂载字段完全一致。

如果意图模块没有提出本该询问的问题，B 分支不能由 runner 自动把答案塞进结果；该分支按“意图未获取完整”记录。这样才能测出询问能力，而不是把人工整理后的答案伪装成模型能力。

## 销售回答脚本

回答脚本放在 `evaluation_sets/sales-intent-v1/sales-clarifications/<case_id>.json`，不要放进 Core 可读的 demo `testdata`。它是 runner-only 的销售回答输入，不是页面测试数据；Core Builder 和独立验收器的模型子进程都不能读取它。每个回答包含：

- `question_topic`：问题主题，如价格规则、必填字段、审批分支。
- `answer`：销售自然语言回答，只有业务事实和演示范围。
- `required_before_core`：如果为 `true`，意图模块未确认该信息时不能进入 Core。
- `allowed_question_aliases`：用于 runner 把模型问题归类到主题；只做记录和发放答案，不给模型看 gold id。

回答脚本必须覆盖每个 case 的关键缺失信息，但不能直接写成浏览器断言。例如可以回答“基础套餐每席位 100，专业套餐每席位 200，按席位数计算，标注演示估算”，不能回答“点击 `#price` 后断言文本为……”。如果实现上必须让文件位于 `testdata`，runner 必须在每次 Core/acceptance 子进程前将其移出或遮蔽，并在调用后检查模型没有读取或修改它。

## 最终验收指标

### 主要指标

1. **最终通过率**：`published + independent_business_audit_passed + fresh_browser_passed / 全部 case 数`。
2. **成对通过差**：每个相同 case 的 B 结果减 A 结果，逐 case 列出。

### 次要指标

- Core 首轮通过率。
- Core 返工轮数总和、平均值和中位数。
- Core CLI 调用次数；B 分支另列意图 CLI 调用次数和追问轮数。
- 意图模块：问题是否覆盖冻结的必要主题、是否凭空添加事实、是否保留销售回答来源。
- 各失败边界的数量：意图询问、Core 生成、Core 内部返工、独立业务验收、浏览器/发布。

意图字段的匹配分数只能作为诊断指标，不能把 B 分支失败的 case 从最终通过率分母中删除。

## 通过条件

这次实验只在以下证据齐全时报告：

- A、B 每个 case 都有终态，或明确记录为 collector failure 并保留在分母。
- A、B 的原始输入、销售回答、意图对话、Core 请求和发布结果可追溯。
- 独立验收器在两个分支都使用相同的完整业务验收和 fresh browser context。
- 报告明确区分“询问销售获取信息带来的提升”和“仅仅把文字结构化带来的提升”。

只有当 B 在同一批 case 上提高最终通过率，或在最终通过率相同的情况下减少 Core 返工，才能说这批样本观察到改善。样本量扩大前不能宣称普遍因果效果。

## 本实验完成后的报告格式

报告必须先给结论边界，再给表格：

| 指标 | A：一句话直达 Core | B：询问后再交给 Core | B-A |
| --- | ---: | ---: | ---: |
| 最终发布且独立验收通过 | 待运行 | 待运行 | 待运行 |
| Core 返工总轮数 | 待运行 | 待运行 | 待运行 |
| Core CLI 调用总数 | 待运行 | 待运行 | 待运行 |
| 意图询问轮数 | 0 | 待运行 | 待运行 |

结论必须使用“在这批 case 上观察到……”或“没有观察到……”；不能把 v3 的结果填入本表。
