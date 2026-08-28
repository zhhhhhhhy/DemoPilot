# DemoPilot 正式数据清理报告

更新时间：2026-08-28

## 最终口径

正式 Demo 必须同时满足：

1. Provider 为真实 DeepSeek；
2. 任务状态为 `completed`；
3. Quality Gate 为 `passed`；
4. Chromium 浏览器验证为 `passed`；
5. Demo、规格、销售讲解词、QA、截图与 ZIP 均真实落盘。

按这个口径，当前正式目录 `.data/runs` 只保留 **11 个真实成功 Demo**。Mock、失败生成、调试运行和重复尝试都不计为 Demo。

## 清理结果

| 项目 | 数量 |
| --- | ---: |
| 正式真实 DeepSeek Demo | 11 |
| 正式目录中的 Mock | 0 |
| 正式目录中的失败运行 | 0 |
| 每个 Demo 的文件产物 | 8 + ZIP |

本轮 8 条失败运行和 5 个包含失败的混合评测批次没有永久删除，而是移入可恢复归档：

`.data/archive/20260828-real-demo-expansion/`

归档只用于排障追溯，不进入产品页 Demo 数量、README 成果数量或正式交付统计。完整的正式清单见 [真实 Demo 清单](docs/REAL_DEMO_CATALOG.md)。
