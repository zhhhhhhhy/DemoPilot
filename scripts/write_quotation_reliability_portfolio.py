"""Build Chinese portfolio from completed immutable audits; no page repair."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from report_quotation_reliability import summarize

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/quotation-reliability-v2'
RESULTS = ROOT / 'evaluation_sets/quotation-reliability-v2/results'
NAMES = ['development-v2-20261016', 'heldout-v3-20261017', 'heldout-clean-v4-20261017']


def read(path):
    return json.loads(path.read_text('utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    metrics = {name: summarize(RESULTS / name) for name in NAMES}
    delivery = read(DOCS / 'delivery/delivery-manifest.json')
    delivery_url = read(DOCS / 'final-service-proof.json')['base_url']
    repair = read(DOCS / 'controlled-real-repair-20261017/summary.json')
    gate = read(DOCS / 'public-gate-calibration/structural-comparison.json')
    condition = read(DOCS / 'clean-primary-generation-run-condition.json')
    audit_condition = read(DOCS / 'clean-primary-audit-run-condition.json')
    assert condition['status'] == audit_condition['status'] == 'completed'
    assert not condition['heartbeat_gaps'] and not audit_condition['heartbeat_gaps']
    closed = read(DOCS / 'original-primary-closed.json')
    assert closed['independent_audit_sha256'] == sha(RESULTS / NAMES[1] / 'independent-audit.json')
    labels = ['开发集', '原始主评测（电脑睡眠中断）', '修复后完整配对复验（复用原7组）']
    lines = []
    total_paths = 0
    for label, name in zip(labels, NAMES):
        for arm, title in [('direct', '完整规则＋自行测试'), ('reliable', '完整规则＋自行测试＋父级业务门禁')]:
            m = metrics[name]['metrics'][arm]
            a, b = m['v1'], m['v2']
            passed = a['passed_journeys'] + b['passed_journeys']
            planned = a['planned_journeys'] + b['planned_journeys']
            total_paths += planned
            lines.append(f"| {label} | {title} | {a['complete_application_success']}/{a['application_groups']} | {b['complete_application_success']}/{b['application_groups']} | {a['complete_combination_success']}/{a['combinations']}；{b['complete_combination_success']}/{b['combinations']} | {passed}/{planned} | {a['cli_calls']+b['cli_calls']} | {a['internal_repair_rounds']+b['internal_repair_rounds']} |")
    clean = metrics[NAMES[-1]]['metrics']
    totals = {arm: sum(clean[arm][v]['complete_application_success'] for v in ('v1', 'v2')) for arm in clean}
    if totals['direct'] == totals['reliable']:
        finding = f"本次复验两组严格成功交付均为{totals['direct']}/14个应用版本，没有观察到业务门禁带来的最终交付通过率增益。这里是7个应用各两个版本，不能当成14个独立需求。"
    else:
        finding = f"本次复验严格成功交付：普通组{totals['direct']}/14个应用版本，业务门禁组{totals['reliable']}/14。这里只报告本轮观察，7组应用及两个相关版本不足以支持稳定泛化收益。失败位置见独立结果与阶段记录。"
    failure_notes = []
    for arm, title in [('direct', '普通组'), ('reliable', '业务门禁组')]:
        m = clean[arm]
        bad = sum(m[v]['incorrectly_published'] for v in ('v1', 'v2'))
        hidden = sum(m[v]['functionally_correct_but_hidden'] for v in ('v1', 'v2'))
        reg = m['change_regression']
        failure_notes.append(f"{title}：错误发布{bad}个版本，业务正确但未发布{hidden}个版本，旧功能回归{reg['regressed_combinations']}/{reg['previously_correct_combinations']}个组合。")
    evidence = dict(metrics=metrics, total_main_browser_executions=total_paths,
                    independent_group_count=10, primary_group_count=7, authored_combinations=100,
                    replayed_primary_group_count=7, final_delivery=delivery,
                    audit_sha256={name: sha(RESULTS / name / 'independent-audit.json') for name in NAMES},
                    natural_comparison_finding=finding, controlled_repair=repair,
                    controlled_gate=gate, original_scores_preserved=True)
    (DOCS / 'final-evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    report = f'''# 结果与贡献

项目现在可以作为“业务验收驱动的Agent构建与可靠发布系统”介绍。你的主要贡献是把“生成页面”变成有业务标准、有预算内返工、有版本保护、有完整证据的交付过程。不能把它介绍成已经验证了生产销售收益或意图算法准确率提升。

## 目的与个人贡献

销售先给一句需求，意图模块追问缺失规则，再把完整目标交给Core生成演示。此前追加“完整规则直接输入”的对照，说明补充业务信息有价值，但未证明意图整理方式有额外准确率收益。本次据此聚焦交付可靠性：业务没做对就返工，新增需求要保住原功能，通过后才发布。

你主导的内容可以归为三项：设计可执行的业务验收契约与预算内Core循环；设计需求版本、任务所有权、验收记录与产物哈希绑定的事务发布；构建来源、分组、完整信息对照与独立浏览器评测，主动区分中间返工、最终未交付和发布后的业务缺陷。实现采用Codex辅助，个人贡献包括问题定义、架构、实验和工程取舍。

## 数据究竟有多少

10类报价流程乘10种定价规则，共100个合成业务组合；3个应用组开发、7个应用组主评测。公开来源包括官方业务文档与第一手功能需求，金额、身份和组合由本项目编写。100不是100名客户或100个独立应用。每个应用先从零生成v1，再在同一工作区增加配送需求得到v2，同时重测旧功能。改版是预先定义的测试目标，测试数据包包含两版文件；本次检验预定义改版与回归，不声称未知需求突然到来时的盲变更泛化能力。

两组使用同一gpt-6.1-sol、medium设置、每版本最多3次CLI调用、每次300秒、最多2个应用分支并行。完整业务规则、测试数据和可执行公开自测方法完全一致。普通组可以自行测试；实验变量是在Core父级增加业务门禁及错误反馈。相同上限不等于相同实际token或费用。表中返工数指父级再次调用CLI的轮数；单次CLI进程内部的自测和修改保留在轨迹中，不包含在这个计数里。

## 全量实际结果

| 批次 | 方法 | v1完整应用交付 | v2完整应用交付 | v1；v2组合交付 | 终态业务路径通过 | CLI调用 | Core内部返工 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

完整应用交付要求“已发布且最终全部业务路径通过”；正确但隐藏的候选不计成功。路径通过数与交付通过数分开。三个批次累计{total_paths}次终态浏览器路径检查，其中1820次属于同一7组需求的完整复验；重复检查不是新增独立样本。调试、受控故障和内部自测也不塞进这个分母。

{finding} CLI调用与返工数字只反映这些运行，不宣称稳定省钱、省时或人工效率提升。

{' '.join(failure_notes)} 具体终态位置及内部返工原因见[阶段记录](final-attempt-stages.json)，中间返工不会混成最终失败。

## 提升具体来自哪里

| 原来会怎样 | 做了什么 | 实际证据 |
|---|---|---|
| 文件存在、页面可打开，业务仍可能算错 | 用独立Decimal模型及状态机编译逐步验收，Chromium真实填值和点击 | 同样8个受控错误副本，结构检查发现{gate['structural_rejected']}/8，业务门禁发现{gate['business_gate_rejected']}/8；正确副本被接受 |
| 发现错误后可能直接结束或先展示错误页面 | 错误回到同一Core，预算内修复，未通过保持隐藏 | 受控集成用了{repair['actual_cli_calls']}次真实CLI调用；观察到拒绝、隐藏、修复、发布，随后独立{repair['independent_passed']}/{repair['independent_planned']}路径通过。一次调用超时也保留 |
| 旧任务晚完成，可能覆盖新需求 | 发布事务核对最新需求、唯一任务、检查记录和精确产物哈希 | 8个并发认领只有1个成功；旧版本、失败检查、篡改与重复提交有正反验证 |
| 浏览器拿旧HTML后又拿到新JS | 入口固定到版本及哈希对应的资源包 | 受控HTTP交错复现旧资源混用，固定地址在当前版本前进后仍返回原版本脚本 |

前两项故障实验是人为构造、复制体上的机制验证，不能说“8个真实失败客户全部修好”，也不能换算成生产准确率提升。原始与复验中的自然模型效果以表格为准。

## 原始失败怎么归因

原始主评测有两个未发布版本，都是qflow08可靠性组。Windows事件确认电脑按钮/合盖睡眠约8.5小时；CLI超时，根目录又出现Chromium格式DNS诊断日志，越界检查阻止发布。具体日志写入PID没有捕获。两个候选最终业务130/130通过，所以它们属于“正确产物未交付”，不是发布后发现报价功能错误。原分保留，原始整轮不用于方法因果或速度结论。

修复只调整工具日志目录、独立探针工作目录和运行条件记录，没有改业务规则、预期答案、Goal输入或CLI适配器，也没有豁免任意debug.log。随后完整重跑两组所有7个应用，复用原需求且结果已知，因此叫配对复验，不叫新增盲测。空闲睡眠请求只在进程运行期间有效，不修改电源方案，也不能阻止手动合盖/按钮睡眠。

## 能直接查看什么

- [100个组合与来源](评测集一览.md)、[方案](方案.md)、[后端机制](后端机制.md)、[失败与改进](失败与改进记录.md)。
- [可复制的简历三条](简历项目描述.md)、[30秒及两分钟讲稿和追问](面试讲稿与追问.md)。
- [全部数字、哈希与结果入口](final-evidence.json)、[独立结果与返工阶段](final-attempt-stages.json)、[实际输入同条件核验](final-information-parity.json)。
- [本机验收发布台]({delivery_url}/)：当前可见{delivery['current_visible']}/{delivery['application_groups']}类应用。仅复制原终态中独立验收通过的精确字节；原始失败分数未改。

新报价Core与发布台是可运行的独立后端模块，旧Vue销售问询表单尚未接入这个新Core。没有生产用户、成交额、人工工时、跨机器可用性或吞吐测量。结论限定在公开来源支撑的合成规则、声明的路径与受控机制验证。
'''
    (DOCS / '结果与贡献.md').write_text(report, encoding='utf-8')
    resume = '''# 简历项目描述

**DemoPilot｜业务验收驱动的 Agent 构建与可靠发布系统**  
Python、FastAPI、asyncio、SQLite、Codex CLI、Playwright

- 主导销售需求到可操作Demo的Agent交付流程，设计可插拔Harness与预算约束的Core循环，将完整目标、只读测试数据和业务验收注入任务，实现生成、真实浏览器自测、失败反馈与内部返工，并保留完整执行轨迹。
- 设计需求版本、任务所有权、验收记录与产物哈希绑定的事务发布机制；通过唯一认领、不可变资源包与固定版本URL处理旧任务覆盖和HTML/JS串版，验证并发唯一认领、旧版本任务拒绝、产物篡改与重复提交。
- 构建10类报价流程与10种定价的100个业务组合，覆盖初始生成和需求变更回归，使用完整信息、同模型预算对照及独立Chromium验收；业务门禁在8类受控语义错误中全部拦截，结构检查全部漏检，并验证真实CLI修复后才发布的闭环。

这三条强调已经验证的系统设计与工程结果。100是合成业务组合，独立应用组为10、主评测为7。8类是故障注入，不能改写成自然任务准确率从0提升到100%。实际自然生成对照、严格失败和所有分母见[结果与贡献](结果与贡献.md)。不写生产成功率、真实客户数量、收入、人工提效或分布式高并发。

较强但仍有证据的项目定位是“将代码Agent从一次性生成升级为可验证、可迭代、版本一致的交付系统”。主导架构和验收，使用Codex辅助实现；面试时应能解释代码与取舍。
'''
    (DOCS / '简历项目描述.md').write_text(resume, encoding='utf-8')
    print(json.dumps(dict(written=['final-evidence.json', '结果与贡献.md', '简历项目描述.md'],
                          browser_paths=total_paths, final_visible=delivery['current_visible'], finding=finding), ensure_ascii=False))


if __name__ == '__main__':
    main()
