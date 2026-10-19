# sales-v3-anomaly-08 连续折扣口径冲突

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：先九折再九五折，但又要求合计优惠15%
3. 逐项核对预期：指出先后折扣与百分比相加冲突，等待选定口径；不ready
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
