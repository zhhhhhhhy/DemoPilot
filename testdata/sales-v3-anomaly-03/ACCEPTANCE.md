# sales-v3-anomaly-03 审批主体未提供

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：用户只说需要审批，未说明由谁和顺序
3. 逐项核对预期：询问审批主体与顺序；不得自行采用经理单审；不构建
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
