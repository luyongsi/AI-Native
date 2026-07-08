# JAP Plus 吸收计划：Agent Skills/Tools/MCP 完整架构设计

> **背景**：JAP Plus 文档仓库提供了需求引出、文件化流水线、降级机制等可复用的工程实践。本文档将这些经验转化为 AI Agent 系统完整的 Agent Skills/Tools/MCP 架构。
> **核心方向**：每个 Agent 有独立 Skills，跨 Agent 共享公共 Skills 和 MCP 服务，知识库等基础能力通过 MCP 协议统一暴露。

---

## 一、目标架构：三层模型

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     LAYER 3: MCP 公共服务层                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ knowledge-   │  │ code-search  │  │ spec-        │  │ sandbox-    │ │
│  │ base-mcp     │  │ -mcp         │  │ validator    │  │ runner      │ │
│  │ 知识库查询    │  │ 代码搜索      │  │ Spec校验     │  │ 沙箱执行     │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘ │
│         └──────────────────┴─────────────────┴─────────────────┘         │
│                              │ MCP Protocol                              │
├──────────────────────────────┼───────────────────────────────────────────┤
│                     LAYER 2: 公共 Skills/Tools 层                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ dedup.tool   │  │ fallback-    │  │ cross-check  │  │ mcp-        │ │
│  │ 问题去重      │  │ parser.tool  │  │ .tool        │  │ client.tool │ │
│  │              │  │ JSON回退解析  │  │ 跨产物校验    │  │ MCP客户端    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
│                     Shared by All Agents                                │
├──────────────────────────────────────────────────────────────────────────┤
│                     LAYER 1: Agent 独立 Skills 层                        │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐               │
│  │  A1    │ │  A2    │ │  A3    │ │  A4    │ │  A5    │  ...           │
│  │ 需求澄清│ │ 知识分析│ │ UI生成 │ │ Spec撰写│ │ 设计评审│               │
│  │ skills │ │ skills │ │ skills │ │ skills │ │ skills │               │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘               │
└──────────────────────────────────────────────────────────────────────────┘
```

```
Agents 请求工具调用的数据流：

Agent.execute()
    │
    ├─ SkillLoader.load_agent_skills(agent_id)     ← Layer 1: 独立 Skills
    │
    ├─ SkillLoader.load_shared_skills()            ← Layer 2: 公共 Skills
    │
    └─ MCPClient.call_tool("knowledge-base-mcp",   ← Layer 3: MCP 公共服务
         "search_knowledge", {query: "..."})
```

---

## 二、目录结构

```
.ai-native/
├── agents/                         ← Layer 1: 每个 Agent 的独立 Skills
│   ├── A1/
│   │   ├── skills/
│   │   │   ├── elicitation.skill.md       # 需求澄清规则
│   │   │   ├── dimension.skill.md         # 问题维度定义
│   │   │   └── mode-config.skill.md       # 快速/深度模式配置
│   │   └── tools/
│   │       └── domain-detector.tool.md    # A1 专有：领域关键词识别
│   │
│   ├── A2/
│   │   ├── skills/
│   │   │   ├── knowledge-analysis.skill.md # 知识分析规则
│   │   │   └── conflict-detection.skill.md # 冲突检测规则
│   │   └── tools/
│   │       └── rag-composer.tool.md        # A2 专有：RAG 结果编排
│   │
│   ├── A3/
│   │   ├── skills/
│   │   │   ├── ui-generation.skill.md      # UI 生成约束
│   │   │   └── prototype-format.skill.md   # 原型格式规范
│   │   └── tools/
│   │       └── annotation-parser.tool.md   # A3 专有：标注解析
│   │
│   ├── A4/
│   │   ├── skills/
│   │   │   ├── spec-writing.skill.md       # Spec 撰写规则
│   │   │   ├── api-schema.skill.md         # API Schema 约束
│   │   │   ├── erd-design.skill.md         # ERD 设计约束
│   │   │   └── state-machine.skill.md      # 状态机设计约束
│   │   └── tools/
│   │       ├── ddl-validator.tool.md       # A4 专有：DDL 校验
│   │       └── schema-linter.tool.md       # A4 专有：Schema Lint
│   │
│   ├── A5/
│   │   ├── skills/
│   │   │   ├── design-review.skill.md      # 设计评审检查清单
│   │   │   ├── ux-heuristic.skill.md       # UX 启发式评审
│   │   │   └── security-checklist.skill.md # 安全检查清单
│   │   └── tools/
│   │       └── n1-detector.tool.md         # A5 专有：N+1 查询检测
│   │
│   ├── A6/  ← DAG 分解
│   ├── A7/  ← 测试用例生成
│   ├── A8/  ← 架构专家
│   ├── A9/  ← 开发 Agent
│   ├── A10/ ← CI/CD
│   ├── A11/ ← 自动测试
│   ├── A12/ ← 代码审查
│   ├── A13/ ← 发布
│   ├── K14/ ← 知识沉淀
│   └── K15/ ← 变更传播
│
├── shared/                         ← Layer 2: 公共 Skills/Tools
│   ├── skills/
│   │   ├── quality-gates.skill.md        # 跨 Agent 质量门禁
│   │   ├── error-handling.skill.md       # 通用错误处理规则
│   │   └── security-baseline.skill.md    # 安全基线（所有 Agent 遵守）
│   └── tools/
│       ├── dedup.tool.py                 # 问题去重（Python 实现）
│       ├── fallback-parser.tool.py       # JSON 回退解析（Python 实现）
│       ├── cross-check.tool.py           # 跨产物一致性校验（Python）
│       └── mcp-client.tool.py            # MCP 客户端封装
│
├── mcp/                            ← Layer 3: MCP 公共服务定义
│   ├── knowledge-base-mcp/
│   │   ├── server.py                     # MCP Server: 知识库
│   │   ├── tools.py                      # 暴露的 tools: search, retrieve, index
│   │   └── config.yaml                   # 连接配置 (pgvector, neo4j)
│   │
│   ├── code-search-mcp/
│   │   ├── server.py                     # MCP Server: 代码搜索
│   │   └── config.yaml
│   │
│   ├── spec-validator-mcp/
│   │   ├── server.py                     # MCP Server: Spec 校验
│   │   └── config.yaml
│   │
│   ├── sandbox-runner-mcp/
│   │   ├── server.py                     # MCP Server: 沙箱执行
│   │   └── config.yaml
│   │
│   └── registry.yaml                # MCP 服务注册表
│
└── README.md                       # 本架构的使用说明
```

---

## 三、Layer 3: MCP 公共服务层

### 3.1 设计原则

- 每个 MCP 服务是独立的 Python 进程，通过 stdio 或 HTTP 与 Agent 通信
- 服务注册在 `registry.yaml` 中，MCPClient 启动时自动发现
- 服务之间无直接依赖，通过 Event Bus 解耦

### 3.2 知识库 MCP 服务（最高优先级）

这是**所有 Agent 都可能调用的**公共服务。

```yaml
# .ai-native/mcp/knowledge-base-mcp/config.yaml
server:
  name: knowledge-base-mcp
  description: "知识库查询服务 - 提供语义搜索、图谱追溯、历史需求检索"
  transport: stdio        # stdio | http
  port: 9101              # http 模式下的端口

tools:
  - name: search_knowledge
    description: "语义搜索知识库，返回相关文档片段"
    parameters:
      query: { type: string, required: true, description: "搜索查询" }
      top_k: { type: integer, default: 5 }
      filters:
        type: object
        properties:
          doc_type: { type: string, enum: [code, doc, spec, design, log] }
          agent_id: { type: string }
          min_relevance: { type: number, default: 0.4 }

  - name: retrieve_by_id
    description: "按 ID 精确获取知识条目"
    parameters:
      chunk_id: { type: string, required: true }

  - name: trace_dependencies
    description: "追溯 API 或模块的上下游依赖（Neo4j 图谱）"
    parameters:
      api_path: { type: string, required: true }
      direction: { type: string, enum: [upstream, downstream, both], default: both }

  - name: search_similar_requirements
    description: "搜索相似历史需求，辅助 A1/A2 去重和参考"
    parameters:
      requirement_text: { type: string, required: true }
      top_k: { type: integer, default: 3 }

  - name: get_context_for_agent
    description: "为指定 Agent 构建上下文，执行 Select->Order->Compress->Isolate 流水线"
    parameters:
      agent_id: { type: string, required: true }
      req_id: { type: string, required: true }
      max_tokens: { type: integer, default: 8000 }
```

### 3.3 Python MCP Server 实现骨架

```python
# .ai-native/mcp/knowledge-base-mcp/server.py
"""
知识库 MCP Server - 基于 MCP SDK 暴露知识库能力
被所有 Agent 通过 MCPClient 调用
"""
import asyncio
import json
import logging
from pathlib import Path

from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .tools import (
    search_knowledge,
    retrieve_by_id,
    trace_dependencies,
    search_similar_requirements,
    get_context_for_agent,
)

logger = logging.getLogger("knowledge-base-mcp")

server = Server("knowledge-base-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_knowledge",
            description="语义搜索知识库（pgvector 混合搜索 + 全文搜索），返回相关文档片段",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "top_k": {"type": "integer", "default": 5},
                    "filters": {
                        "type": "object",
                        "properties": {
                            "doc_type": {"type": "string", "enum": ["code", "doc", "spec", "design", "log"]},
                            "agent_id": {"type": "string"},
                            "min_relevance": {"type": "number", "default": 0.4},
                        },
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="trace_dependencies",
            description="追溯 API/模块的上下游依赖（Neo4j 图谱查询）",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_path": {"type": "string", "description": "API 路径，如 /api/v1/orders"},
                    "direction": {"type": "string", "enum": ["upstream", "downstream", "both"], "default": "both"},
                },
                "required": ["api_path"],
            },
        ),
        Tool(
            name="search_similar_requirements",
            description="搜索相似历史需求（语义相似度 > 0.7），辅助去重和参考",
            inputSchema={
                "type": "object",
                "properties": {
                    "requirement_text": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
                "required": ["requirement_text"],
            },
        ),
        Tool(
            name="get_context_for_agent",
            description="为指定 Agent 执行 Context Builder 五阶段流水线",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "req_id": {"type": "string"},
                    "max_tokens": {"type": "integer", "default": 8000},
                },
                "required": ["agent_id", "req_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """路由到对应的工具实现"""
    logger.info(f"[knowledge-base-mcp] Tool call: {name}")

    tool_map = {
        "search_knowledge": search_knowledge,
        "retrieve_by_id": retrieve_by_id,
        "trace_dependencies": trace_dependencies,
        "search_similar_requirements": search_similar_requirements,
        "get_context_for_agent": get_context_for_agent,
    }

    handler = tool_map.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    try:
        result = await handler(**arguments)
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except Exception as e:
        logger.exception(f"Tool {name} failed")
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

```python
# .ai-native/mcp/knowledge-base-mcp/tools.py
"""知识库 MCP Server 的 Tool 实现"""

import os
import json
import logging
from typing import Optional

import asyncpg
from neo4j import AsyncGraphDatabase

logger = logging.getLogger(__name__)

_pg_pool: Optional[asyncpg.Pool] = None
_neo4j_driver = None


async def _get_pg():
    global _pg_pool
    if _pg_pool is None:
        DATABASE_URL = os.environ.get("DATABASE_URL",
            "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native")
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pg_pool


async def _get_neo4j():
    global _neo4j_driver
    if _neo4j_driver is None:
        NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
        NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
        _neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _neo4j_driver


async def search_knowledge(
    query: str,
    top_k: int = 5,
    filters: Optional[dict] = None,
) -> dict:
    """混合搜索知识库（pgvector 语义搜索 + PostgreSQL 全文搜索）"""
    pool = await _get_pg()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, doc_id, title, content, doc_type,
                   1 - (embedding <=> $1::vector) AS relevance
            FROM knowledge_chunks
            WHERE 1 - (embedding <=> $1::vector) > 0.4
            ORDER BY relevance DESC
            LIMIT $2
        """, query, top_k * 2)

        results = []
        for row in rows:
            doc_type = row["doc_type"]
            if filters:
                if "doc_type" in filters and doc_type != filters["doc_type"]:
                    continue
                if "agent_id" in filters:
                    pass
            results.append({
                "chunk_id": str(row["id"]),
                "title": row["title"],
                "content": row["content"][:800],
                "doc_type": doc_type,
                "relevance": round(float(row["relevance"]), 3),
            })
            if len(results) >= top_k:
                break

        return {"results": results, "total": len(results)}


async def retrieve_by_id(chunk_id: str) -> dict:
    """按 ID 精确获取知识条目"""
    pool = await _get_pg()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, doc_id, title, content, doc_type FROM knowledge_chunks WHERE id = $1::uuid",
            chunk_id,
        )
        if not row:
            return {"found": False, "chunk_id": chunk_id}
        return {
            "found": True,
            "chunk_id": str(row["id"]),
            "title": row["title"],
            "content": row["content"],
            "doc_type": row["doc_type"],
        }


async def trace_dependencies(api_path: str, direction: str = "both") -> dict:
    """追溯依赖关系（Neo4j 图谱）"""
    driver = await _get_neo4j()
    results = {"api_path": api_path, "direction": direction}

    async with driver.session() as session:
        if direction in ("downstream", "both"):
            downstream = await session.run("""
                MATCH (a:API {path: $path})-[:DEPENDS_ON*1..3]->(d:Component)
                RETURN d.name AS name, d.type AS type
            """, path=api_path)
            results["downstream"] = [dict(r) for r in await downstream.data()]

        if direction in ("upstream", "both"):
            upstream = await session.run("""
                MATCH (u:Component)-[:DEPENDS_ON*1..3]->(a:API {path: $path})
                RETURN u.name AS name, u.type AS type
            """, path=api_path)
            results["upstream"] = [dict(r) for r in await upstream.data()]

    return results


async def search_similar_requirements(requirement_text: str, top_k: int = 3) -> dict:
    """搜索相似历史需求"""
    pool = await _get_pg()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM requirements
            WHERE 1 - (embedding <=> $1::vector) > 0.7
            ORDER BY similarity DESC
            LIMIT $2
        """, requirement_text, top_k)

        return {
            "similar": [
                {
                    "req_id": str(row["id"]),
                    "title": row["title"],
                    "similarity": round(float(row["similarity"]), 3),
                }
                for row in rows
            ]
        }


async def get_context_for_agent(agent_id: str, req_id: str, max_tokens: int = 8000) -> dict:
    """为指定 Agent 执行 Context Builder 五阶段流水线"""
    from context_builder.pipeline import ContextBuilder

    builder = ContextBuilder(max_tokens=max_tokens)
    items = await builder.build(agent_id, req_id)

    return {
        "context_items": [
            {
                "type": item.type,
                "content": item.content[:500],
                "relevance": item.relevance,
                "position": item.position,
                "tokens": item.tokens,
                "file": item.file,
                "compressed": item.compressed,
            }
            for item in items
        ],
        "total_tokens": sum(i.tokens for i in items),
        "item_count": len(items),
    }
```

### 3.4 其他 MCP 公共服务规划

| MCP 服务 | 暴露的 Tools | 消费方 |
|----------|------------|--------|
| **knowledge-base-mcp** | search_knowledge, trace_dependencies, search_similar_requirements, get_context_for_agent | **所有 Agent** |
| **code-search-mcp** | search_code, grep_symbol, find_definition, list_files | A2, A5, A6, A8, A9, A12 |
| **spec-validator-mcp** | validate_openapi, validate_erd, check_consistency, lint_spec | A4, A5, A8 |
| **sandbox-runner-mcp** | execute_code, run_tests, lint_code, security_scan | A9, A10, A11, A12 |

### 3.5 MCP 服务注册表

```yaml
# .ai-native/mcp/registry.yaml
version: "1.0"

servers:
  knowledge-base-mcp:
    enabled: true
    transport: stdio
    command: python
    args: ["-m", "ai_native.mcp.knowledge_base_mcp.server"]
    env:
      DATABASE_URL: "${DATABASE_URL}"
      NEO4J_URI: "${NEO4J_URI}"
    tools:
      - search_knowledge
      - retrieve_by_id
      - trace_dependencies
      - search_similar_requirements
      - get_context_for_agent

  code-search-mcp:
    enabled: true
    transport: stdio
    command: python
    args: ["-m", "ai_native.mcp.code_search_mcp.server"]
    tools:
      - search_code
      - grep_symbol
      - find_definition
      - list_files

  spec-validator-mcp:
    enabled: true
    transport: stdio
    command: python
    args: ["-m", "ai_native.mcp.spec_validator_mcp.server"]
    tools:
      - validate_openapi
      - validate_erd
      - check_consistency
      - lint_spec

  sandbox-runner-mcp:
    enabled: true
    transport: stdio
    command: python
    args: ["-m", "ai_native.mcp.sandbox_runner_mcp.server"]
    tools:
      - execute_code
      - run_tests
      - lint_code
      - security_scan
```

---

## 四、Layer 2: 公共 Skills/Tools 层

### 4.1 公共 Skill 示例：质量门禁

```markdown
# .ai-native/shared/skills/quality-gates.skill.md
---
skill_id: quality-gates-v1
applies_to: "*"
version: 1.0
ttl_seconds: 600
---

# 质量门禁规则（所有 Agent 遵守）

## 通用质量标准
- LLM 输出必须符合指定的 Schema（JSON/OpenAPI/Gherkin 等）
- 命名必须统一：表名 snake_case、API 路径 kebab-case、类名 PascalCase
- 错误信息必须包含错误码、描述、建议操作
- 所有产出物必须保留生成溯源（agent_id、req_id、timestamp）

## 跨 Agent 约束
- A4 产出的 API Schema 字段必须与 ERD 列名一致
- A6 的 DAG 任务数必须覆盖 A4 的所有核心用例
- A7 的测试用例必须覆盖 A4 状态机的所有转换路径
- A9 的代码必须通过 A11 的变异测试（mutation score >= 80%）

## 门禁阻断条件
- API-ERD 字段不一致 -> Gate 2 阻断
- 状态机-用例覆盖缺口 -> Gate 2 阻断
- 变异测试得分 < 60% -> Gate 3 阻断
- 安全扫描发现 critical 漏洞 -> Gate 3 阻断
```

### 4.2 公共 Tool 示例：MCP 客户端封装

```python
# .ai-native/shared/tools/mcp-client.tool.py
"""
MCP 客户端 - 所有 Agent 调用 MCP 公共服务的统一入口

基于 MCP SDK (Python)，封装连接管理、tool 发现、调用和超时。
参考 JAP Plus mcpClient.ts 的设计（多服务器连接、候选工具查找、错误诊断）。
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Any
from contextlib import asynccontextmanager

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """单个 MCP Server 的连接管理"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self._session: Optional[ClientSession] = None
        self._tools_cache: list[dict] = []
        self._tools_cache_time: float = 0
        self._cache_ttl: float = 300  # 5 分钟

    async def connect(self):
        """建立 stdio 连接"""
        params = StdioServerParameters(
            command=self.config["command"],
            args=self.config.get("args", []),
            env=self.config.get("env", {}),
        )
        self._read, self._write = await stdio_client(params).__aenter__()
        self._session = await ClientSession(self._read, self._write).__aenter__()
        await self._session.initialize()
        logger.info(f"[MCPClient] Connected to {self.name}")

    async def list_tools(self, force_refresh: bool = False) -> list[dict]:
        """列出可用工具（带缓存）"""
        if not force_refresh and self._tools_cache and (time.time() - self._tools_cache_time) < self._cache_ttl:
            return self._tools_cache

        result = await self._session.list_tools()
        self._tools_cache = [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in result.tools
        ]
        self._tools_cache_time = time.time()
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: dict, timeout: float = 30.0) -> dict:
        """调用工具，带超时"""
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
            for content in result.content:
                if hasattr(content, "text"):
                    return json.loads(content.text)
            return {"raw": str(result.content)}
        except asyncio.TimeoutError:
            logger.error(f"[MCPClient] Tool {tool_name} timed out after {timeout}s")
            return {"error": "timeout", "tool": tool_name}
        except Exception as e:
            logger.error(f"[MCPClient] Tool {tool_name} failed: {e}")
            return {"error": str(e), "tool": tool_name}

    async def close(self):
        if self._session:
            await self._session.__aexit__(None, None, None)
            await self._write.close()


class MCPClient:
    """
    多 MCP Server 的统一客户端。

    使用方式：
        client = MCPClient()
        await client.start()
        result = await client.call_tool("knowledge-base-mcp", "search_knowledge", {"query": "用户登录"})
        await client.stop()

    参考 JAP Plus mcpClient.ts:
      - 多服务器动态连接
      - 工具自动发现和缓存
      - 候选工具查找（call_text_tool_by_candidates）
      - 错误诊断
    """

    def __init__(self, registry_path: str = ".ai-native/mcp/registry.yaml"):
        self.registry_path = Path(registry_path)
        self._connections: dict[str, MCPServerConnection] = {}
        self._tool_index: dict[str, list[str]] = {}  # tool_name -> [server_names]

    async def start(self, server_names: Optional[list[str]] = None):
        """启动指定（或全部）MCP 服务器连接"""
        registry = self._load_registry()

        targets = server_names or [
            name for name, cfg in registry.get("servers", {}).items()
            if cfg.get("enabled", True)
        ]

        for name in targets:
            if name in self._connections:
                continue
            cfg = registry["servers"].get(name)
            if not cfg:
                logger.warning(f"[MCPClient] Unknown server: {name}")
                continue

            try:
                conn = MCPServerConnection(name, cfg)
                await conn.connect()
                self._connections[name] = conn

                tools = await conn.list_tools()
                for t in tools:
                    self._tool_index.setdefault(t["name"], []).append(name)

                logger.info(f"[MCPClient] {name}: {len(tools)} tools available")
            except Exception as e:
                logger.error(f"[MCPClient] Failed to connect {name}: {e}")
                # 失败不阻塞 - 和 JAP Plus 一样的容错策略

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        调用指定 MCP Server 的工具。

        支持自动服务发现：如果 server_name 为 "auto"，根据 tool_name 自动路由。
        """
        if server_name == "auto":
            candidates = self._tool_index.get(tool_name, [])
            if not candidates:
                return {"error": f"No server found for tool: {tool_name}"}
            server_name = candidates[0]

        conn = self._connections.get(server_name)
        if not conn:
            return {"error": f"Server not connected: {server_name}"}

        return await conn.call_tool(tool_name, arguments, timeout=timeout)

    async def call_tool_by_candidates(
        self,
        tool_names: list[str],
        arguments: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        按候选名称查找并调用工具 - 找到第一个就调用。

        参考 JAP Plus callTextToolByCandidates
        """
        for tool_name in tool_names:
            servers = self._tool_index.get(tool_name, [])
            if not servers:
                continue

            for server_name in servers:
                result = await self.call_tool(server_name, tool_name, arguments, timeout)
                if "error" not in result:
                    return {"tool_used": tool_name, "server": server_name, "result": result}

        return {"error": f"No candidate tool found among: {tool_names}"}

    async def list_all_tools(self) -> dict[str, list[dict]]:
        """列出所有已连接服务器的工具"""
        result = {}
        for name, conn in self._connections.items():
            result[name] = await conn.list_tools()
        return result

    def get_diagnostics(self) -> dict:
        """获取 MCP 服务诊断信息（参考 JAP Plus 的 PRD 工具诊断）"""
        diag = {"connected_servers": len(self._connections), "servers": {}}
        for name, conn in self._connections.items():
            diag["servers"][name] = {
                "tool_count": len(conn._tools_cache),
                "cache_age_seconds": round(time.time() - conn._tools_cache_time, 1) if conn._tools_cache_time else None,
            }
        return diag

    async def stop(self):
        for name, conn in self._connections.items():
            try:
                await conn.close()
            except Exception:
                pass
        self._connections.clear()
        self._tool_index.clear()

    def _load_registry(self) -> dict:
        if not self.registry_path.exists():
            logger.warning(f"[MCPClient] Registry not found: {self.registry_path}")
            return {"servers": {}}
        with open(self.registry_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
```

---

## 五、BaseAgentWorker 集成

### 5.1 改造后的 BaseAgentWorker

```python
# repos/agent-workers/base_worker.py - 新增的 Skills + MCP 集成方法

class BaseAgentWorker:
    """所有 Agent Worker 的基类"""

    agent_id: str = ""
    agent_type: str = ""

    # 类级别单例
    _skill_loader: "SkillLoader" = None
    _mcp_client: "MCPClient" = None

    @classmethod
    def get_skill_loader(cls) -> "SkillLoader":
        if cls._skill_loader is None:
            from skill_loader import SkillLoader
            cls._skill_loader = SkillLoader()
        return cls._skill_loader

    @classmethod
    def get_mcp_client(cls) -> "MCPClient":
        if cls._mcp_client is None:
            from shared.tools.mcp_client import MCPClient
            cls._mcp_client = MCPClient()
        return cls._mcp_client

    @classmethod
    async def start_shared_services(cls, server_names: list[str] = None):
        """启动公共 MCP 服务连接（在 worker_launcher.py 中调用）"""
        client = cls.get_mcp_client()
        await client.start(server_names=server_names)

    @classmethod
    async def stop_shared_services(cls):
        if cls._mcp_client:
            await cls._mcp_client.stop()
            cls._mcp_client = None

    async def build_enhanced_prompt(
        self,
        base_prompt: str,
        workspace_path: str = None,
        include_shared: bool = True,
    ) -> str:
        """
        构建增强的系统提示词。

        加载顺序：
        1. Agent 独立 Skills（.ai-native/agents/{agent_id}/skills/*.skill.md）
        2. 公共 Skills（.ai-native/shared/skills/*.skill.md）

        参考 JAP Plus skillContext.ts + promptTexts.ts
        """
        loader = self.get_skill_loader()
        parts = [base_prompt]

        # Layer 1: Agent 独立 Skills
        agent_skills = loader.load_agent_skills(self.agent_id, workspace_path)
        if agent_skills:
            parts.append(agent_skills)

        # Layer 2: 公共 Skills
        if include_shared:
            shared_skills = loader.load_shared_skills()
            if shared_skills:
                parts.append(shared_skills)

        return "\n\n".join(parts)

    async def mcp_call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        调用 MCP 公共服务（Layer 3）。

        示例:
            result = await self.mcp_call(
                "knowledge-base-mcp",
                "search_knowledge",
                {"query": "用户认证流程", "top_k": 5}
            )
        """
        mcp = self.get_mcp_client()
        return await mcp.call_tool(server_name, tool_name, arguments, timeout=timeout)

    async def mcp_search_knowledge(self, query: str, top_k: int = 5, **filters) -> dict:
        """快捷方法：知识库搜索"""
        return await self.mcp_call(
            "knowledge-base-mcp",
            "search_knowledge",
            {"query": query, "top_k": top_k, "filters": filters or None},
        )

    async def mcp_get_context(self, req_id: str, max_tokens: int = 8000) -> dict:
        """快捷方法：获取 Agent 上下文"""
        return await self.mcp_call(
            "knowledge-base-mcp",
            "get_context_for_agent",
            {"agent_id": self.agent_id, "req_id": req_id, "max_tokens": max_tokens},
        )

    async def call_llm_with_fallback(
        self,
        messages: list,
        *,
        task_type: str = "text",
        temperature: float = 0.3,
        max_tokens: int = 2000,
        req_id: str = "",
        workflow_id: str = "",
        fallback_parser: bool = True,
    ) -> str | None:
        """
        增强的 LLM 调用：
        1. 自动注入 Skills 到 system prompt
        2. JSON 回退解析

        参考 JAP Plus structuredOutputFallback.ts
        """
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = await self.build_enhanced_prompt(messages[0]["content"])

        result = await self.call_llm(
            messages,
            task_type=task_type,
            temperature=temperature,
            max_tokens=max_tokens,
            req_id=req_id,
            workflow_id=workflow_id,
        )

        if result is not None:
            return result

        if fallback_parser:
            return await self._structured_fallback(messages, task_type, temperature, max_tokens, req_id, workflow_id)

        return None

    async def _structured_fallback(self, messages, task_type, temperature, max_tokens, req_id, workflow_id) -> str | None:
        """结构化输出 JSON 回退 - 参考 JAP Plus invokeStructuredWithJsonFallback"""
        import re

        fallback_msg = "\n\n请直接输出纯 JSON，不要 markdown 代码块包裹。只输出 JSON。"
        if messages and messages[-1].get("role") == "user":
            messages[-1]["content"] += fallback_msg

        try:
            result = await self.call_llm(
                messages,
                task_type=task_type,
                temperature=0.0,
                max_tokens=max_tokens,
                req_id=f"{req_id}-fallback",
                workflow_id=workflow_id,
            )
            if result is None:
                return None

            m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', result)
            if m:
                return m.group(1).strip()
            m = re.search(r'\{[\s\S]*\}', result)
            if m:
                return m.group(0).strip()
            return result
        except Exception:
            return None
```

### 5.2 SkillLoader 完整实现

```python
# repos/agent-workers/skill_loader.py

import re
import time
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SkillRule:
    skill_id: str
    applies_to: str
    version: str
    ttl_seconds: int
    content: str
    raw_content: str
    frontmatter: dict


@dataclass
class ToolDef:
    tool_id: str
    tool_type: str
    version: str
    content: str
    frontmatter: dict


class SkillLoader:
    """
    统一技能/工具加载器。
    支持三层模型：Agent 独立 Skills + 公共 Skills + MCP 服务

    参考 JAP Plus skillContext.ts + mcpClient.ts 的设计。
    """

    def __init__(self, base_dir: str = ".ai-native"):
        self.base_dir = Path(base_dir)
        self._skill_cache: dict[str, tuple[SkillRule, float]] = {}
        self._default_ttl = 300
        self._current_agent: Optional[str] = None

    # === Layer 1: Agent 独立 Skills ===

    def load_agent_skills(self, agent_id: str, workspace_path: Optional[str] = None) -> str:
        """加载指定 Agent 的所有独立 Skills"""
        skills_dir = self._resolve_agent_skills_dir(agent_id, workspace_path)
        if not skills_dir or not skills_dir.exists():
            return ""

        combined = []
        for file_path in sorted(skills_dir.glob("*.skill.md")):
            skill = self._parse_skill_file(file_path)
            if skill is None:
                continue
            combined.append(skill.content)

        if combined:
            logger.info(f"[SkillLoader] {agent_id}: loaded {len(combined)} agent skills")
        return "\n\n".join(combined)

    def load_agent_tools(self, agent_id: str, workspace_path: Optional[str] = None) -> list[ToolDef]:
        """加载指定 Agent 的独立 Tool 定义"""
        tools_dir = self._resolve_agent_tools_dir(agent_id, workspace_path)
        if not tools_dir or not tools_dir.exists():
            return []

        tools = []
        for file_path in sorted(tools_dir.glob("*.tool.md")):
            tool = self._parse_tool_file(file_path)
            if tool:
                tools.append(tool)
        return tools

    # === Layer 2: 公共 Skills/Tools ===

    def load_shared_skills(self) -> str:
        """加载所有公共 Skills"""
        skills_dir = self.base_dir / "shared" / "skills"
        if not skills_dir.exists():
            return ""

        combined = []
        for file_path in sorted(skills_dir.glob("*.skill.md")):
            skill = self._parse_skill_file(file_path)
            if skill is None:
                continue
            applies = skill.frontmatter.get("applies_to", "*")
            if applies == "*":
                combined.append(skill.content)
            elif self._current_agent and self._current_agent in applies.split(","):
                combined.append(skill.content)

        return "\n\n".join(combined)

    def load_shared_tools(self) -> list[ToolDef]:
        """加载所有公共 Tool 定义"""
        tools_dir = self.base_dir / "shared" / "tools"
        if not tools_dir.exists():
            return []

        tools = []
        for file_path in sorted(tools_dir.glob("*.tool.md")):
            tool = self._parse_tool_file(file_path)
            if tool:
                tools.append(tool)
        return tools

    # === 组合加载 ===

    def load_all_for_agent(self, agent_id: str, workspace_path: Optional[str] = None) -> str:
        """加载 Agent 需要的全部技能规则（独立 + 公共）"""
        self._current_agent = agent_id

        parts = []
        agent_skills = self.load_agent_skills(agent_id, workspace_path)
        if agent_skills:
            parts.append(agent_skills)

        shared_skills = self.load_shared_skills()
        if shared_skills:
            parts.append(shared_skills)

        self._current_agent = None
        return "\n\n".join(parts)

    def get_all_tools_for_agent(self, agent_id: str, workspace_path: Optional[str] = None) -> list[ToolDef]:
        """获取 Agent 可用的所有 Tool（独立 + 公共）"""
        return self.load_agent_tools(agent_id, workspace_path) + self.load_shared_tools()

    # === 单文件加载（带缓存） ===

    def load_skill(self, skill_name: str, workspace_path: Optional[str] = None) -> str:
        """按名称加载单个 Skill 文件"""
        # 先在 Agent 目录找，再在 shared 目录找
        for search_dir in [
            self._resolve_agent_skills_dir(self._current_agent or "", workspace_path),
            self.base_dir / "shared" / "skills",
        ]:
            if search_dir is None:
                continue
            file_path = search_dir / f"{skill_name}.skill.md"
            if file_path.exists():
                skill = self._parse_skill_file(file_path)
                return skill.content if skill else ""
        return ""

    # === 缓存管理 ===

    def invalidate(self, cache_key: Optional[str] = None):
        if cache_key:
            self._skill_cache.pop(cache_key, None)
        else:
            self._skill_cache.clear()

    # === 内部方法 ===

    def _parse_skill_file(self, file_path: Path) -> Optional[SkillRule]:
        if not file_path.exists():
            return None

        cache_key = str(file_path)
        cached = self._skill_cache.get(cache_key)
        if cached:
            rule, expire_at = cached
            if time.time() < expire_at:
                return rule

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(raw)

        wrapped = f"[SkillRules]\n# {frontmatter.get('skill_id', file_path.stem)}\n\n{body}\n[/SkillRules]"

        rule = SkillRule(
            skill_id=frontmatter.get("skill_id", file_path.stem),
            applies_to=frontmatter.get("applies_to", "*"),
            version=frontmatter.get("version", "1.0"),
            ttl_seconds=int(frontmatter.get("ttl_seconds", self._default_ttl)),
            content=wrapped,
            raw_content=body,
            frontmatter=frontmatter,
        )
        self._skill_cache[cache_key] = (rule, time.time() + rule.ttl_seconds)
        return rule

    def _parse_tool_file(self, file_path: Path) -> Optional[ToolDef]:
        if not file_path.exists():
            return None

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(raw)

        return ToolDef(
            tool_id=frontmatter.get("tool_id", file_path.stem),
            tool_type=frontmatter.get("tool_type", "utility"),
            version=frontmatter.get("version", "1.0"),
            content=body,
            frontmatter=frontmatter,
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict, str]:
        frontmatter = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        frontmatter[k.strip()] = v.strip()
                body = parts[2].strip()
        return frontmatter, body

    def _resolve_agent_skills_dir(self, agent_id: str, workspace_path: Optional[str] = None) -> Optional[Path]:
        if workspace_path:
            ws_dir = Path(workspace_path) / ".ai-native" / "agents" / agent_id / "skills"
            if ws_dir.exists():
                return ws_dir
        return self.base_dir / "agents" / agent_id / "skills"

    def _resolve_agent_tools_dir(self, agent_id: str, workspace_path: Optional[str] = None) -> Optional[Path]:
        if workspace_path:
            ws_dir = Path(workspace_path) / ".ai-native" / "agents" / agent_id / "tools"
            if ws_dir.exists():
                return ws_dir
        return self.base_dir / "agents" / agent_id / "tools"
```

---

## 六、各 Agent 的 Skills/Tools/MCP 完整映射

| Agent | 独立 Skills（Layer 1） | 独立 Tools（Layer 1） | 公共 Skills（Layer 2） | MCP 服务（Layer 3） |
|-------|----------------------|---------------------|---------------------|-------------------|
| **A1** | elicitation, dimension, mode-config | domain-detector | quality-gates, error-handling, security-baseline | knowledge-base-mcp (search_similar_requirements) |
| **A2** | knowledge-analysis, conflict-detection | rag-composer | 同上 | knowledge-base-mcp (全部), code-search-mcp |
| **A3** | ui-generation, prototype-format | annotation-parser | 同上 | knowledge-base-mcp |
| **A4** | spec-writing, api-schema, erd-design, state-machine | ddl-validator, schema-linter | 同上 | knowledge-base-mcp, spec-validator-mcp |
| **A5** | design-review, ux-heuristic, security-checklist | n1-detector | 同上 | knowledge-base-mcp, code-search-mcp, spec-validator-mcp |
| **A6** | dag-decomposition, dependency-rules | dependency-analyzer | 同上 | knowledge-base-mcp, code-search-mcp |
| **A7** | test-case-generation, gherkin-rules | test-template | 同上 | knowledge-base-mcp |
| **A8** | architecture-review, pattern-matching | tech-stack-validator | 同上 | knowledge-base-mcp, code-search-mcp, spec-validator-mcp |
| **A9** | dev-guidelines, tdd-rules, dual-brain | code-generator, test-runner | 同上 | knowledge-base-mcp, code-search-mcp, sandbox-runner-mcp |
| **A10** | ci-cd-pipeline, deploy-checklist | pipeline-templates | 同上 | sandbox-runner-mcp |
| **A11** | test-execution, mutation-testing | mutation-runner | 同上 | sandbox-runner-mcp |
| **A12** | code-review-checklist, security-rules | bandit-runner, semgrep-runner | 同上 | code-search-mcp, sandbox-runner-mcp |
| **A13** | release-checklist, rollback-rules | canary-analyzer | 同上 | knowledge-base-mcp |
| **K14** | knowledge-indexing, dedup-rules | pgvector-writer | 同上 | knowledge-base-mcp |
| **K15** | change-propagation, impact-rules | neo4j-updater | 同上 | knowledge-base-mcp, code-search-mcp |

---

## 七、worker_launcher.py 启动流程改造

```python
# repos/agent-workers/worker_launcher.py - 改造后
"""
Agent Worker 启动器。

启动顺序:
  1. 启动公共 MCP 服务连接（knowledge-base-mcp 等）
  2. 预热 SkillLoader 缓存
  3. 启动各 Agent Worker
"""

async def main():
    # Step 1: 启动 MCP 公共服务连接（所有 Agent 共享）
    logger.info("Starting shared MCP services...")
    await BaseAgentWorker.start_shared_services(server_names=[
        "knowledge-base-mcp",   # 所有 Agent 都需要
    ])
    logger.info("MCP services started")

    # Step 2: 预热 SkillLoader
    loader = BaseAgentWorker.get_skill_loader()
    for agent_id in ALL_AGENT_IDS:
        loader.load_all_for_agent(agent_id)
    logger.info("SkillLoader cache warmed")

    # Step 3: 启动各个 Agent Worker
    workers = [
        A1RequirementIntake(nats_url),
        A2KnowledgeAnalyst(nats_url),
        A3UIGenerator(nats_url),
        A4SpecWriter(nats_url),
        A5DesignReviewAgent(nats_url),
        # ...
    ]

    tasks = [w.subscribe_nats() for w in workers]
    await asyncio.gather(*tasks)

    # Cleanup
    await BaseAgentWorker.stop_shared_services()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 八、A1~A5 从 JAP Plus 吸收的具体内容

### A1 需求澄清增强

来自 JAP Plus `elicitationRoutes.ts` + `elicitationHelpers.ts`：

- **四维问题覆盖**：核心实体、状态边界、安全权限、外部依赖
- **双签名去重**：完整签名 + 短签名，跨轮次 + 同轮次
- **快速/深度双模式**：快速 90s/16条/批，深度 180s/24条/批，temperature=0.1, maxRetries=0
- **结构化输出 JSON 回退**：`structuredOutputFallback.ts` 的提取+解析+标记逻辑

### A5 设计评审增强

来自 JAP Plus `taskRoutes.ts` 审批控制流程：

- **跨产物一致性检查清单**：API-ERD 字段映射、状态机-用例覆盖、$ref 完整性、命名一致性
- **SDD 证据注入机制**：将 01-07 产物作为"证据块"注入评审提示词，防止模型编造
- **质量阈值**：UX >= 70, API >= 70, Business >= 70，三者全部通过才 overall_pass

### A2 知识分析增强

来自 JAP Plus `skillContext.ts` + `context-builder/`：

- **技能上下文注入**：读取 `.ai-native/rules.md`，格式化为 `[SkillRules]...[/SkillRules]` 块
- **四策略对照**：write(K14) / select(selector.py) / compress(compress.py) / isolate(isolate.py)

### A4 Spec 撰写增强

来自 JAP Plus 7 步文件生成流程：

- **产出物扩展**：API Schema + ERD -> 增加功能清单(Mermaid)、状态机(Mermaid)、验收测试大纲(Gherkin)
- **格式约束**：DDL 统一 `uk_`/`idx_` 命名、OpenAPI 3.0 YAML 含 `$ref`、Gherkin Given/When/Then

### 通用降级增强

来自 JAP Plus `taskRoutes.ts` 多级降级：

- **四级降级链**：MCP 工具 -> LLM 标准上下文 -> LLM 极简模式 -> 分段合并
- **JSON 回退解析**：提取 markdown code block -> 提取裸 JSON -> safe_parse -> 标记 used_fallback

---

## 九、达成路径：从现状到目标架构

> 当前实施 Spec: `doc/specs/orchestrator-completion-spec.md` — 记录了 Phase 0 的详细设计

### 9.1 演进路线图

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4
 (当前)      (并行)      (并行)                     (收尾)

Phase 0 + Phase 1 + Phase 2 可以三线并行——各自改不同的代码区域。
Phase 3 依赖 Phase 2 的 Agent 改造完成。
Phase 4 依赖 Phase 3 的 MCP 基础设施就绪。
```

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Phase 0 — Orchestrator 补全                                              │
│                                                                          │
│ 范围: 让 Orchestrator 稳定运行，信息流完整                                │
│                                                                          │
│  T1: Gate SLA 超时通知（不自动通过，人工审批）                            │
│  T2: notify_mc DB 同步（状态变更写入 requirements.status）               │
│  T3: Agent 超时升级通知（达阈值发升级事件）                               │
│  T4: build_context 富化（五层上下文：需求+产物+知识库+环境+返工）         │
│  T5: Agent 产物持久化（store_agent_result → spec.artifacts JSONB）       │
│                                                                          │
│  新增: ContextCompressionService（分层压缩）                              │
│  新增: .ai-native/ 目录骨架（project-config.yaml + context-budget.yaml）  │
│  改造: dispatch_agent context 截断 5000→64K 字符                         │
│  改造: Agent 侧暴力截断 → prepare_llm_context()                          │
│                                                                          │
│  交付物: 稳定的 Orchestrator + 五层上下文基础设施                         │
│  预估: ~2 周                                                             │
│  Spec: doc/specs/orchestrator-completion-spec.md                         │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ├───────────────────┬───────────────────┐
        ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ Phase 1         │ │ Phase 2         │ │ (同步进行)      │
│ Stub Agent 替换 │ │ Skills 系统     │ │                 │
│                 │ │                 │ │ Phase 1 和      │
│ A9: 真实 Claude │ │ SkillLoader     │ │ Phase 2 互不    │
│     CodeBridge  │ │ 解析 .skill.md  │ │ 冲突，可并行    │
│ A10: 真实 Docker│ │ TTL 缓存        │ │                 │
│     build+deploy│ │ 组合加载        │ │                 │
│ A11: 真实       │ │                 │ │                 │
│     VisAgent    │ │ 3 个 public     │ │                 │
│ A13: 真实       │ │ shared skills   │ │                 │
│     Prometheus  │ │ (quality-gates  │ │                 │
│ K14: LLM 增强   │ │  + error-handle │ │                 │
│     pgvector    │ │  + security-    │ │                 │
│ K15: Neo4j      │ │  baseline)      │ │                 │
│     依赖图      │ │                 │ │                 │
│                 │ │ A1/A4/A5/A9     │ │                 │
│ 交付物: 端到端  │ │ Agent skills    │ │                 │
│ 可跑通          │ │                 │ │                 │
│ 预估: ~3 周     │ │ 交付物: 统一    │ │                 │
│                 │ │ 行为规则约束    │ │                 │
│                 │ │ 预估: ~2 周     │ │                 │
└────────┬────────┘ └────────┬────────┘ │                 │
         │                   │           │                 │
         └───────────────────┴───────────┘                 │
                     │                                     │
                     ▼                                     │
┌─────────────────────────────────────────────────────────┐ │
│ Phase 3 — MCP 基础设施                                   │ │
│                                                          │ │
│ 1. Python MCPClient（多 Server stdio 连接 + 工具发现缓存）│ │
│ 2. knowledge-base-mcp Server（search_knowledge +         │ │
│    retrieve_by_id）                                      │ │
│ 3. spec-validator-mcp Server                             │ │
│ 4. ⚡ Agent function calling 改造（关键里程碑）           │ │
│ 5. 开启 lazy_load_enabled — Agent 通过 _refs 按需拉取    │ │
│ 6. build_context 知识库注入从 HTTP → MCP stdio           │ │
│ 7. code-search-mcp + sandbox-runner-mcp Server           │ │
│                                                          │ │
│ 交付物: Agent 主动调用工具，上下文从 push → pull          │ │
│ 预估: ~3 周                                              │ │
└──────────────────────────┬──────────────────────────────┘ │
                           │                                 │
                           ▼                                 │
┌─────────────────────────────────────────────────────────┐ │
│ Phase 4 — 全量覆盖 + 生产加固                             │ │
│                                                          │ │
│ 1. A6-A13, K14-K15 独立 Skills（15 个 Agent 全覆盖）     │ │
│ 2. Circuit Breaker Agent 侧接入                           │ │
│    — call_llm() 失败时 FEW_SHOT→STRONG_MODEL→HUMAN      │ │
│ 3. MCP 服务注册表自动发现（registry.yaml → 动态加载）     │ │
│ 4. 四级降级链接入                                         │ │
│    MCP 工具 → LLM 标准上下文 → LLM 极简模式 → 分段合并    │ │
│ 5. 全链路可观测性（Grafana Tempo/Loki/Mimir）            │ │
│ 6. Context Builder 四策略对照文档                         │ │
│                                                          │ │
│ 交付物: 全 Agent Skills/Tools/MCP 三层架构完成            │ │
│ 预估: ~4 周                                              │ │
└─────────────────────────────────────────────────────────┘
```

### 9.2 Phase 之间依赖关系

```
Phase 0 ──→ Phase 1 (依赖: 稳定的上下文基础设施)
        ──→ Phase 2 (依赖: prepare_llm_context() 入口点)
             ──→ Phase 3 (依赖: Agent 已改造，支持 function calling)
                  ──→ Phase 4 (依赖: MCP 基础设施就绪)
```

- **Phase 1 不依赖 Phase 2** — Stub 替换改 Agent 实现逻辑，Skills 系统加 Agent 行为规则，互不冲突
- **Phase 2 依赖 Phase 0** — 需要 `prepare_llm_context()` 作为 Skills 注入的统一入口
- **Phase 3 依赖 Phase 2** — Agent 需要先有 Skills 意识（知道什么时候该调用工具），再做 function calling
- **Phase 4 依赖 Phase 3** — 全量 Skills 和降级链依赖 MCP 协议和工具已经可用

### 9.3 当前 spec 为远景预留的接口点

| 接口点 | Phase 0 状态 | Phase 2+ 扩展 |
|--------|------------|-------------|
| `BaseAgentWorker.prepare_llm_context()` | 上下文压缩入口 | 叠加 `build_enhanced_prompt()` — Skills 注入 |
| `BaseAgentWorker.call_llm()` | 统一 LLM 调用 | 叠加 Agent function calling — MCP tools |
| `build_context` Activity | HTTP 调 context-builder | 改为 MCP stdio 调 knowledge-base-mcp，查询逻辑复用 |
| `store_agent_result` Activity | 直接写 JSONB | 叠加 Agent skill 定义的 output schema 校验 |
| `context-budget.yaml` | 百分比预算 | 换模型只改 `model_window` 一行 |
| `lazy_load_enabled: false` | 关闭 | Phase 3 开启 — Agent 按需拉取 artifact 详情 |
| `.ai-native/` 目录 | project-config.yaml + context-budget.yaml | 扩展出 agents/shared/mcp 子目录 |

### 9.4 各 Phase 关键新增文件

| Phase | 关键新增文件 |
|-------|------------|
| **0** | `context_compression.py`, `store_agent_result.py`, `project-config.yaml`, `context-budget.yaml` |
| **1** | 重写 A9/A10/A11/A13/K14/K15 (约 10 个 Agent 文件) |
| **2** | `skill_loader.py`, `quality-gates.skill.md`, `error-handling.skill.md`, `security-baseline.skill.md`, A1/A4/A5/A9 各 2-4 个 `.skill.md` |
| **3** | `mcp-client.tool.py`, `knowledge-base-mcp/{server.py,tools.py,config.yaml}`, `spec-validator-mcp/{server.py,config.yaml}`, `code-search-mcp/`, `sandbox-runner-mcp/` |
| **4** | 10+ 个 Agent `.skill.md`, `registry.yaml` 动态发现, 观测性配置 |

### 9.5 与 orchestrator-completion-spec.md 的分工

| 文档 | 职责 |
|------|------|
| **本文档 (jap-plus-absorption-plan.md)** | 远景架构蓝图，定义 What（目标是什么） |
| **orchestrator-completion-spec.md** | 当前实施 Spec，定义 How（Phase 0 怎么做） |

两文档互补而非替代。本文档回答"系统最终长什么样"，orchestrator-completion-spec 回答"第一步怎么走，同时不堵死后面的路"。

---

## 十、与现有架构的兼容性

| 现有能力 | 状态 | 变更 |
|---------|------|------|
| NATS JetStream | **保持** | Agent 间通信不变 |
| Temporal 工作流 | **保持** | Orchestrator 调度不变 |
| LLMProviderManager | **保持** | LLM 调用路由不变 |
| Context Builder | **封装** | 通过 knowledge-base-mcp 的 get_context_for_agent 暴露 |
| 现有知识库 (pgvector+Neo4j) | **封装** | 通过 knowledge-base-mcp 统一暴露 |
| MCP Gateway (Go) | **保留** | Go 网关管理外部工具注册，Python MCPClient 是 Agent 侧消费者 |
| BaseAgentWorker | **增强** | 新增方法（prepare_llm_context, build_enhanced_prompt, mcp_call），现有接口不动 |
| ContextCompressionService | **新增** | Phase 0 产出，Phase 3 解耦为独立 shared/tools |
| store_agent_result | **新增** | Phase 0 产出，Phase 2 叠加 output schema 校验 |
| `.ai-native/` 目录 | **渐进** | Phase 0 建骨架，Phase 2 加 agents/ 子目录，Phase 3 加 mcp/ 子目录 |

**关键原则**：三层架构是**渐进式增强**——每一层缺失时系统都能优雅降级：
- MCP 服务不可用 → Agent 使用原有直接 PostgreSQL 调用
- Skills 目录不存在 → 退回到硬编码 prompt
- 公共 Skills 未配置 → 仅使用 Agent 独立 Skills
- ContextCompressionService 不可用 → 退回到截断模式
- 知识库不可用 → 回退直接查 knowledge_chunks 表
