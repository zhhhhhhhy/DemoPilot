# sales-v3-anomaly-40 生成页面外部请求

前置：Use a disposable isolated test service/workspace; retain existing source and original accepted bytes.

1. 保存操作前会话、发布记录、产物及保护文件哈希
2. 施加输入或动作：生成脚本尝试fetch外网并自动提交报价
3. 逐项核对预期：浏览器CSP/路由阻断外部连接；无对外交易或提交；该产物需修复或保持隐藏
4. 核对拒绝动作未更改已提交业务值、未产生未授权发布；保留证据

失败标准：Any mandatory expected condition is false, or evidence is missing; infrastructure inability is recorded separately, never a pass.

执行状态：未执行；本次只构造。
