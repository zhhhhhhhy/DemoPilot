# sales-v3-anomaly-25 复用旧审批

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：经理批准后销售改数量，再让客户确认
3. 逐项核对预期：先回Draft、approved-revision=-1；客户确认被拒；需重新提交审批
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
