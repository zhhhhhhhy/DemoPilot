# True intent A/B 实验报告（2026-10-09）

> 2026-10-16 口径说明：本文件的 20 秒、0 次返工批次仅保留为故障诊断，不能作为正常预算下的意图效果比较。“终态记录完成”不等于用户目标或能力评测完成。当前正常预算试验与简历结论见 `docs/portfolio-v1/指标与实验报告.md`；原始结果文件保留不变。

## 目的

验证一个明确问题：销售只说一句不完整的话时，先让意图模块追问销售，再把确认后的意图交给 Core Builder，是否能提高最终发布通过率或减少 Core 返工。

本实验的 A 臂是原始销售话术直接进入 Core；B 臂先把同一字节串交给意图模块。B 只有在模型返回 `needs_clarification` 且问题覆盖冻结脚本中的必需主题后，才释放销售回答并生成结构化意图。两臂使用同一 Codex CLI、模型、普通 fixture、浏览器验收协议和发布门禁。

## 当前架构

```text
销售一句话
    ├─ A raw-sales ───────────────┐
    └─ B intent-agent → 追问 → 回答 ─┤
                                      ↓
                              Codex CLI Core Builder
                                      ↓
                          Core 内部 acceptance_checker
                                      ↓
                         Chromium 验收与发布/隐藏
                                      ↓
                     独立 fresh-browser 全量审计
```

意图回答脚本在 `evaluation_sets/sales-intent-v1/sales-clarifications/`，不放入 `testdata`，避免 Core 在追问前偷读答案。Core 工作区只挂载同一份普通 fixture；`scenario` 和 `audience` 从模型可见的 `inputs.json` 中去掉，避免 A 臂从 fixture 反向读到完整业务说明。验收标准和 gold 只由受信验收器使用。

## 真实运行结果

结果文件：`evaluation_sets/sales-intent-v1/results/true-intent-ab-20261009-final/paired-results.json`。

| 分支 | 终态 | 最终发布通过 | CLI 调用 | 主要终止位置 |
|---|---:|---:|---:|---|
| A raw-sales | 3/3 | 0/3 | 6 | Core 一轮验收未通过，候选保持隐藏 |
| B intent-agent | 3/3 | 0/3 | 3 | 意图首轮 CLI 超时，未进入 Core |

A 的 3 个案例均留下 Core workspace、stdout/stderr、验收事件和隐藏状态。B 的 3 个案例均留下意图请求、首轮 prompt/context、进程日志和失败状态；本批没有答案释放，因此不能把 `0/3` 解读成意图质量为零。

独立审计文件：`evaluation_sets/sales-intent-v1/results/true-intent-ab-20261009-final/external-audit/external-business-audit.json`。6 个候选全部未发布，审计器按协议把 6 个案例保留在分母，浏览器业务检查均标为 `not_run`，没有把隐藏候选误报为通过或发布后缺陷。

## 已经真实验证的链路证据

较长超时批次 `evaluation_sets/sales-intent-v1/results/true-intent-ab-20261009-bounded/` 中，简单案例 B 臂真实走完了：首轮询问、主题覆盖检查、释放销售回答、第二轮意图整理、进入 Core。对应记录包含 `intent-turn-01/02-context.json`、`seller-question-audit.json`、`seller-answers-released.json` 和两轮 CLI stdout/stderr。该案例之后在 Core 验收阶段失败，所以它证明的是意图链路确实可执行，不证明最终发布成功。

同一批次的中等案例还捕获到一个可考核的意图门禁问题：模型首轮直接返回 `ready`，没有询问冻结必需主题，runner 记录 `intent_gate_errors` 并拒绝把回答脚本塞给模型。这属于意图获取模块的协议失败，不属于 Core 中间返工。

## 失败归因

1. **本批 A 的失败发生在 Core/验收阶段。** 模型尝试进入 Core，但一次迭代内没有形成同时满足静态安全、子智能体验收证据和浏览器契约的可发布候选；结果保持 `cannot_complete`/隐藏。它不是意图模块失败。
2. **本批 B 的失败发生在意图模块调用之前。** 3 个 B 臂都出现 `Codex CLI agent intent timed out`，没有得到可交付的结构化意图；因此 Core 没有被调用。它属于 Codex CLI 网络/会话基础设施故障，不属于 Core 构建能力。
3. **已记录的基础设施症状。** CLI stderr 反复出现 `tls handshake eof`；Core 验收子进程还出现 `read() called while another coroutine is already waiting for incoming data`。这些记录位于各 run 的 `artifacts/evidence/**/stderr.log`，是当前无法完成全量效果比较的直接原因。
4. **独立验收没有发现“发布后缺陷”。** 因为本批没有任何发布候选，浏览器审计全部是 `not_run`。不能把它写成业务功能通过，也不能把它写成发布后回归失败。
5. **连接恢复后仍有子会话问题。** 一个短 Codex 请求已经成功返回，但稳定主实验的 acceptance child 仍出现异步流读取冲突并长时间不收尾；这说明问题已经缩小到验收子会话管理，不能只归因于外网暂时不可用。

## 已采取的改进及作用

| 改进 | 作用 | 验证 |
|---|---|---|
| 首轮意图上下文改为 sales-text-only | 防止意图模块提前读取 fixture 或销售回答 | 配套测试通过 |
| 回答脚本移出 `testdata` | 防止 Core 绕过问询直接读答案 | loader 和路径审计通过 |
| required topic 覆盖门禁 | 模型未追问就返回 ready 时拒绝交付 | 中等案例真实捕获该失败 |
| `scenario/audience` 从 Core 可见 fixture 白名单移除 | 防止 A 臂从 inputs 读回完整意图 | masked-input 测试通过 |
| 终态恢复逻辑 | CLI 被中断后再次运行只补写终态，不重复启动该臂 | 相关测试通过 |
| 独立 fresh-browser 审计 | 只审计真正发布的候选，隐藏候选保留分母 | 6/6 隐藏案例均正确记为 not_run |

## 验收结论

这次工作已经完成了实验协议、真实 CLI 执行、终态记录、失败归因和独立审计；没有完成“意图模块提高最终发布通过率”的效果结论。当前最先需要修复的是 Codex CLI 的 TLS/会话稳定性，然后在同一冻结协议下重跑完整 A/B。只有 A、B 都有进入 Core 的终态，并且发布候选都经过 fresh-browser 全量检查，才可以比较最终发布率和返工次数。
