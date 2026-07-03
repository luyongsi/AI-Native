"""
A12: Cross-Module Impact Analyzer with K15 Neo4j Integration

Combines pattern-based analysis (Phase 2) with graph-based analysis (Phase 3)
to provide comprehensive impact assessment of code changes.

Flow:
  1. Phase 2: Apply file path rules for quick pattern-based impact
  2. Phase 3: Query Neo4j (K15) for graph-based dependency analysis
  3. Merge results and calculate combined risk level
  4. Generate testing recommendations based on impact scope

Triggered by:
  - A9 code changes
  - Explicit impact analysis requests
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add agent-workers to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from k15.change_propagation import ChangePropagation
from a12.security_scanner import SecurityScanner
from a12.cwe_mapper import CWEMapper

logger = logging.getLogger(__name__)

# Neo4j configuration
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://172.27.78.109:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "ai-native-2026")

# Phase 2 impact rules: file path patterns -> impact metadata
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
    """Cross-module impact analyzer with Neo4j (K15) integration.

    Phase 2 (Pattern-based): Uses hardcoded file path rules
    Phase 3 (Graph-based):   Queries Neo4j for dependency analysis
    """

    def __init__(self, use_neo4j: bool = True, enable_security_scan: bool = True):
        """Initialize the impact analyzer.

        Args:
            use_neo4j: Enable Neo4j K15 integration (default True)
            enable_security_scan: Enable security scanning (default True)
        """
        self.rules = IMPACT_RULES
        self.use_neo4j = use_neo4j
        self.propagation = None
        self.enable_security_scan = enable_security_scan
        self.security_scanner = None
        self.cwe_mapper = CWEMapper()

        if use_neo4j:
            try:
                self.propagation = ChangePropagation(
                    uri=NEO4J_URI,
                    user=NEO4J_USER,
                    password=NEO4J_PASSWORD
                )
                logger.info("[A12] K15 ChangePropagation initialized")
            except Exception as e:
                logger.warning(f"[A12] Failed to initialize K15: {str(e)}")
                self.propagation = None

        if enable_security_scan:
            try:
                self.security_scanner = SecurityScanner(timeout=60)
                logger.info("[A12] Security scanner initialized")
            except Exception as e:
                logger.warning(f"[A12] Failed to initialize security scanner: {str(e)}")
                self.security_scanner = None

    async def analyze(
        self,
        diff: List[str],
        dependency_graph: Optional[Dict] = None,
        req_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyze code changes for cross-module impact and security issues.

        Args:
            diff: List of changed file paths
            dependency_graph: Optional pre-built dependency graph
            req_id: Optional requirement ID for context

        Returns:
            Impact report dict with:
                - overall_severity: none | low | medium | high | critical
                - affected_modules: List of affected module names
                - impacts: List of impact dicts per file
                - graph_impacts: Neo4j-based impacts (if available)
                - combined_risk_level: Merged risk assessment
                - security_findings: Security scan results (if enabled)
                - security_risk_score: Overall security risk score (0-10)
                - recommendation: Testing recommendation
        """
        logger.info(f"[A12] Analyzing impact for {len(diff)} changed files")

        # Phase 2: Pattern-based impact analysis
        phase2_result = self._analyze_patterns(diff)

        # Phase 3: Neo4j graph-based analysis
        phase3_result = None
        if self.propagation:
            try:
                phase3_result = await self._analyze_with_neo4j(diff, phase2_result)
            except Exception as e:
                logger.warning(f"[A12] Neo4j analysis failed: {str(e)}")

        # Phase 4: Security scanning
        security_result = None
        if self.enable_security_scan and self.security_scanner:
            try:
                security_result = await self._security_analysis(diff)
            except Exception as e:
                logger.warning(f"[A12] Security analysis failed: {str(e)}")

        # Merge results
        combined_result = self._merge_results(phase2_result, phase3_result, security_result)

        logger.info(
            f"[A12] Analysis complete: severity={combined_result['overall_severity']}, "
            f"affected_modules={len(combined_result['affected_modules'])}"
        )

        return combined_result

    # ========================================================================
    # Phase 2: Pattern-Based Analysis
    # ========================================================================

    def _analyze_patterns(self, diff: List[str]) -> Dict[str, Any]:
        """Analyze changes using hardcoded file path patterns.

        Args:
            diff: List of changed file paths

        Returns:
            Pattern analysis result dict
        """
        if not diff:
            logger.info("[A12] No diff to analyze")
            return {
                "overall_severity": "none",
                "affected_modules": [],
                "impacts": [],
                "recommendation": "无变更，无需额外测试",
                "analysis_source": "pattern",
            }

        changes = diff if isinstance(diff, list) else diff.get("changes", [])
        if not changes:
            return {
                "overall_severity": "none",
                "affected_modules": [],
                "impacts": [],
                "recommendation": "无有效变更记录",
                "analysis_source": "pattern",
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

        # Determine overall severity
        max_severity_score = 0
        for impact in impacts:
            score = severity_scores.get(impact["severity"], 0)
            if score > max_severity_score:
                max_severity_score = score

        severity_map_reverse = {0: "none", 1: "low", 2: "medium", 3: "high"}
        overall_severity = severity_map_reverse.get(max_severity_score, "none")

        recommendation = self._generate_recommendation(overall_severity, all_affected_modules)

        return {
            "overall_severity": overall_severity,
            "affected_modules": sorted(list(all_affected_modules)),
            "impacts": impacts,
            "total_files_analyzed": len(changes),
            "files_with_impact": len(impacts),
            "recommendation": recommendation,
            "analysis_source": "pattern",
        }

    def _match_rules(self, file_path: str) -> List[Dict]:
        """Match file path against impact rules."""
        matched = []
        for prefix, rule in self.rules.items():
            if file_path.startswith(prefix):
                matched.append(rule)
        return matched

    # ========================================================================
    # Phase 3: Neo4j Graph-Based Analysis
    # ========================================================================

    async def _analyze_with_neo4j(
        self,
        diff: List[str],
        phase2_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze impact using Neo4j (K15) queries.

        Args:
            diff: List of changed file paths
            phase2_result: Phase 2 pattern analysis result

        Returns:
            Graph analysis result dict or None
        """
        if not self.propagation:
            return None

        logger.debug("[A12] Analyzing with Neo4j (K15)")

        # Batch analyze all changed entities
        try:
            batch_result = await self.propagation.analyze_batch_impact(diff, max_depth=3)

            graph_impacts = []
            for individual_impact in batch_result.get("individual_impacts", []):
                entity = individual_impact.get("changed_entity", "unknown")
                affected = individual_impact.get("affected_count", 0)
                risk = individual_impact.get("risk_level", "UNKNOWN")

                graph_impacts.append({
                    "entity": entity,
                    "affected_count": affected,
                    "risk_level": risk,
                    "affected_nodes": individual_impact.get("affected_nodes", []),
                })

            return {
                "graph_impacts": graph_impacts,
                "combined_risk_level": batch_result.get("combined_risk_level", "UNKNOWN"),
                "total_affected": batch_result.get("total_affected", 0),
                "analysis_source": "neo4j",
            }

        except Exception as e:
            logger.error(f"[A12] Neo4j batch analysis failed: {str(e)}")
            return None

    # ========================================================================
    # Result Merging
    # ========================================================================

    def _merge_results(
        self,
        phase2: Dict[str, Any],
        phase3: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Merge Phase 2 and Phase 3 analysis results.

        Args:
            phase2: Pattern-based analysis
            phase3: Neo4j-based analysis (optional)

        Returns:
            Merged impact report
        """
        if not phase3:
            # No Neo4j data available, use Phase 2 only
            return {
                **phase2,
                "analysis_phases": ["phase2"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Merge severity levels: take higher risk
        severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        phase2_score = severity_order.get(phase2.get("overall_severity", "none"), 0)
        phase3_score = severity_order.get(
            self._risk_to_severity(phase3.get("combined_risk_level", "LOW")), 0
        )

        merged_severity_score = max(phase2_score, phase3_score)
        severity_reverse = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "critical"}
        merged_severity = severity_reverse.get(merged_severity_score, "none")

        # Merge affected modules
        merged_modules = set(phase2.get("affected_modules", []))
        for impact in phase3.get("graph_impacts", []):
            for node in impact.get("affected_nodes", []):
                module_name = node.get("name") or node.get("id")
                if module_name:
                    merged_modules.add(module_name)

        return {
            "overall_severity": merged_severity,
            "affected_modules": sorted(list(merged_modules)),
            "impacts": phase2.get("impacts", []),
            "graph_impacts": phase3.get("graph_impacts", []),
            "combined_risk_level": phase3.get("combined_risk_level", "UNKNOWN"),
            "total_files_analyzed": phase2.get("total_files_analyzed", 0),
            "files_with_impact": phase2.get("files_with_impact", 0),
            "total_graph_affected": phase3.get("total_affected", 0),
            "recommendation": self._generate_merged_recommendation(
                merged_severity,
                merged_modules,
                phase3.get("combined_risk_level")
            ),
            "analysis_phases": ["phase2", "phase3"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _risk_to_severity(risk_level: str) -> str:
        """Convert K15 risk level to severity score."""
        mapping = {
            "LOW": "low",
            "MEDIUM": "medium",
            "HIGH": "high",
            "CRITICAL": "critical",
        }
        return mapping.get(risk_level, "low")

    # ========================================================================
    # Recommendations
    # ========================================================================

    def _generate_recommendation(self, severity: str, modules: set) -> str:
        """Generate testing recommendation based on severity."""
        if severity == "high":
            return (
                f"高风险变更，建议执行全量回归测试。受影响模块: {', '.join(sorted(modules))}。"
            )
        elif severity == "medium":
            return (
                f"中等风险变更，建议对受影响模块执行集成测试。"
                f"受影响模块: {', '.join(sorted(modules))}。"
            )
        elif severity == "low":
            return (
                f"低风险变更，建议对受影响模块执行 smoke 测试。"
                f"受影响模块: {', '.join(sorted(modules))}。"
            )
        else:
            return "无明显风险变更，常规测试即可。"

    def _generate_merged_recommendation(
        self,
        severity: str,
        modules: set,
        graph_risk: Optional[str] = None
    ) -> str:
        """Generate recommendation from merged analysis."""
        base_rec = self._generate_recommendation(severity, modules)

        if graph_risk and graph_risk in ["HIGH", "CRITICAL"]:
            return (
                f"{base_rec} 图数据库分析显示高风险传播，"
                f"请特别关注跨模块依赖。"
            )

        return base_rec

    # ========================================================================
    # Phase 4: Security Analysis
    # ========================================================================

    async def _security_analysis(self, diff: List[str]) -> Optional[Dict[str, Any]]:
        """Analyze security issues in changed files.

        Args:
            diff: List of changed file paths

        Returns:
            Security analysis result dict or None if scanning unavailable
        """
        if not self.security_scanner:
            return None

        logger.debug(f"[A12] Performing security analysis on {len(diff)} files")

        try:
            # Filter for supported file types
            supported_files = [
                f for f in diff
                if f.endswith(('.py', '.js', '.ts', '.jsx', '.tsx', 'package.json'))
            ]

            if not supported_files:
                logger.debug("[A12] No supported files for security scanning")
                return {
                    "success": True,
                    "findings": [],
                    "risk_score": 0.0,
                    "risk_level": "NONE",
                    "summary": {"total_findings": 0},
                }

            # Scan all supported files
            scan_result = await self.security_scanner.scan_multiple(supported_files)

            if not scan_result["success"]:
                logger.warning("[A12] Security scan failed")
                return None

            # Generate security report
            security_report = self.cwe_mapper.generate_report(scan_result["all_findings"])

            return {
                "success": True,
                "findings": scan_result["all_findings"],
                "results_by_file": scan_result["results_by_file"],
                "risk_score": security_report["risk_score"],
                "risk_level": security_report["risk_level"],
                "decision": security_report["decision"],
                "recommendation": security_report["recommendation"],
                "summary": {
                    "total_findings": security_report["total_findings"],
                    "critical_count": security_report["critical_count"],
                    "high_count": security_report["high_count"],
                    "by_severity": security_report["categories"]["by_severity"],
                    "by_tool": security_report["categories"]["by_tool"],
                },
            }

        except Exception as e:
            logger.error(f"[A12] Security analysis error: {str(e)}", exc_info=True)
            return None

    # ========================================================================
    # Result Merging (Updated)
    # ========================================================================

    def _merge_results(
        self,
        phase2: Dict[str, Any],
        phase3: Optional[Dict[str, Any]],
        phase4: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Merge Phase 2, Phase 3, and Phase 4 analysis results.

        Args:
            phase2: Pattern-based analysis
            phase3: Neo4j-based analysis (optional)
            phase4: Security analysis (optional)

        Returns:
            Merged impact report
        """
        # Start with Phase 2 + Phase 3 merge
        if not phase3:
            # No Neo4j data available, use Phase 2 only
            base_result = {
                **phase2,
                "analysis_phases": ["phase2"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        else:
            # Merge severity levels: take higher risk
            severity_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
            phase2_score = severity_order.get(phase2.get("overall_severity", "none"), 0)
            phase3_score = severity_order.get(
                self._risk_to_severity(phase3.get("combined_risk_level", "LOW")), 0
            )

            merged_severity_score = max(phase2_score, phase3_score)
            severity_reverse = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "critical"}
            merged_severity = severity_reverse.get(merged_severity_score, "none")

            # Merge affected modules
            merged_modules = set(phase2.get("affected_modules", []))
            for impact in phase3.get("graph_impacts", []):
                for node in impact.get("affected_nodes", []):
                    module_name = node.get("name") or node.get("id")
                    if module_name:
                        merged_modules.add(module_name)

            base_result = {
                "overall_severity": merged_severity,
                "affected_modules": sorted(list(merged_modules)),
                "impacts": phase2.get("impacts", []),
                "graph_impacts": phase3.get("graph_impacts", []),
                "combined_risk_level": phase3.get("combined_risk_level", "UNKNOWN"),
                "total_files_analyzed": phase2.get("total_files_analyzed", 0),
                "files_with_impact": phase2.get("files_with_impact", 0),
                "total_graph_affected": phase3.get("total_affected", 0),
                "recommendation": self._generate_merged_recommendation(
                    merged_severity,
                    merged_modules,
                    phase3.get("combined_risk_level")
                ),
                "analysis_phases": ["phase2", "phase3"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Merge with security results if available
        if phase4:
            base_result["security_findings"] = phase4.get("findings", [])
            base_result["security_results_by_file"] = phase4.get("results_by_file", {})
            base_result["security_risk_score"] = phase4.get("risk_score", 0.0)
            base_result["security_risk_level"] = phase4.get("risk_level", "NONE")
            base_result["security_decision"] = phase4.get("decision", "APPROVE")
            base_result["security_summary"] = phase4.get("summary", {})
            base_result["analysis_phases"].append("phase4")

            # Update overall decision if security found critical issues
            if phase4.get("decision") == "REJECT":
                base_result["overall_decision"] = "REJECT"
                base_result["rejection_reason"] = "Security vulnerabilities detected"
            else:
                base_result["overall_decision"] = "APPROVE"

        return base_result

    async def close(self) -> None:
        """Clean up resources."""
        if self.propagation:
            await self.propagation.close()


# ============================================================================
# Convenience Functions
# ============================================================================

async def analyze_diff_impact(
    diff: List[str],
    dependency_graph: Optional[Dict] = None,
    use_neo4j: bool = True
) -> Dict[str, Any]:
    """Convenience function for impact analysis."""
    analyzer = CrossModuleImpactAnalyzer(use_neo4j=use_neo4j)
    try:
        return await analyzer.analyze(diff, dependency_graph)
    finally:
        await analyzer.close()
