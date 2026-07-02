"""
A9: Dev Agent Stub (开发 Agent)

接收 spec_package (OpenAPI + ERD) → 通过 ClaudeCodeBridge 生成代码 → 返回 diff。

开发阶段：ClaudeCodeBridge 工作在 mock 模式，模拟代码变更。
生产阶段：ClaudeCodeBridge 调用真实 Claude Code CLI。

控制流：
  spec_package → A9 分析变更范围 → ClaudeCodeBridge.execute_task() → code_diff → artifact.produced
"""

import logging
import hashlib
import random
from datetime import datetime, timezone
from uuid import uuid4

from base_worker import BaseAgentWorker
from a9_claude_code_bridge import ClaudeCodeBridge

logger = logging.getLogger(__name__)


class DevAgent(BaseAgentWorker):
    """A9 Dev Agent — 所有代码生成都走 ClaudeCodeBridge"""

    agent_id = "A9"
    agent_type = "dev_agent"

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(self.agent_id, self.agent_type, nats_url)
        self.cc = ClaudeCodeBridge()

    async def execute(self, req_id: str, context_package: dict) -> dict:
        spec_package = context_package.get("spec_package", {})
        openapi = spec_package.get("openapi", {})
        erd = spec_package.get("erd", {})

        domain = openapi.get("info", {}).get("title", "general")
        paths = openapi.get("paths", {})
        tables = erd.get("tables", [])

        logger.info(f"[A9] DevAgent processing spec for domain={domain}, req={req_id}")
        logger.info(f"[A9]   API paths: {len(paths)}, DB tables: {len(tables)}")

        # Phase 1: 分析 Spec，确定变更范围
        await self.report_status(req_id, "running", "Phase 1: 分析 Spec 变更范围")
        plan = self._build_dev_plan(domain, paths, tables)

        # Phase 2: 通过 ClaudeCodeBridge 执行代码变更任务
        #     开发阶段 (mock=True): 模拟代码生成
        #     生产阶段 (mock=False): 调用真实 Claude Code CLI
        await self.report_status(req_id, "running", "Phase 2: ClaudeCodeBridge 执行代码变更")
        task_spec = {
            "type": "backend",
            "title": f"生成 {domain} 模块代码",
            "plan": plan,
            "openapi_paths": len(paths),
            "erd_tables": len(tables),
        }
        result = await self.cc.execute_task(task_spec)

        # Phase 3: 构建 diff 结构
        await self.report_status(req_id, "running", "Phase 3: 构建 diff")
        diff = self._build_diff_from_bridge_result(result, plan, domain)

        # Phase 4: 产出 diff artifact
        await self.report_status(req_id, "running", "Phase 4: 产出 diff artifact")
        await self.report_artifact(req_id, "code_diff", diff)

        # Phase 5 (可选): 运行 Code Review
        is_mock = result.get("mock", True)
        review = None
        if not is_mock:
            review = await self.cc.run_code_review(str(diff))

        return {
            "status": "completed",
            "files_created": diff.get("files_created", 0),
            "files_modified": diff.get("files_modified", 0),
            "commit_sha": diff["commit_sha"] if "commit_sha" in diff else f"mock-{uuid4().hex[:8]}",
            "dev_plan": plan,
            "diff": diff,
            "claude_code_session": result.get("session_id"),
            "claude_code_cost_usd": result.get("total_cost_usd"),
            "claude_code_mock": is_mock,
            "code_review": review,
        }

    def _build_dev_plan(self, domain: str, paths: dict, tables: list) -> dict:
        """基于 Spec 制定开发计划（与 stub 版本兼容）"""
        plan_files = []
        for ep in list(paths.keys())[:3]:
            resource = ep.split("/")[1] if "/" in ep else "items"
            plan_files.append(f"src/routes/{resource}.py")
            plan_files.append(f"src/models/{resource}.py")
            plan_files.append(f"tests/test_{resource}.py")
        # 追加数据库模型（基于 ERD）
        for t in tables[:3]:
            table_name = t.get("name", "items")
            plan_files.append(f"src/models/{table_name}.py")
        return {
            "domain": domain,
            "files_to_create": list(dict.fromkeys(plan_files[:6])),
            "files_to_modify": ["src/main.py", "src/db.py"],
            "estimated_lines": random.randint(80, 300),
        }

    def _build_diff_from_bridge_result(self, bridge_result: dict, plan: dict, domain: str) -> dict:
        """将 ClaudeCodeBridge 的结果转换为标准 diff 结构"""
        files_changed = bridge_result.get("files_changed", [])
        changes = []

        for fc in files_changed:
            content_hash = hashlib.md5(
                fc.get("diff", "").encode()
            ).hexdigest()[:16]
            changes.append({
                "path": fc["path"],
                "change_type": "modified" if fc.get("removed", 0) > 0 else "created",
                "lines_added": fc.get("added", 0),
                "lines_removed": fc.get("removed", 0),
                "patch_preview": fc.get("diff", ""),
                "content_hash": content_hash,
            })

        if not changes:
            # Fallback: 如果没有从 bridge 拿到变更，基于 plan 生成兜底
            for f in plan.get("files_to_create", [])[:3]:
                content_hash = hashlib.md5(f"stub-{f}".encode()).hexdigest()[:16]
                changes.append({
                    "path": f,
                    "change_type": "created",
                    "lines_added": random.randint(10, 80),
                    "lines_removed": 0,
                    "patch_preview": f"# {domain.upper()} - AUTO STUB\n# File: {f}",
                    "content_hash": content_hash,
                })

        return {
            "files_created": sum(1 for c in changes if c["change_type"] == "created"),
            "files_modified": sum(1 for c in changes if c["change_type"] == "modified"),
            "changes": changes,
            "commit_sha": "a9" + hashlib.md5(str(changes).encode()).hexdigest()[:12],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_id": bridge_result.get("session_id"),
            "cost_usd": bridge_result.get("total_cost_usd"),
            "mock": bridge_result.get("mock", True),
            "bridge": "claude_code",  # 标识变更来源
        }
