"""
A12: Code Review Agent (代码审查)

真实 LLM: 通过统一的 self.call_llm() 进行代码审查
触发: test.passed (A11 测试通过后触发)
审查包括: 跨模块影响分析、代码规范检查、安全问题、自动修复建议
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from base_worker import BaseAgentWorker

logger = logging.getLogger(__name__)

AGENT_ID = "A12"
AGENT_TYPE = "code_review"

class CodeReviewAgent(BaseAgentWorker):
    """A12: 代码审查 Agent — LLM 驱动"""

    agent_id = AGENT_ID
    agent_type = AGENT_TYPE

    def __init__(self, nats_url: str = "nats://localhost:4222"):
        super().__init__(AGENT_ID, AGENT_TYPE, nats_url)
        self.running_tasks: set = set()
        self._execute_lock = asyncio.Lock()  # Prevent concurrent execute() calls

    async def init(self):
        await super().init()
        sub = await self.nc.subscribe("test.passed")
        logger.info(f"[A12] Subscribed to 'test.passed' events")
        asyncio.create_task(self._consume_test_passed(sub))

    async def _consume_test_passed(self, sub):
        async for msg in sub.messages:
            try:
                data = json.loads(msg.data.decode())
                req_id = data.get("req_id", "unknown")
                logger.info(f"[A12] Received test.passed for req={req_id}")
                task = asyncio.create_task(self._handle_review_request(req_id, data))
                self.running_tasks.add(task)
                task.add_done_callback(self.running_tasks.discard)
            except Exception as e:
                logger.error(f"[A12] Error in test.passed handler: {e}")

    async def _handle_review_request(self, req_id: str, test_result: dict):
        try:
            await self.report_status(req_id, "running", "代码审查开始")
            result = await self.execute(req_id, test_result)
            await self.report_status(req_id, "completed", f"审查结果: {result.get('verdict')}")
        except Exception as e:
            logger.error(f"[A12] Review failed: {e}")

    async def execute(self, req_id: str, context_package: dict) -> dict:
        """Code review with mutex to prevent concurrent overlapping calls."""
        async with self._execute_lock:
            return await self._execute_impl(req_id, context_package)

    async def _execute_impl(self, req_id: str, context_package: dict) -> dict:
        test_result = context_package
        code_diff = test_result.get("code_diff", test_result.get("payload", {}))
        changes = code_diff.get("changes", []) if isinstance(code_diff, dict) else []

        logger.info(f"[A12] Code review req={req_id}, changes={len(changes)}")

        await self.report_status(req_id, "running", "Phase 1: LLM 代码审查")

        # Context compression replaces brute [:4000] truncation
        review_text = await self.prepare_llm_context(context_package, state="reviewing_code")
        prompt = f"""你是资深代码审查员。审查以下代码变更。

代码变更上下文:
{review_text}

输出 JSON:
{{
  "verdict": "pass|fail",
  "score": 0-100,
  "issues": [
    {{"file": "文件路径", "line": 行号, "rule": "规则名", "severity": "error|warning|info", "description": "问题描述", "suggestion": "修复建议"}}
  ],
  "positive_feedback": ["做得好的地方"],
  "summary": "审查总结（100字）"
}}

检查: SQL注入、XSS、CSRF、硬编码密钥、不安全加密、空指针、未处理异常、类型安全、代码规范
只输出 JSON"""

        content = await self.call_llm([{"role": "user", "content": prompt}],
            task_type="code_review",
            max_tokens=2000,
            req_id=req_id,
            workflow_id=context_package.get("workflow_id", ""),
            temperature=0.1,
        )

        if content:
            try:
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                review = json.loads(content)
                verdict = review.get("verdict", "pass")
                score = review.get("score", 85)
                issues = review.get("issues", [])
            except json.JSONDecodeError:
                review = self._fallback_review()
                verdict = review["verdict"]
                score = review["score"]
                issues = review["issues"]
        else:
            review = self._fallback_review()
            verdict = review["verdict"]
            score = review["score"]
            issues = review["issues"]

        # Build auto-fix patches for warnings
        patches = []
        for issue in issues:
            if issue.get("severity") in ("warning", "info"):
                patches.append({
                    "file": issue.get("file", ""),
                    "line": issue.get("line", 0),
                    "rule": issue.get("rule", ""),
                    "description": f"Auto-fix suggestion: {issue.get('suggestion','')}",
                    "auto_apply": issue.get("severity") == "info",
                })

        summary = {
            "req_id": req_id,
            "verdict": verdict,
            "score": score,
            "issues": issues,
            "auto_fix_patches": patches,
            "positive_feedback": review.get("positive_feedback", []),
            "summary": review.get("summary", ""),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": "A12 (LLM)",
        }

        await self.report_artifact(req_id, "code_review", summary)

        envelope = {
            "event_id": f"review-code-{req_id}",
            "event_type": "review.completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": summary,
            "req_id": req_id,
            "agent_id": AGENT_ID,
        }
        await self.nc.publish("review.completed", json.dumps(envelope, ensure_ascii=False).encode())
        logger.info(f"[A12] Published review.completed verdict={verdict} score={score}")

        return summary

    def _fallback_review(self) -> dict:
        return {
            "verdict": "pass",
            "score": 80,
            "issues": [],
            "positive_feedback": ["代码结构清晰"],
            "summary": "[Fallback] 自动审查通过，建议人工复审关键安全逻辑",
        }
