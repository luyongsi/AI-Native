"""
A12: Cross-Module Impact Analyzer (跨模块影响分析)

独立模块，供 A12 Code Review Agent 调用。
开发阶段 mock：用文件路径做简单的模式匹配。
"""

import logging

logger = logging.getLogger(__name__)

# 影响规则：文件路径模式 -> 影响描述
IMPACT_RULES = {
    "src/api/": {
        "impact": "可能影响前端页面和后端 API 调用方",
        "severity": "medium",
        "affected_modules": ["frontend", "api-gateway", "external-integrations"],
    },
    "src/routes/": {
        "impact": "可能影响 API 路由和前端页面",
        "severity": "medium",
        "affected_modules": ["frontend", "api-gateway"],
    },
    "src/components/": {
        "impact": "可能影响其他页面和组件复用方",
        "severity": "low",
        "affected_modules": ["frontend", "shared-ui"],
    },
    "src/models/": {
        "impact": "可能影响数据库 Schema 和数据访问层",
        "severity": "high",
        "affected_modules": ["database", "orm-layer", "data-migration"],
    },
    "src/services/": {
        "impact": "可能影响业务逻辑层和其他服务调用方",
        "severity": "medium",
        "affected_modules": ["business-logic", "other-services", "event-bus"],
    },
    "src/utils/": {
        "impact": "可能影响所有引用该工具函数的模块",
        "severity": "low",
        "affected_modules": ["all-modules"],
    },
    "src/middleware/": {
        "impact": "可能影响全局请求/响应处理流程",
        "severity": "high",
        "affected_modules": ["request-pipeline", "auth", "logging"],
    },
    "package.json": {
        "impact": "依赖变更，建议全量测试",
        "severity": "high",
        "affected_modules": ["all-modules"],
    },
    "requirements.txt": {
        "impact": "Python 依赖变更，建议全量测试",
        "severity": "high",
        "affected_modules": ["all-modules"],
    },
    "src/config/": {
        "impact": "可能影响所有依赖配置的模块",
        "severity": "medium",
        "affected_modules": ["config-service", "all-modules"],
    },
    "src/db.py": {
        "impact": "数据库核心文件变更，可能影响所有数据操作",
        "severity": "high",
        "affected_modules": ["database", "all-models"],
    },
    "src/main.py": {
        "impact": "应用入口变更，可能影响启动流程和全局配置",
        "severity": "high",
        "affected_modules": ["application-entry", "middleware-chain"],
    },
    "tests/": {
        "impact": "测试文件变更，不影响生产代码",
        "severity": "info",
        "affected_modules": ["test-suite"],
    },
}


class CrossModuleImpactAnalyzer:
    """跨模块影响分析器

    用法:
        analyzer = CrossModuleImpactAnalyzer()
        report = analyzer.analyze(diff_changes, dependency_graph)
    """

    def __init__(self):
        self.rules = IMPACT_RULES

    def analyze(self, diff: list, dependency_graph: dict = None) -> dict:
        """分析代码变更的跨模块影响

        Args:
            diff: 变更文件列表，每项包含 'path' 字段
            dependency_graph: 可选的依赖图（开发阶段不使用真实图）

        Returns:
            影响报告 dict，包含 overall_severity, affected_modules, impacts[]
        """
        if not diff:
            logger.info("[A12 ImpactAnalyzer] No diff to analyze")
            return {
                "overall_severity": "none",
                "affected_modules": [],
                "impacts": [],
                "recommendation": "无变更，无需额外测试",
            }

        changes = diff if isinstance(diff, list) else diff.get("changes", [])
        if not changes:
            return {
                "overall_severity": "none",
                "affected_modules": [],
                "impacts": [],
                "recommendation": "无有效变更记录",
            }

        impacts = []
        all_affected_modules = set()
        severity_scores = {"info": 0, "low": 1, "medium": 2, "high": 3}

        for change in changes:
            file_path = change.get("path", change) if isinstance(change, dict) else str(change)
            matched = self._match_rules(file_path)

            if matched:
                for rule in matched:
                    impacts.append({
                        "file": file_path,
                        "impact": rule["impact"],
                        "severity": rule["severity"],
                        "affected_modules": rule["affected_modules"],
                    })
                    all_affected_modules.update(rule["affected_modules"])

        # 确定整体严重性
        max_severity_score = 0
        for impact in impacts:
            score = severity_scores.get(impact["severity"], 0)
            if score > max_severity_score:
                max_severity_score = score

        severity_map_reverse = {0: "none", 1: "low", 2: "medium", 3: "high"}
        overall_severity = severity_map_reverse.get(max_severity_score, "none")

        # 生成建议
        recommendation = self._generate_recommendation(overall_severity, all_affected_modules)

        report = {
            "overall_severity": overall_severity,
            "affected_modules": sorted(list(all_affected_modules)),
            "impacts": impacts,
            "total_files_analyzed": len(changes),
            "files_with_impact": len(impacts),
            "recommendation": recommendation,
        }

        logger.info(
            f"[A12 ImpactAnalyzer] Analysis complete: severity={overall_severity}, " +
            f"affected_modules={len(all_affected_modules)}, impacts={len(impacts)}"
        )
        return report

    def _match_rules(self, file_path: str) -> list:
        """将文件路径与规则匹配"""
        matched = []
        for prefix, rule in self.rules.items():
            if file_path.startswith(prefix):
                matched.append(rule)
        return matched

    def _generate_recommendation(self, severity: str, modules: set) -> str:
        """根据严重性和受影响模块生成测试建议"""
        if severity == "high":
            return (
                f"高风险变更，建议执行全量回归测试。受影响模块: {', '.join(sorted(modules))}。"
            )
        elif severity == "medium":
            return (
                f"中等风险变更，建议对受影响模块执行集成测试。" +
                f"受影响模块: {', '.join(sorted(modules))}。"
            )
        elif severity == "low":
            return (
                f"低风险变更，建议对受影响模块执行 smoke 测试。" +
                f"受影响模块: {', '.join(sorted(modules))}。"
            )
        else:
            return "无明显风险变更，常规测试即可。"


# 便捷函数
def analyze_diff_impact(diff: list, dependency_graph: dict = None) -> dict:
    """对 diff 进行快速影响分析的便捷函数"""
    analyzer = CrossModuleImpactAnalyzer()
    return analyzer.analyze(diff, dependency_graph)
