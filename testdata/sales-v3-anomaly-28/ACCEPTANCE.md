# sales-v3-anomaly-28 服务中断恢复

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：构建中关闭服务并重启，调用manager.recover
3. 逐项核对预期：原任务标interrupted且不发布；界面恢复另开修订；不得后台重复调用CLI
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
