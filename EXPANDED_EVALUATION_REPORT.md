# DemoPilot 真实 Demo 扩充报告

更新时间：2026-08-28

## 结果

DemoPilot 已把正式真实 DeepSeek Demo 从 4 个扩充到 **11 个**，覆盖建筑施工、航空运行、汽车服务、智慧农业、公共服务、数字内容、碳排管理、医药供应链、客户服务、人力资源和 B2B 销售 11 个不重复行业场景。

这些不是 Mock，也不是把一次批量测试拆成多个 Demo。每一项都对应一次独立的 DeepSeek Agent Team 生成任务，并同时通过产物校验、Chromium 真实点击和 Reviewer Quality Gate。

## 验收数据

| 指标 | 结果 |
| --- | ---: |
| 正式成功 Demo | 11 |
| 不重复行业 | 11 |
| DeepSeek Agent 调用合计 | 115 |
| 平均 Agent 调用 | 10.5 |
| 返修合计 | 13 |
| 平均返修 | 1.2 |
| 浏览器通过 | 11/11 |
| Quality Gate 通过 | 11/11 |
| ZIP 交付包 | 11/11 |

这里的 11/11 是**经筛选后的正式成果目录完整率**，不是对 DeepSeek 随机任务成功率的估计。失败尝试已移出正式目录并归档，不计为 Demo。

## 本轮 Harness 改进

真实扩充暴露出三个重复问题：点击 selector 被放在非原生 `div`、冻结控件被直接隐藏、导航名称与契约视图 ID 不一致。Harness 新增了以下确定性阻断：

- click 必须落在原生 button/a/input；
- 冻结步骤控件不得直接隐藏；
- 每个契约视图必须存在；
- 每个导航必须使用精确的 `data-target="contract-view-N"` 映射；
- selector ID 必须全页唯一。

这些规则在写盘和启动 Chromium 前执行；标准没有放宽，浏览器仍负责最终行为验收。

精确路由规则上线后，又用此前失败的销售机会场景做了真实回归。新版本首版即通过路由预检，1 次定向返修后完成 Chromium 与 Quality Gate 验收，证明规则已进入真实模型链路。

## 工程回归边界

固定评测集已扩为 30 条。Mock 30 用例回归只验证 Harness 与验证器没有工程回归，不属于真实 Demo，也不进入本报告的 11 个成果。正式清单及 run ID 见 [真实 Demo 清单](docs/REAL_DEMO_CATALOG.md)。
