# sales-v3-anomaly-34 路径穿越读取

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：accepted URL使用../或编码变体尝试读取外部文件
3. 逐项核对预期：404/409；响应不含外部内容；只解析已验收bundle内文件
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
