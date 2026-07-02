# infra — 基础设施配置

系统全部中间件的 Docker Compose 编排和数据库初始化。

## 文件说明

| 文件 | 说明 |
|---|---|
| `docker-compose.yml` | 全部中间件编排 (9 个容器) |
| `init-db.sql` | PostgreSQL 初始表结构 (6 张业务表 + pgvector 扩展) |

## 中间件清单

| 服务 | 端口 | 说明 |
|---|---|---|
| PostgreSQL 16 + pgvector | 5432 | 业务数据 + 向量检索 |
| NATS 2.10 JetStream | 4222/8222 | Event Bus |
| Redis 7 | 6379 | 缓存/队列 |
| Temporal Server 1.24 | 7233 | 工作流引擎 |
| Temporal Web UI | 8088 | Temporal 控制台 |
| Neo4j 5 Community | 7474/7687 | 知识图谱 |
| Prometheus | 9090 | 指标采集 |
| Grafana | 3000 | 可视化面板 |
| Loki | 3100 | 日志聚合 |

## 快速开始

```bash
docker compose up -d
```

Docker 网络默认使用 `172.31.0.0/24` 网段。生产环境需配合 `configs/` 目录下的 Prometheus / Grafana 配置文件。

## 关联 Spec

spec-10 · Control Plane 基础设施 · spec-32 · 可观测性
