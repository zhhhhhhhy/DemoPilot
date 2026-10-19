# sales-v3-anomaly-27 CLI单次超时

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：使一次构建超过冻结的300秒限制
3. 逐项核对预期：终止拥有的子进程、保留部分轨迹、记Core超时；预算内可返工，不能把超时当发布成功
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
