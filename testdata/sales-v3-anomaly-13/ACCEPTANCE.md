# sales-v3-anomaly-13 多审批流程组合

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：同一报价必须两经理会签后再财务审批并叠加有效期
3. 逐项核对预期：不能静默删除流程条件；明确当前表达限制；不发布部分实现
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
