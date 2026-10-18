# DemoPilot 简历证据卡

> 2026-10-16：本文件是历史证据卡，不再作为最新简历文案。使用 [当前简历项目描述](portfolio-v1/简历项目描述.md)、[面试讲稿](portfolio-v1/面试讲稿与追问.md) 和 [可核验指标](portfolio-v1/指标与实验报告.md)。旧的测试通过数量与“下一项工作”保留历史含义，不作为本轮验证结果。

## 推荐项目描述

设计并实现可插拔 Harness 的 Codex CLI Agent Core 生成评测闭环：将 20 个真实 Goal Prompt 按 simple/medium/hard 分为 10/5/5，隔离 `testdata` 与可执行 acceptance contract，限制 Builder 的 run-scoped 写入范围，接入真实 Chromium Builder Gate 与 fresh post-publish 双门禁，并持久化每轮 CLI transcript、验收 JSON 和浏览器截图。

针对 5 个真实失败样本建立 before/action/after 台账：区分 2 个 Codex CLI workspace-routing 基础设施失败与 3 个 Builder 产物回归；通过离线 fixture 约束、禁止运行时网络读取、完整合同重跑和验收子进程虚拟环境修复，使首批恢复结果从合并 15/20（75%）达到 19/20（95%），最终增量合并证据达到 20/20（100%，+25 个百分点）。

## 面试时必须说明

- `20/20` 是 15 个原始通过案例加 5 个分别复测案例的增量合并，不是修复后单次全量 20 案例。
- 2 个 workspace-routing 失败发生在 Builder 启动前，不能写成模型生成能力失败。
- 3 个 Builder 失败是最终产物没有同时满足功能、离线和安全门禁；当前证据更支持 Prompt/Harness 约束不足，尚不足以证明基础模型能力上限。
- Core 模式没有独立 Reviewer；发布结论来自受信任验收 Runner、只读 acceptance child 和两次真实 Chromium 门禁。
- hard-v2 已完成 treatment-only 的 8/8 真实运行，但还没有完成统一服务版本下的 Prompt A/B；同时 hard-v2 的业务 fixtures 仍偏通用，所以不能写成“已证明 Prompt 改进造成全部提升”或“已证明真实业务难度”。

## 当前可核验指标

| 指标 | 已验证值 | 证据边界 |
|---|---:|---|
| Core 评测集 | 20（simple 10 / medium 5 / hard 5） | `evaluation_sets/codex-cli-v1/cases.json` |
| 基线发布率 | 15/20 = 75% | `full-real-post-audit-20261006.json` |
| 首批失败复测恢复 | 4/5；合并 19/20 = 95% | `failure-followup-20261007.json` |
| 最终失败案例恢复 | 5/5；合并 20/20 = 100% | `failure-followup-replenishment-v3-20261007.json` |
| 后端回归测试 | 56 passed | 本地 `uv run --project backend pytest -q` |
| 测试数据完整性 | 20 cases，10/5/5，检查通过 | `scripts/materialize_testdata.py --check` |
| hard-v2 treatment run | 8/8 发布；6 个案例返工，共 9 次 revision | `docs/engineering/hard-v2-ab/full-real-2026-10-07.json` |

## 不应混用的另一套指标

README 和 `docs/REAL_DEMO_CATALOG.md` 中的 23 个正式 Demo、23/23 Chromium、23/23 Quality Gate、255 次调用和 33 次定向返修属于旧的 DeepSeek Agent Team 正式 Demo 集合，不是本次 Codex CLI Core 20-case 评测的前后对照数据。
