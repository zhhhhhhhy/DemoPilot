# DemoPilot

DemoPilot 是一个面向售前团队的 **Agent Team Demo 制造器**：销售输入客户、场景、受众与必须展示的能力，团队经过需求增强、Manager 拆解、洞察、并行产品/体验设计/评审标准准备、Contract Agent 冻结共享交互协议、构建、产物验证和 Reviewer 独立评审，最后交付可交互页面、方案规格、销售讲解词、评审报告与 ZIP 包。

## 已实现的闭环

1. 销售在 Vue 控制台填写客户 Brief 或套用行业模板。
2. FastAPI 创建任务并持久化每个 Agent 的状态和结果。
3. Manager 设定目标、任务依赖、验收条件与调用预算。
4. 产品和体验 Agent 并行工作，Builder 等待二者完成后再构建。
5. Builder 每一版完整文件都会先经过确定性预检，只有文件范围、安全、契约选择器、控件类型、断言文本和基础数据契约通过后，Runner 才允许落盘并启动 Chromium。
6. 每次工具调用在真实成功或失败后生成 receipt，记录路径、耗时、结果和 SHA-256，不接受模型自报完成。
7. Reviewer 在构建前把客户需求转成固定权重的评审量表；本地产物验证器与无头 Chromium 随后检查最终文件、按钮、导航、控制台错误并保存截图证据。
8. Reviewer 只读取需求、最终项目和验证证据，不修改文件、不接受 Builder 自报完成；它逐项记录需求覆盖、真实交互、模拟能力、问题证据、根因、修复要求与复验方法，再由 Manager 决定通过或返工。
9. 可选人工审批会在写文件前暂停；任务支持取消、检查点恢复、服务重启恢复和 SSE 实时事件流。
10. 返工受最大轮次与最大模型调用数限制，避免失控循环。
11. 销售在控制台预览并下载完整交付包，最终由人工复核后对外使用。
12. 自动评测中心可用固定跨行业用例批量运行同一套 Agent Team，汇总成功率、质量分、浏览器通过率、功能覆盖率和调用成本，并和同 Provider 的上一版本比较。

## 技术栈

- 前端：Vue 3、TypeScript、Vite，苹果风格响应式界面
- 后端：Python 3.11+、FastAPI、Pydantic
- Python 包管理：uv
- 内核：Manager 驱动的 Pipeline、并行阶段、任务沙箱、生命周期 Hook、审批、调用凭证、检查点恢复、SSE、Chromium 质量门禁与受限返工
- Provider：默认 Mock（离线、确定性）；可选 DeepSeek、AIHubMix、ZJU 或 Anthropic 官方 `claude-agent-sdk-python`
- 存储：本地 JSON 任务记录与文件制品，后续可替换 PostgreSQL/S3

## 快速启动

首次安装：

```powershell
cd D:\作品集\DemoPilot\backend
uv sync --extra dev
uv run playwright install chromium

cd D:\作品集\DemoPilot\frontend
npm.cmd install
```

分别启动：

```powershell
# 终端 1
cd D:\作品集\DemoPilot\backend
uv run uvicorn --env-file ../.env --app-dir src demopilot.main:app --reload --host 127.0.0.1 --port 8091

# 终端 2
cd D:\作品集\DemoPilot\frontend
npm.cmd run dev
```

打开 <http://127.0.0.1:5173>。也可以在完成安装后直接运行 `start.ps1`。

## 接入官方 Claude Agent SDK

本项目不包含、也不依赖任何泄露或未经授权的 Claude Code 源码。真实 Claude 模式使用 Anthropic 官方 MIT 许可 Python SDK，并将模型执行能力限制为结构化规划：默认禁用 Bash、Read、Write、Edit 与网络工具。

```powershell
cd D:\作品集\DemoPilot\backend
uv sync --extra dev --extra claude
$env:DEMOPILOT_ENABLE_CLAUDE = "true"
uv run uvicorn --env-file ../.env --app-dir src demopilot.main:app --host 127.0.0.1 --port 8091
```

还需要有效的 Claude Code/Anthropic 登录。未配置时继续使用 Mock 模式即可完整演示产品流程。

## Agent Team 运行参数

新建任务默认由 DeepSeek 驱动完整 Agent Team；Mock 仅用于离线回归，AIHubMix 和 ZJU 保留为手动备用。真实模型的地址、密钥和模型名从项目根目录 `.env` 读取。支持 `DEEPSEEK_*`、`AIHUBMIX_*`、`ZJU_*` 三组配置。以下参数可控制团队成本和循环边界：

```text
DEMOPILOT_MAX_AGENT_CALLS=18
DEMOPILOT_MAX_REVISIONS=4
DEMOPILOT_MAX_PARALLEL_AGENTS=2
```

只有在新建 Demo 时由用户显式选择真实 Provider 才会产生外部模型调用。控制台默认勾选“生成文件前需要人工批准”：Brief、Manager、Discovery、Product、Experience 和 Builder 可以先工作，Runner 在首次写入文件前暂停。

## 受控执行 API

- `GET /api/runs/{id}/events`：SSE 推送完整任务快照、审批状态和工具凭证。
- `POST /api/runs/{id}/approvals/{approval_id}`：提交 `approve` 或 `decline`。
- `POST /api/runs/{id}/cancel`：取消运行，保留已有输出、事件与 receipt。
- `POST /api/runs/{id}/resume`：从已持久化的 Agent 输出和检查点恢复失败/取消任务，不重复已完成模型调用。

Builder 可以返回真实的 `demo/index.html`、`demo/styles.css`、`demo/app.js` 文件内容。若 Provider 未提供完整三文件，系统会明确记录 `controlled_template_fallback`，不会把模板冒充为模型生成；若提供完整文件，则记录 `agent_generated_files` 并执行相同的安全与浏览器验证。

## Agent Team 内置 Reviewer

Reviewer 是 Team 内成员，但与 Builder 保持 Prompt、职责和权限隔离。它分两阶段运行：

1. 与产品和体验设计阶段一起，根据原始需求形成 `review_rubric`，固定检查需求覆盖、交互、产物、安全、演示清晰度与来源追踪，并设置不可被模型降低的硬门禁。
2. Runner 生成验证器、manifest 和 Chromium 证据后，Reviewer 对照“需求 + 最终项目 + 运行证据”输出 `reviewer_iteration_n`；每个问题必须包含证据、根因、修复指令和复验方法。

验证器问题会强制覆盖模型的主观结论：只要产物、must-have、固定交互、安全或来源门禁失败，即使 Reviewer 声称通过，系统仍会进入返工。最终 `qa-report.md` 保留兼容文件名，但内容已升级为 Reviewer 独立评审报告，并明确区分真实交互、样例数据模拟能力、既定演示边界和真正未解决项。不接 ERP/WMS/CRM、数据库、客户真实数据或生产环境属于纯展示型 Demo 的正确完成范围，不记为缺陷或开放项。

## Contract Agent 与内部共享交互协议

产品、体验设计和评审标准完成后，Contract Agent 会把每项 must-have 转成业务操作路径；Harness 再统一分配稳定 `#contract-*` 选择器并冻结协议 SHA-256。Builder 只能实现协议，Runner 忽略 Builder 自报的测试并执行同一协议，Reviewer 根据协议违约和 Chromium 证据决定返工。协议每个 Demo 只生成一次，返工不得修改验收标准。

该机制解决的是多 Agent 共享同一幻觉：以前 Builder 可能同时编造页面和测试选择器；现在缺失元素会被精确报告并进入自主返工。真实 DeepSeek 测试证明采购高难用例能在两轮自主返工后达到 95 分并通过浏览器质量门，但三个用例的首轮成功率仍为 33.3%，因此不宣称它已经提升首轮总体质量。详细证据见 `SHARED_CONTRACT_REPORT.md`。

## Builder 确定性预检门

Builder 初版和每个 Reviewer 修订版都会在写文件前运行同一预检。硬门只检查可客观判定的内容：三个文件及大小预算、危险代码、HTML 基础结构、模拟边界、冻结契约选择器与控件类型、精确成功反馈、核心事件声明、三幕故事、must-have 数据和客户主色。视觉审美、文案质量和销售说服力不属于硬门，仍由 Reviewer 评分并由销售人工确认。

失败结果会保存为 `builder_preflight_iteration_n`，包含稳定错误码、失败类别、精确选择器和修复说明；预检失败不会写入产物，也不会启动 Chromium 或调用最终 Reviewer。Contract v1.1 会把 Contract Agent 的描述性断言规范化为短、原子、可见的文本，减少“业务结果正确但长句无法逐字匹配”的脆弱失败。真实 DeepSeek 复杂零售案例 `a50e398debcb` 在前三版缺失契约选择器时均被提前阻断，第 3 次修订通过预检后才进入 Chromium 与 Reviewer 阶段，最终浏览器通过、Reviewer 100 分、质量门通过，共 12 次模型调用。详细证据见 `BUILDER_PREFLIGHT_REPORT.md`。

评测 API 另有 `builder_preflight_enabled` 开关，只用于隔离 A/B 对照，普通 Demo 始终启用预检。2026-08-27 的一次 3 用例 DeepSeek 探索性 A/B 中，开启预检的最终成功率从 0% 升至 33.3%，平均调用从 17.0 降至 12.67，平均耗时从 285.81 秒降至 181.50 秒；但两个用例在产物生成前失败，使现有评测器记录的功能覆盖率从 100% 降至 33.3%。因此该结果只支持“安全与失败成本改善、最终质量有初步正向信号”，不构成首轮质量或总体质量的正式统计证明。

## 自动评测中心

控制台的“自动评测”区域内置 20 条固定用例，覆盖运营、销售、客服、制造、零售、金融、人力、物流、教育、医疗、能源、物业、法务、营销、采购、安全、项目管理、知识库、电商与经营驾驶舱。每条用例都带有难度、必须能力和行业标签，便于重复运行和版本比较。

- Mock 模式支持一次运行 5、10 或 20 条，适合离线全量回归；其 `controlled_template_fallback` 是明确标注的受控基线，不计作真实模型生成。
- DeepSeek、AIHubMix 和 ZJU 属于真实外部调用，一次最多 3 条并强制串行，避免误触发高成本批量任务。
- 每个结果都保存原始 Demo 任务 ID、产物验证、Chromium 点击证据、功能覆盖、来源模式、调用数、返工次数、耗时和输入摘要。
- 验收门禁可配置成功率、平均分、浏览器通过率、功能覆盖率和平均调用数；完成后生成 Markdown 报告并显示相同 Provider 的版本差异。
- 批次与单个 Demo 运行均写入 `.data`，服务重启后可恢复未完成批次；运行中的批次可以取消。

相关 API：

- `GET /api/evaluation-cases`：读取固定评测集。
- `POST /api/evaluations`：创建批量评测。
- `GET /api/evaluations`、`GET /api/evaluations/{id}`：读取历史与明细。
- `GET /api/evaluations/{id}/events`：SSE 实时进度。
- `POST /api/evaluations/{id}/cancel`：取消批次。
- `GET /api/evaluations/{id}/report`：下载 Markdown 报告。

## 工程 Skill 与 A/B 晋级门

Harness 采用“小型、单一职责、按阶段渐进加载”的工程 Skill，而不是把大段通用提示词塞进每次调用。当前六个 Skill 分别负责需求规格化、Vue Demo 工程、Apple 风格界面、模拟业务数据、浏览器验收和定向修复。每次调用会记录所加载 Skill 的名称、版本、文件 SHA-256 与整个配置包 SHA-256，便于复现和审计。

Skill 分为三个配置：`baseline` 不加载 Skill，`candidate` 用于实验，`approved` 才是普通 Demo 任务默认加载的正式配置。候选配置必须在相同 Provider、相同用例和首轮停止条件下与基线 A/B；首轮成功率提高，或成功率持平且平均分至少提高 2 分，同时浏览器通过率、功能覆盖率和调用次数不退化，才允许晋级。评测中心可以选择配置并显示晋级结论。

```powershell
cd D:\作品集\DemoPilot
python scripts\validate_skills.py
python scripts\run_skill_ab.py --base-url http://127.0.0.1:8091
```

本次 DeepSeek A/B 使用三个高难固定用例。基线首轮成功率为 0%、平均分 30.0；获批候选为 33.3%、55.3，浏览器通过率从 0% 提升至 33.3%，功能覆盖率从 66.7% 提升至 100%，平均调用数保持 8。另一次更强约束候选回落到 0%、26.0，已拒绝并回滚。当前 `approved` 精确对应通过 A/B 的配置包：`ccc27684bd2be1718a0dd26c69757d2c1529f6a195e0211444cb5a276c660d7d`。

## 验证

```powershell
cd D:\作品集\DemoPilot\backend
uv run ruff check .
uv run pytest --basetemp=.pytest-tmp

cd D:\作品集\DemoPilot\frontend
npm.cmd run build
```

## 当前边界

- Mock Provider 是受控演示基线，不代表真实大模型效果。
- 20 条固定用例可用于回归，但不是客户真实数据集；3 条 DeepSeek 试跑只能证明链路可用，不能代表模型总体质量。
- Builder 只可生成三份静态 Web 文件；沙箱不开放 Bash、任意读写、包安装或外部网络，这是一项刻意的安全边界。
- Chromium E2E 证明受控页面在当前本机可加载和点击，不代表跨浏览器、部署环境、无障碍或真实客户数据集成已经验收。
- 生成页面使用样例数据，不代表已接入客户生产数据。
- 本地 JSON 适合 MVP；多实例部署需要数据库、对象存储、任务队列与租户隔离。
- 真实交付仍需销售人工复核，不会自动发布或发送给客户。

## 合法内核参考

- [Anthropic Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python)（MIT）
- [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)（MIT，可作为后续沙箱执行器）

项目仅参考公开可描述的 Agent 工作流思想，未复制、打包或依赖第三方复原版 Claude Code 源码。
