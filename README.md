<div align="center">

# DemoPilot

### 由 Agent Team 亲手造出来的 Agent Team Demo 工厂

**Human-directed. Agent-built. Evidence-verified.**

人类负责目标、边界与最终验收；Agent Team 完成架构、前后端开发、浏览器测试、失败复盘与持续迭代。

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-42B883?logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![uv](https://img.shields.io/badge/managed%20with-uv-DE5FE9)](https://docs.astral.sh/uv/)
[![DeepSeek](https://img.shields.io/badge/Provider-DeepSeek-4D6BFE)](https://www.deepseek.com/)
[![Built by Agent Team](https://img.shields.io/badge/Built_by-Agent_Team-111111)](#built-by-an-agent-team)

[快速开始](#快速开始) · [核心能力](#核心能力) · [运行架构](#运行架构) · [评测证据](#评测证据) · [API](#api) · [项目边界](#项目边界)

</div>

## Built by an Agent Team

DemoPilot 不只是一个“内部调用多个模型”的项目。**这个项目本身也采用 Agent Team 协作方式完成**：从需求讨论、公开方案调研、系统架构、Vue 前端、Python 后端，到真实 API 调用、Chromium 端到端测试、失败归因、修复和 A/B 评测，都由不同职责的 AI Agent 在人的目标与验收标准下持续推进。

| 参与者 | 主要职责 |
| --- | --- |
| 人类负责人 | 提出真实业务目标、确认产品边界、作出关键决策并最终验收 |
| 产品与架构 Agent | 丰富需求，设计 Agent Team、Harness、契约与评测体系 |
| 工程 Agent | 实现 Vue 前端、FastAPI 后端、Provider、沙箱与持久化 |
| 测试与 Reviewer Agent | 运行真实 DeepSeek/API/浏览器测试，记录失败证据并驱动返工 |
| Harness | 约束调用预算、文件权限、验证顺序和 Skill 晋级，防止“自称完成” |

这不是“全自动、无人监督”的营销故事，而是一种更可复现的工程分工：**人负责方向和责任，Agent Team 负责高密度执行，测试证据决定能否交付。**

## 为什么是 DemoPilot

普通的一次性代码生成容易把“页面看起来完成了”误当成“需求真的实现了”。DemoPilot 把生成过程改造成一条可验证的 Agent Team 流水线：Builder 负责构建，但不能自己定义验收标准，也不能用自报结果证明完成；Contract Agent、Runner 与 Reviewer 分别冻结交互协议、执行真实浏览器验证、给出独立结论。

| 一次性生成 | DemoPilot |
| --- | --- |
| Prompt 直接变代码 | 先增强 Brief，再拆解、设计、冻结契约后构建 |
| 生成者同时解释自己是否完成 | Builder、Runner、Reviewer 职责与权限隔离 |
| 测试选择器可能跟着页面一起“编出来” | Harness 分配并冻结 `#contract-*` 选择器与协议 SHA-256 |
| 失败后整段重做 | 精确记录证据、根因、修复指令与复验方法，定向返工 |
| 成功依赖一次演示 | 固定用例、版本对比、A/B 晋级门持续回归 |
| 产物来源不清楚 | 每次真实工具调用记录路径、耗时、结果与 SHA-256 |

> [!IMPORTANT]
> DemoPilot 生成的是**纯展示型售前 Demo**。业务数据为本地虚构样例，不连接 ERP、WMS、CRM、客户数据库或生产环境，也不会自动发布或发送给客户。

## 核心能力

- **9 节点 Agent Team**：Brief、Manager、Discovery、Product、Experience、Contract、Builder、Runner、Reviewer 分工协作。
- **共享交互契约**：每项 must-have 被转换为稳定操作路径、选择器与可见断言，返工期间不得修改验收标准。
- **Builder 确定性预检**：每一版代码在落盘前检查文件范围、安全、HTML 结构、契约选择器、控件类型、断言文本和数据契约。
- **真实浏览器验证**：Playwright + Chromium 执行页面加载、导航、按钮点击、状态变化与控制台错误检查，并保存截图证据。
- **独立 Reviewer**：只读取需求、最终项目和运行证据，不修改文件，也不接受 Builder 自报完成。
- **受控执行 Harness**：任务级沙箱、生命周期 Hook、审批、取消/恢复、最大调用数、最大返工轮次和 SSE 实时事件流。
- **自动评测中心**：30 条固定跨行业用例，跟踪成功率、质量分、浏览器通过率、功能覆盖率、调用数和耗时。
- **Skill A/B 晋级**：六个小型工程 Skill 只有通过同 Provider、同用例、同停止条件的 A/B 门槛后，才进入正式 Harness。

## 运行架构

```mermaid
flowchart LR
    A[销售 Brief] --> B[Brief Agent<br/>需求增强]
    B --> C[Manager<br/>计划 / 预算 / 依赖]
    C --> D[Discovery<br/>问题与价值假设]
    D --> E1[Product<br/>功能与演示主线]
    D --> E2[Experience<br/>Apple 风格体验]
    D --> E3[Reviewer<br/>预先冻结评审量表]
    E1 --> F[Contract Agent<br/>共享交互协议]
    E2 --> F
    E3 --> F
    F --> G[Builder<br/>HTML / CSS / JS]
    G --> H{确定性预检}
    H -- 失败 --> G
    H -- 通过 --> I[Runner<br/>沙箱落盘 + Chromium]
    I --> J[Reviewer<br/>独立评审]
    J -- 要求返工 --> G
    J -- 通过 --> K[Demo + 规格 + 讲解词<br/>QA 报告 + ZIP]
```

### 关键设计

1. **验收标准先于代码**：Product、Experience 与 Reviewer 完成后，Contract Agent 生成业务操作路径，Harness 再分配稳定选择器并冻结协议。
2. **客观门禁先于主观评审**：文件缺失、危险代码、契约违约等问题由预检硬阻断；视觉审美、文案质量和销售说服力由 Reviewer 与销售人工判断。
3. **证据先于结论**：只有文件真实落盘、校验和生成、浏览器交互完成后才创建 receipt；模型文本不能替代运行证据。
4. **失败可恢复**：运行状态、Agent 输出、审批和评测批次持久化到本地 JSON；任务可取消，并从检查点恢复。

## 快速开始

### 前置条件

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20+ 与 npm

### 1. 获取项目

```powershell
git clone https://github.com/zhhhhhhhy/DemoPolit.git
cd DemoPolit
Copy-Item .env.example .env
```

### 2. 安装依赖

```powershell
cd backend
uv sync --extra dev
uv run playwright install chromium

cd ../frontend
npm.cmd install
cd ..
```

### 3. 配置 Provider

DeepSeek 是真实开发的默认 Provider。把下面配置加入项目根目录 `.env`：

```dotenv
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

没有 API Key 也可以启动项目，并在界面中选择 **Mock** 完成确定性的离线全流程回归。Mock 会明确标记为 `controlled_template_fallback`，不会冒充真实模型生成。

可选 Provider 还支持同样格式的 `AIHUBMIX_*` 与 `ZJU_*` 配置。Claude 默认禁用；如需启用，只使用 Anthropic 官方 SDK，详见[可选：Claude 官方 SDK](#可选claude-官方-sdk)。

### 4. 启动

```powershell
.\start.ps1
```

打开：

- Web 控制台：<http://127.0.0.1:5173>
- API 健康检查：<http://127.0.0.1:8091/api/health>
- OpenAPI 文档：<http://127.0.0.1:8091/docs>

也可以分别启动两个服务：

```powershell
# 终端 1
cd backend
uv run uvicorn --env-file ../.env --app-dir src demopilot.main:app --reload --host 127.0.0.1 --port 8091

# 终端 2
cd frontend
npm.cmd run dev
```

## 使用方式

1. 填写客户名称、行业、演示对象、客户场景和必须出现的能力。
2. 选择 DeepSeek 进行真实生成，或选择 Mock 进行离线回归。
3. 需要时开启“生成文件前人工批准”；团队会在首次写入产物前暂停。
4. 在 Agent Team 时间线中查看每个节点、工具凭证、预检失败和返工轨迹。
5. 预览最终 Demo，检查独立 Reviewer 报告，下载完整 ZIP 交付包。

最终交付包包含：

```text
demo/
├── index.html
├── styles.css
└── app.js
demo-spec.md
sales-script.md
qa-report.md
manifest.json
```

## 评测证据

### 工程验证

当前仓库快照已完成以下本地验证：

| 检查项 | 结果 |
| --- | --- |
| Backend Ruff | 通过 |
| Backend pytest | 36 tests passed |
| Frontend ESLint | 通过 |
| Frontend Vitest | 4 tests passed |
| Frontend production build | 通过 |

复现命令：

```powershell
cd backend
uv run ruff check .
uv run pytest --basetemp=.pytest-tmp

cd ../frontend
npm.cmd run lint
npm.cmd run test:run
npm.cmd run build
```

### 真实 DeepSeek Demo 清单

当前正式目录包含 **23 个真实成功 Demo**，覆盖 23 个不重复行业，并分为 9 个简单要求与 14 个复杂要求。每个 Demo 都对应独立的 DeepSeek Agent Team 任务，并通过文件落盘、Chromium 真实点击和 Reviewer Quality Gate；每项均保留 8 个文件产物与 ZIP。

| 指标 | 当前正式成果 |
| --- | ---: |
| 真实 DeepSeek Demo | 23 |
| 简单 / 复杂要求 | 9 / 14 |
| 不重复行业 | 23 |
| 浏览器通过 | 23/23 |
| Quality Gate 通过 | 23/23 |
| Agent 调用合计 | 255 |
| 定向返修合计 | 33 |

详细 run ID、行业和调用次数见 [真实 Demo 清单](docs/REAL_DEMO_CATALOG.md)。这里统计的是经验证的正式成果，不把 Mock、失败尝试或批量回归用例算作 Demo。

工程与实验记录：

- [Builder 确定性预检报告](BUILDER_PREFLIGHT_REPORT.md)
- [共享交互契约报告](SHARED_CONTRACT_REPORT.md)
- [工程 Skill A/B 报告](SKILL_AB_REPORT.md)
- [扩大评测用例报告](EXPANDED_EVALUATION_REPORT.md)
- [本地评测数据清理报告](DATA_CLEANUP_REPORT.md)

### 扩大后的真实 DeepSeek 覆盖

2026-08-28 先将正式成果从 4 个扩充为 11 个，再按难度扩充到 20 个，并追加电商售后、安全响应和酒店收益 3 个真实 Demo，当前共 **23 个**。扩充过程中新增了契约控件可见性、唯一 ID、契约视图存在性和 `data-target → contract-view-N` 精确路由门禁；评测中心进一步支持简单 / 复杂筛选和分组统计。追加 3 个 Demo 的最终成功率、浏览器通过率和功能覆盖率均为 100%，平均评测分 94.42；其中酒店案例首轮被产物门禁拦下，重新生成后才进入正式清单。详见 [难度扩容报告](docs/DIFFICULTY_EXPANSION_REPORT.md)。

## 自动评测中心

评测中心内置 30 条固定用例。在原有运营、销售、客服、制造、零售、金融、人力、物流、教育、医疗、能源、物业、法务、营销、采购、安全、项目管理、知识库、电商和经营驾驶舱之外，新增保险、酒店、农业、航空、汽车服务、建筑施工、医药供应链、公共服务、数字内容和碳排管理。

- **Mock**：支持 5 / 10 / 20 / 30 条离线回归。
- **真实 Provider**：DeepSeek、AIHubMix、ZJU 一次最多 3 条并强制串行，限制误触发成本。
- **难度分组**：支持“简单要求 / 复杂要求”筛选，并分别计算成功率、首轮成功率、平均分与返工率。
- **可追溯结果**：保存 Demo 任务 ID、输入摘要、来源模式、验证结果、浏览器证据、调用数、返工次数和耗时。
- **版本比较**：对比相同 Provider 的上一版本，并输出 Markdown 报告。
- **Skill 晋级**：`baseline`、`candidate`、`approved` 三种配置支持首轮质量 A/B；未通过门槛的候选不会进入正式 Harness。

## API

### Demo 运行

| Method | Endpoint | 说明 |
| --- | --- | --- |
| `POST` | `/api/runs` | 创建 Demo 任务 |
| `GET` | `/api/runs/{id}` | 获取完整任务快照 |
| `GET` | `/api/runs/{id}/events` | SSE 推送进度、审批和工具凭证 |
| `POST` | `/api/runs/{id}/approvals/{approval_id}` | 提交 `approve` / `decline` |
| `POST` | `/api/runs/{id}/cancel` | 取消任务并保留已有证据 |
| `POST` | `/api/runs/{id}/resume` | 从持久化检查点恢复 |
| `GET` | `/api/runs/{id}/files/{path}` | 读取或下载交付文件 |

### 自动评测

| Method | Endpoint | 说明 |
| --- | --- | --- |
| `GET` | `/api/evaluation-cases` | 获取固定评测集 |
| `POST` | `/api/evaluations` | 创建批量评测 |
| `GET` | `/api/evaluations` | 获取评测历史 |
| `GET` | `/api/evaluations/{id}` | 获取批次明细 |
| `GET` | `/api/evaluations/{id}/events` | SSE 推送批次进度 |
| `POST` | `/api/evaluations/{id}/cancel` | 取消批次 |
| `GET` | `/api/evaluations/{id}/report` | 下载 Markdown 报告 |

## 项目结构

```text
DemoPilot/
├── backend/
│   ├── src/demopilot/
│   │   ├── providers/          # DeepSeek / Mock / 可选 Provider
│   │   ├── skills/             # 六个小型工程 Skill
│   │   ├── orchestrator.py     # Agent Team 编排与返工循环
│   │   ├── interaction_contract.py
│   │   ├── builder_preflight.py
│   │   ├── browser_qa.py
│   │   ├── reviewer.py
│   │   └── evaluator.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/components/
│   └── package.json
├── scripts/                    # Skill 校验与 A/B 工具
├── .env.example
└── start.ps1
```

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `DEMOPILOT_MAX_AGENT_CALLS` | `18` | 单任务最大模型调用数 |
| `DEMOPILOT_MAX_REVISIONS` | `4` | 最大返工轮次 |
| `DEMOPILOT_MAX_PARALLEL_AGENTS` | `2` | 最大并行 Agent 数 |
| `DEMOPILOT_ENABLE_CLAUDE` | `false` | 是否启用 Claude 官方 SDK |
| `DEEPSEEK_API_KEY` | 空 | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | DeepSeek 模型名 |
| `VITE_API_BASE` | 空 | 前端 API 地址；开发代理模式保持为空 |

> [!CAUTION]
> 不要提交 `.env`、API Key、`.data` 运行记录或客户信息。项目已通过 `.gitignore` 排除这些内容，但提交前仍应人工检查 `git status`。

## 可选：Claude 官方 SDK

本项目不包含、也不依赖任何泄露或未经授权的 Claude Code 源码。Claude 模式只使用 Anthropic 官方 Python SDK，并将执行能力限制为结构化规划；默认禁用 Bash、Read、Write、Edit 与网络工具。

```powershell
cd backend
uv sync --extra dev --extra claude
$env:DEMOPILOT_ENABLE_CLAUDE = "true"
uv run uvicorn --env-file ../.env --app-dir src demopilot.main:app --host 127.0.0.1 --port 8091
```

## 项目边界

- Mock 是确定性的受控基线，不代表真实大模型效果。
- 30 条固定用例用于工程回归，不是客户真实数据集；当前正式 DeepSeek 成果覆盖 11 个不重复行业，仍不能代表模型总体质量或随机任务成功率。
- Builder 只生成 `index.html`、`styles.css`、`app.js`，沙箱不开放 Bash、任意文件读写、包安装或外部网络。
- Chromium E2E 证明受控页面在当前环境可加载和点击，不等于完成跨浏览器、无障碍、性能、部署或生产验收。
- 本地 JSON 适合单机 MVP；多实例与多租户部署仍需要数据库、对象存储、任务队列、权限与租户隔离。
- 最终 Demo 必须由销售复核业务正确性、视觉质量与客户表达，不会自动对外发布。

## Roadmap

- [x] 9 节点 Agent Team 与受限返工循环
- [x] Contract Agent 与 Harness 冻结交互协议
- [x] Builder 确定性预检与 Chromium 质量门
- [x] 独立 Reviewer 与证据化 QA 报告
- [x] 30 用例自动评测中心与 Skill A/B 晋级
- [ ] PostgreSQL / 对象存储 / 任务队列适配
- [ ] 多租户、RBAC 与审计后台
- [ ] 跨浏览器、无障碍与性能基线
- [ ] 容器化部署与 CI 回归

## Contributing

欢迎提交 Issue、评测用例、失败样本和 Pull Request。建议在 PR 中说明：

1. 要解决的真实失败是什么；
2. 修改影响哪些 Agent、契约或门禁；
3. 如何复现以及新增了哪些自动化证据；
4. 是否改变 Provider 成本、安全边界或产物格式。

新增工程 Skill 请先放入 `candidate` 配置，并通过同 Provider、同用例、同首轮停止条件的 A/B 晋级门；不要直接加入 `approved`。

## Acknowledgements

- [Anthropic Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python)：可选的官方 Claude Provider。
- [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)：公开的 Agent 沙箱与执行器设计参考。

DemoPilot 只吸收公开可描述的 Agent 工作流与工程方法，未复制、打包或依赖第三方复原版 Claude Code 源码。
