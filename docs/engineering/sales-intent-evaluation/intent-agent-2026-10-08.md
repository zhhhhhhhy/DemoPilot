# AI intent acquisition smoke（2026-10-08）

这次是第一条真正调用 Codex CLI 进行销售意图获取的链路。输入是 `simple-quote-generator-01` 的原始销售话术，Codex CLI 输出 typed intent，随后先经过 evaluator-only gold 检查；意图门禁不通过时不启动 Core Builder，也不允许发布。

结果：Codex CLI 产出了结构化 JSON，但意图保真度没有达到阈值。

| 指标 | 结果 |
| --- | ---: |
| must-have precision | 0.0000 |
| must-have recall | 0.0000 |
| must-have F1 | 0.0000 |
| flow recall | 0.0000 |
| flow order | 1.0000 |
| constraint recall | 0.0000 |
| problem similarity | 0.4096 |
| outcome similarity | 0.4242 |
| 综合 intent fidelity | 0.3056 |
| 通过阈值（≥0.8 且关键 must-have 全召回） | 否 |

失败位置是**意图获取层**：模型把“套餐选择、席位数量、总价”扩写成多个泛化能力和推测的页面功能，没有保留 gold 中的原子需求和流程。Core Builder 没有开始，因而不存在 Builder、浏览器或发布失败。

这正好说明为什么之前的 3/3 发布不能叫“意图准确率”：之前的结构化意图是人工直接提供的；这次让 AI 从原始销售话术提取后，第一条真实样本就暴露了意图层的缺陷。

原始证据：

- `evaluation_sets/sales-intent-v1/results/intent-agent-20261008/intent-agent-pilot.json`
- `evaluation_sets/sales-intent-v1/results/intent-agent-20261008/simple-quote-generator-01/intent-output.json`
- `evaluation_sets/sales-intent-v1/results/intent-agent-20261008/simple-quote-generator-01/intent-events.json`
- `docs/engineering/sales-intent-evaluation/WORKFLOW_STATE.md`
