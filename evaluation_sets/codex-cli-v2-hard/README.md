# Codex CLI Agent Core hard v2

这是独立于 v1 的高难评测批次，包含 8 个案例。每个案例至少有 8 个连续阶段、3 个实体、正向路径、非法路径、规则分支和实体隔离检查；数据目录为 `testdata/<case-id>/`。

`manifest.json` 的 `status=passed` 表示 acceptance contract 和 selector 静态审计通过；当前 `execution_status=real_executed_8_of_8` 表示八个案例都已经启动真实 Codex CLI 并留下终态证据。它不能和 v1 的 20-case 结果合并。完整结果见 `docs/engineering/hard-v2-ab/full-real-2026-10-07.json`。

这批合同目前更准确的结论是“页面闭环合同可执行”。输入数据和旅程仍偏通用，尚不足以证明每个业务主题都具有真实的金额、角色、审批、聚合和跨实体隔离难度。

建议先用 3 个 v1 hard + 2 个 v2 hard 做小批真实运行，确认 runner 能承受新 contract，再扩展到完整 v2。
