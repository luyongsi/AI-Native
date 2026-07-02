# context-builder — RAG 上下文构建管线

五阶段上下文构建服务：SELECT → COMPRESS → ORDER → ISOLATE → SANITIZE。

对抗 Context Rot、Lost-in-the-Middle 和自条件化错误的核心工程模块。

## 架构

```
POST /context/build
  → Sanitize (检查是否需要清理)
  → Select (pgvector 语义检索 + ts_rank 全文检索)
  → Order (Lost-in-the-Middle 对抗重排)
  → Compress (代码片段压缩)
  → Isolate (填充率 >50% 预警, >75% 强制 compact)
  → 返回 context_package
```

## 快速开始

```bash
cd context-builder
pip install fastapi uvicorn psycopg2-binary pgvector asyncpg
python routes.py
# 服务监听 :8300
```

```bash
curl -X POST http://localhost:8300/context/build \
  -H "Content-Type: application/json" \
  -d '{"target_agent":"A9","req_id":"REQ-001","max_tokens":8000}'
```

## 依赖

- PostgreSQL 16 + pgvector
- Voyage AI / 千问 Embedding API

## 关联 Spec

spec-13 · Context Builder (RAG)
