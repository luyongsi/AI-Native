"""
A1 BDD — BDDDrafter: Generates Given-When-Then acceptance criteria from a requirement draft.

LLM-driven with template fallback when API key is unavailable.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://uniapi.ruijie.com.cn")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606")

BDD_PROMPT = """你是一个 BDD 测试专家。请基于以下需求草案，生成 Given-When-Then 格式的验收标准场景。

要求：
1. 每个场景必须包含 given / when / then 三个部分
2. 覆盖主要正常流程和关键异常流程
3. 至少生成 3 条场景，目标 5 条以上
4. 中文输出

需求草案:
__DRAFT__

请只输出 JSON，不要 markdown 代码块包裹，不要任何解释文字:
{"scenarios": [{"given": "前置条件", "when": "操作", "then": "预期结果"}], "coverage_score": 0.8}"""

# ---------- fallback templates ----------
GWT_TEMPLATES: dict[str, list[dict]] = {
    "order_management": [
        {"given": "用户已登录且具有下单权限", "when": "用户填写订单信息并点击提交", "then": "系统生成订单并返回订单号，状态为待支付"},
        {"given": "存在一个待支付的订单", "when": "用户在30分钟内完成支付", "then": "订单状态变更为已支付，库存扣减成功"},
        {"given": "存在一个支付超时的订单", "when": "系统定时任务检测到超时", "then": "订单状态变更为已取消，预占库存释放"},
    ],
    "auth": [
        {"given": "用户未登录", "when": "用户访问受保护页面", "then": "系统重定向到登录页并提示'请先登录'"},
    ],
    "payment": [
        {"given": "用户选择微信支付", "when": "支付网关返回成功回调", "then": "系统更新订单状态，发送支付成功通知"},
    ],
    "inventory": [
        {"given": "商品库存充足", "when": "用户提交订单", "then": "系统预占库存并返回预计发货时间"},
    ],
    "reporting": [
        {"given": "用户选择导出范围为最近一个月", "when": "用户点击导出Excel按钮", "then": "系统生成异步导出任务并返回任务ID"},
    ],
    "general": [
        {"given": "用户处于正常操作流程中", "when": "用户执行核心业务操作", "then": "操作成功，界面给出明确反馈"},
        {"given": "用户输入了不符合规则的数据", "when": "用户提交表单", "then": "系统在校验失败字段旁显示错误提示，不提交请求"},
    ],
}


class BDDDrafter:
    """Generates GWT acceptance criteria from a requirement draft."""

    def __init__(self):
        self.model = DEEPSEEK_MODEL
        self.base_url = DEEPSEEK_BASE_URL
        self.api_key = DEEPSEEK_API_KEY

    async def draft_gwt(self, draft: dict) -> dict:
        """Generate GWT scenarios.

        Returns:
            {"scenarios": [{"given": "...", "when": "...", "then": "..."}], "coverage_score": 0.85}
        """
        if not self.api_key:
            return self._fallback_gwt(draft)

        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        prompt = BDD_PROMPT.replace("__DRAFT__", draft_text)

        try:
            import httpx
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "system", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_response(content, draft)
        except Exception:
            logger.exception("BDDDrafter LLM call failed")
            return self._fallback_gwt(draft)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(content: str, _draft: dict) -> dict:
        try:
            result = json.loads(content.strip())
            if isinstance(result, dict) and "scenarios" in result:
                return result
        except json.JSONDecodeError:
            pass
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, dict) and "scenarios" in result:
                    return result
            except json.JSONDecodeError:
                pass
        return {"scenarios": [], "coverage_score": 0}

    @staticmethod
    def _fallback_gwt(draft: dict) -> dict:
        domain = draft.get("domain", "general")
        scenarios = list(GWT_TEMPLATES.get(domain, GWT_TEMPLATES["general"]))
        coverage = round(min(len(scenarios) * 0.12, 1.0), 2)
        return {"scenarios": scenarios, "coverage_score": coverage}
