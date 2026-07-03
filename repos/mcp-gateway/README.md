# mcp-gateway — MCP 协议 Gateway

基于 MCP (Model Context Protocol) 的统一工具接入层，聚合所有 Skill API，提供 JWT 认证、限流、审计。

## 架构

```
Worker (Claude Code / Python Agent)
    │ MCP Client
    ▼
MCP Gateway (:8081)
    ├── GET  /tools/list   → 返回该 Agent 可用的工具列表
    ├── POST /tools/call   → 路由到后端 Skill API
    ├── POST /auth/token   → JWT 签发 (RS256)
    ├── JWT 认证中间件 (Agent-scoped token)
    ├── 限流中间件 (100 req/min/agent)
    └── 审计中间件 (每请求记录 agent_id/req_id/duration)
```

## 快速开始

```bash
cd mcp-gateway
export HTTP_PROXY=http://10.40.5.3:17891
go build -o mcp-gateway .
./mcp-gateway
# 服务监听 :8081
```

```bash
# 获取 JWT Token
curl -X POST http://localhost:8081/auth/token \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"A9","req_id":"REQ-001"}'

# 获取工具列表
curl http://localhost:8081/tools/list \
  -H "Authorization: Bearer <token>"
```

## 依赖

- Go 1.23+
- golang-jwt v5

## 关联 Spec

spec-14 · MCP Gateway
