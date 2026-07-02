# mc-backend — Mission Control 后端 API

FastAPI 后端服务，为 Mission Control 前端提供数据源，含 WebSocket Gateway。

## API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/dashboard/stats` | GET | 流水线状态概览 |
| `/api/requirements` | GET/POST | 需求列表 + 创建 |
| `/api/requirements/:id` | GET | 需求详情 (含时间轴) |
| `/api/agents` | GET | Agent 活动流 |
| `/api/approvals` | GET | 审批列表 |
| `/api/approvals/:id/approve` | POST | 通过审批 |
| `/api/approvals/:id/reject` | POST | 打回审批 |
| `/api/tests/:req_id` | GET | 测试洞察 |
| `/api/insights` | GET | 效能仪表盘 |
| `/api/notifications` | GET | 通知列表 |
| `/api/knowledge` | GET | 知识库状态 |
| `/api/releases` | GET | 版本发布 |
| `/api/alerts` | GET | 告警列表 |
| `/metrics` | GET | Prometheus 指标 |
| `/ws/gateway` | WS | 实时事件推送 |

## 快速开始

```bash
cd mc-backend
pip install fastapi uvicorn nats-py asyncpg prometheus-client redis
python main.py
# 服务监听 :8000
```

## 依赖

- PostgreSQL 16
- NATS JetStream
- Redis

## 关联 Spec

spec-17 · MC Backend · spec-40~49 · API 扩展
