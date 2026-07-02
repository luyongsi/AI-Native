"""
feasibility.py — Technical Feasibility Assessor

Evaluates whether a requirement is technically feasible given the current
architecture, team capacity, and known constraints. The stub uses keyword
heuristics; a real implementation would query infrastructure dashboards,
capacity plans, and call an LLM with a structured rubric.

Contract:
    class FeasibilityAssessor
        async assess(requirement: dict) -> dict
        -> {feasible: bool, risk_level: "low"|"medium"|"high",
            concerns: list[str], confidence: float}
"""

import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Known hard constraints (would be fetched from a config service in prod)
HARD_BLOCKERS = {
    "real_time_video": "实时视频处理需要GPU集群，当前基础设施暂不支持",
    "blockchain": "区块链功能超出当前架构范围，需专项评估",
    "air_gapped": "物理隔离环境部署需要运维侧配合，请提前申请资源",
}

HIGH_RISK_PATTERNS = {
    "real_time_analytics": ("high", "实时分析需要Flink/Kafka Streams，评估链路延迟SLA"),
    "legacy_migration": ("high", "遗留系统迁移数据一致性风险较高，建议分阶段切换"),
    "multi_tenant": ("high", "多租户架构需评审数据隔离方案"),
    "zero_downtime": ("medium", "零停机部署需要蓝绿/金丝雀策略，评估CD流水线成熟度"),
    "pci_dss": ("high", "PCI DSS合规需安全团队专项评审"),
    "gdpr": ("medium", "GDPR相关功能需法务审核数据处理条款"),
    "100k": ("medium", "高并发场景(>10万QPS)需压测验证"),
    "huge_data": ("medium", "大数据量处理需评估存储和计算资源"),
    "export": ("low", "异步导出功能相对成熟，复用现有报表服务即可"),
    "crud": ("low", "标准CRUD功能技术风险低，使用现有代码生成模板"),
    "notification": ("low", "通知功能可直接复用消息通知模板引擎"),
    "approval": ("low", "审批类功能可复用现有工作流引擎"),
}


class FeasibilityAssessor:
    """Assess technical feasibility of a new requirement.

    In production this would also:
      - Consult the team's capacity plan (Jira / Linear workload).
      - Check dependent service SLAs and availability.
      - Run an architecture fit score against the current tech radar.
    """

    async def assess(self, requirement: dict) -> dict:
        """Evaluate the feasibility of *requirement*.

        Args:
            requirement: dict with ``title``, ``domain``, ``entities`` and
                         optional ``constraints``.

        Returns:
            {feasible: bool, risk_level: "low"|"medium"|"high",
             concerns: [...], confidence: float}
        """
        title = requirement.get("title", "")
        domain = requirement.get("domain", "general")
        constraints = requirement.get("constraints", [])

        logger.info("Feasibility assessment for '%s' (domain=%s)", title[:60], domain)

        concerns: list[str] = []
        risk_level = "low"

        # Check hard blockers first
        feasible = True
        for blocker_key, reason in HARD_BLOCKERS.items():
            if blocker_key in title.lower() or blocker_key in str(constraints).lower():
                concerns.append(reason)
                feasible = False

        # Risk pattern heuristics
        for keyword, (risk, explanation) in HIGH_RISK_PATTERNS.items():
            if keyword in title.lower() or keyword in str(constraints).lower():
                concerns.append(explanation)
                risk_level = risk if risk == "high" or (
                    risk == "medium" and risk_level == "low"
                ) else risk_level

        # Domain-specific boilerplate
        if domain == "general" and not concerns:
            concerns.append("领域信息不足，建议补充业务背景后重新评估")
            risk_level = "medium"

        confidence = {
            "low": 0.85,
            "medium": 0.60,
            "high": 0.35,
        }.get(risk_level, 0.70)

        if not feasible:
            confidence = 0.20

        return {
            "feasible": feasible,
            "risk_level": risk_level,
            "concerns": concerns,
            "confidence": round(confidence, 2),
        }
