# neo4j — 知识图谱 Schema + Python 客户端

Neo4j 图数据库的初始 Schema、测试数据和 Python 查询客户端。

## 文件说明

| 文件 | 说明 |
|---|---|
| `import/init-schema.cypher` | 图约束 + 索引 (4 个约束, 2 个索引) |
| `import/seed-test-data.cypher` | 测试数据 (11 个节点, 9 种关系) |
| `client.py` | Python 驱动封装，含 5 个查询方法 |

## 节点模型

```
(Requirement)-[:HAS_SPEC]→(Spec)-[:DEFINES]→(API)
(Component)-[:CALLS]→(API)
(TestCase)-[:COVERS]→(Component)
```

## 快速开始

```python
from client import Neo4jClient

client = Neo4jClient(uri="bolt://localhost:7687", user="neo4j", password="password123")
result = client.trace_downstream("/api/orders/export")
print(result["components"])  # ['ExportButton', 'OrderDetailPage']
```

## 查询方法

- `trace_downstream(api_path)` — 变更影响追溯
- `trace_upstream(api_path)` — 上游溯源
- `change_impact(api_path)` — 变更影响分析
- `knowledge_graph_health()` — 知识库覆盖度统计
- `agent_artifacts(agent_id)` — Agent 产出物查询

## 关联 Spec

spec-33 · Neo4j 知识图谱 + 历史数据迁移
