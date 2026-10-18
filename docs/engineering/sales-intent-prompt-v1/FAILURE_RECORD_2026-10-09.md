# 失败记录与处理方案（2026-10-09）

| 记录 | 环节 | 现象 | 是否算产品功能失败 | 处理方案 | 证据 |
|---|---|---|---|---|---|
| F-001 | Core Builder / acceptance child | CLI 出现 TLS `handshake eof`，验收子进程超时；候选未发布 | Core 终态未通过，属于本次 A 臂的产品流程结果；根因同时含 CLI 基础设施故障 | 保留 workspace、提示、stdout/stderr；修 CLI 会话后重跑 | `.data/runs/102c5e4bc474`、`6697db248a37`、`822006376433` |
| F-002 | 意图获取 | B 臂首轮 `Codex CLI agent intent timed out`，没有生成意图 | 不算 Core 构建失败；属于意图模块调用的 CLI 基础设施失败 | 记录为 B 臂未进入 Core，不能纳入意图效果分子 | `.data/runs/3427f3d7842a`、`599bd5b7064f`、`62a0a03efb80` |
| F-003 | 意图门禁 | 模型直接返回 `ready`，未覆盖必需追问主题 | 算意图获取协议失败 | runner 拒绝释放销售答案并保持隐藏，修 prompt 或继续追问 | `true-intent-ab-20261009-bounded/medium-lead-followup-01/intent-agent/` |
| F-004 | 独立审计 | 6 个候选均为隐藏状态 | 不算浏览器功能失败 | 审计器将 6/6 记为 `not_run` 并保留分母 | `true-intent-ab-20261009-final/external-audit/external-business-audit.json` |
| F-005 | Core acceptance child 会话 | 基础 Codex 请求短测已恢复，但 acceptance child 仍出现 `read() called while another coroutine is already waiting for incoming data` 并长时间不收尾 | 属于 CLI 子会话/验收证据基础设施失败；不能降级为发布 | 保留父子进程日志；修复子会话收尾后再重跑稳定主实验 | `.data/runs/e78d6ec071fa/run.json` |

当前没有证据证明“已发布页面存在业务缺陷”，因为本批没有页面进入发布状态。下轮修复 CLI 会话后，必须重新执行两臂和全部独立浏览器 journeys，才能形成发布通过率对比。
