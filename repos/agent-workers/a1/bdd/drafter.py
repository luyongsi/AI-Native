"""
bdd/drafter.py — BDD GWT Scenario Drafter

Generates Given-When-Then acceptance scenarios from a requirement draft.
Real implementation would use an LLM with few-shot prompts, potentially
leveraging existing spec files as in-context examples for consistency.

Contract:
    class BDDDrafter
        async draft_gwt(requirement: dict) -> dict
        -> {scenarios: [{"given", "when", "then"}], coverage_score: float}
"""

import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# ---------- scenario templates per domain ----------

GWT_TEMPLATES: dict[str, list[dict]] = {
    "order_management": [
        {
            "given": "用户已登录且具有下单权限",
            "when": "用户填写订单信息并点击提交",
            "then": "系统生成订单并返回订单号，状态为待支付",
        },
        {
            "given": "存在一个待支付的订单",
            "when": "用户在30分钟内完成支付",
            "then": "订单状态变更为已支付，库存扣减成功",
        },
        {
            "given": "存在一个支付超时的订单",
            "when": "系统定时任务检测到超时",
            "then": "订单状态变更为已取消，预占库存释放",
        },
    ],
    "auth": [
        {
            "given": "用户未登录",
            "when": "用户访问受保护页面",
            "then": "系统重定向到登录页并提示'请先登录'",
        },
    ],
    "payment": [
        {
            "given": "用户选择微信支付",
            "when": "支付网关返回成功回调",
            "then": "系统更新订单状态，发送支付成功通知",
        },
    ],
    "inventory": [
        {
            "given": "商品库存充足",
            "when": "用户提交订单",
            "then": "系统预占库存并返回预计发货时间",
        },
    ],
    "reporting": [
        {
            "given": "用户选择导出范围为最近一个月",
            "when": "用户点击导出Excel按钮",
            "then": "系统生成异步导出任务并返回任务ID",
        },
    ],
    "general": [
        {
            "given": "用户处于正常操作流程中",
            "when": "用户执行核心业务操作",
            "then": "操作成功，界面给出明确反馈",
        },
        {
            "given": "用户输入了不符合规则的数据",
            "when": "用户提交表单",
            "then": "系统在校验失败字段旁显示错误提示，不提交请求",
        },
    ],
}


class BDDDrafter:
    """Draft GWT (Given-When-Then) BDD scenarios from a requirement document.

    The stub selects scenario templates by domain keyword. A real implementation
    would:
      1. Embed the requirement text with a sentence-transformer model.
      2. Retrieve the most similar historical scenarios from a vector store.
      3. Call Claude to generate 5–15 new scenarios covering happy path,
         edge cases, error paths, and authorization boundaries.
    """

    async def draft_gwt(self, requirement: dict) -> dict:
        """Generate BDD scenarios.

        Args:
            requirement: dict with ``title``, ``domain``, and optionally ``entities``.

        Returns:
            {scenarios: [...], coverage_score: float, generated_at: str}
        """
        domain = requirement.get("domain", "general")
        title = requirement.get("title", "")

        logger.info("Drafting GWT scenarios for domain=%s, title='%s'", domain, title[:60])

        scenarios = list(GWT_TEMPLATES.get(domain, [])) or list(GWT_TEMPLATES["general"])

        # Append title-specific scenarios for extra coverage
        customized = self._custom_scenarios(title)
        scenarios.extend(customized)

        coverage_score = round(min(len(scenarios) * 0.12, 1.0), 2)

        return {
            "scenarios": scenarios,
            "coverage_score": coverage_score,
            "generated_at": __import__("datetime", fromlist=["datetime"]).datetime.now(
                __import__("datetime", fromlist=["timezone"]).timezone.utc,
            ).isoformat(),
        }

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    def _custom_scenarios(self, title: str) -> list[dict]:
        """Keyword-driven extra scenarios."""
        extras: list[dict] = []
        if any(kw in title for kw in ("权限", "角色", "审批")):
            extras.append({
                "given": "当前用户角色为普通用户",
                "when": "用户尝试执行管理员专属操作",
                "then": "系统返回403 Forbidden并记录审计日志",
            })
        if any(kw in title for kw in ("导出", "下载")):
            extras.append({
                "given": "系统负载较高且导出任务队列已满",
                "when": "用户发起大数据量导出请求",
                "then": "系统提示'导出任务排队中，预计等待X分钟'",
            })
        return extras
