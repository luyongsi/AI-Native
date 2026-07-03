# feishu-bot — 飞书 Bot 服务

飞书开放平台对接服务，实现需求多源汇入 + 对话卡片交互。

## 功能

- `POST /api/v1/feishu/webhook` — 飞书事件回调接收
- URL Verification 自动处理
- `im.message.receive_v1` 事件 → NATS `msg_received` 事件
- 卡片消息发送 (开发阶段 log 输出)
- HMAC-SHA256 签名验证 (开发阶段可关闭)

## 快速开始

```bash
cd feishu-bot
pip install fastapi uvicorn httpx
FEISHU_SKIP_VERIFY=true python main.py
# 服务监听 :8400
```

## 模拟测试

```bash
bash test_webhook.sh
```

## 飞书开放平台配置

需要在飞书开放平台创建企业自建应用，获取 App ID / App Secret / Verification Token，配置 Webhook URL 为 `https://<domain>/api/v1/feishu/webhook`。

## 权限 scope

- `im:message` — 接收/发送群聊消息
- `drive:doc:readonly` — 读取飞书文档
- `vc:meeting:readonly` — 读取会议信息

## 关联 Spec

spec-20 · Requirement Intake Agent (A1) · 飞书对接
