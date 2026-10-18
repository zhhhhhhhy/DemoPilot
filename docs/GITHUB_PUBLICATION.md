# GitHub 同步范围与本地证据

本轮同步对象为 [zhhhhhhhy/DemoPilot](https://github.com/zhhhhhhhy/DemoPilot)，包含最新源码、自动化测试、公开合成输入、评测定义、README、问题修复记录和经过检查的结果摘要。

## 上传什么

- `backend/`、`frontend/`、`scripts/` 中的源码、测试和依赖定义。
- `testdata/` 中的公开合成输入及公开验收路径，以及 `evaluation_sets/` 中的实验定义、来源和分组。
- README、`docs/ITERATION_METHODS.md`、失败分析、结果与个人贡献、面试材料以及小型结果摘要和演示截图。

## 仅保留在本机

- `.env`、登录凭据、私钥、编辑器配置、虚拟环境、依赖安装目录和构建缓存。
- 原始 CLI 对话、JSONL、进程日志、工作目录、运行数据库、实验逐次运行目录和历史执行环境快照。
- 评测专用的 `private/`、`gold/` 文件。公开业务规则与验收路径可以随源码分发，独立评分计划不直接上传。
- `docs/quotation-reliability-v2/delivery/` 中的本机发布数据库和产物副本。

忽略上传不会删除这些本地文件，也不会修改历史评分。文档中的历史路径、运行 ID 和哈希用于追溯原记录，不是登录凭据；部分路径只能在原实验电脑上打开，GitHub 仓库不等于完整原始运行档案。

## 在新目录中准备评测文件

安装依赖后，可以由公开合成规则在本地重建评测专用文件。以下命令适用于新检出的目录；原实验目录应保留冻结状态，不为同步重新生成数据。

```powershell
uv run --directory backend python ../scripts/materialize_sales_intent_v1.py
uv run --directory backend python ../scripts/materialize_quotation_intent.py --write
uv run --directory backend python ../scripts/prepare_quotation_private_plans.py
```

报价可靠性专项已经提交冻结的公开规则和清单；`prepare_quotation_private_plans.py` 只补齐遗漏的本地评分计划，生成字节必须符合清单中原有 SHA-256，不覆盖已有文件，也不改公开输入或清单。完整的 `materialize_quotation_reliability.py` 用于首次创建数据集，会拒绝重写已冻结的数据集。

重建已有规则不等于得到新的盲测需求，也不会恢复过去的模型对话、生成页面或验收执行记录。重新生成 Demo 需另开结果目录，并使用自己的 CLI 登录，不从原电脑复制凭据。

## 查看演示与证据

原电脑已有独立验收的发布台数据，可按 [运行与复现](quotation-reliability-v2/运行与复现.md) 启动。仅克隆 GitHub 不会获得这份本机数据库；需要在自己的环境执行新的生成、独立验收和交付导出，才会产生自己的发布台数据。

当前留存的结果汇总见 [结果与贡献](quotation-reliability-v2/结果与贡献.md)，问题和修复见 [README 更新日志](../README.md#更新日志) 与 [完整迭代记录](ITERATION_METHODS.md)。本轮同步不重跑模型、不更改已有实验分数，也不把摘要代替原始执行证据。

## 同步前修正的交付问题

- 整理 5 处 Python 导入顺序，保持业务逻辑不变。
- 前端默认测试的 fork worker 在本机启动超时；改为已有单 worker 限制下的线程池，默认测试命令通过 4 项测试，页面生产构建通过。
- 补充上述仅重建缺失评分计划的脚本，实际重建 20 份计划，全部匹配冻结清单哈希，公开输入不变。
- 将 201 个指向原电脑的 Markdown 链接转换为指向已提交文件的仓库相对链接。
