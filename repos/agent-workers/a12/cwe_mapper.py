"""
A12 CWE Mapper — CWE-to-severity mapping and risk scoring.

Maps Common Weakness Enumeration (CWE) IDs to standard severity levels
and calculates overall risk scores from security findings.

References:
  - CWE-89: SQL Injection
  - CWE-79: Cross-site Scripting (XSS)
  - CWE-78: OS Command Injection
  - CWE-22: Path Traversal
  - CWE-502: Deserialization of Untrusted Data
  - CWE-798: Use of Hard-coded Credentials
  - CWE-327: Use of a Broken or Risky Cryptographic Algorithm
  - CWE-918: Server-Side Request Forgery (SSRF)
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# CWE to CVSS severity mapping
CWE_SEVERITY_MAP = {
    # Critical severity
    "CWE-89": "CRITICAL",   # SQL Injection
    "CWE-78": "CRITICAL",   # OS Command Injection
    "CWE-94": "CRITICAL",   # Code Injection
    "CWE-95": "CRITICAL",   # Improper Neutralization of Directives in Dynamically Evaluated Code
    "CWE-798": "CRITICAL",  # Use of Hard-coded Credentials
    "CWE-434": "CRITICAL",  # Unrestricted Upload of File with Dangerous Type

    # High severity
    "CWE-79": "HIGH",       # Cross-site Scripting (XSS)
    "CWE-22": "HIGH",       # Improper Limitation of a Pathname to a Restricted Directory
    "CWE-502": "HIGH",      # Deserialization of Untrusted Data
    "CWE-918": "HIGH",      # Server-Side Request Forgery (SSRF)
    "CWE-611": "HIGH",      # Improper Restriction of XML External Entity Reference
    "CWE-401": "HIGH",      # Missing Release of Memory after Effective Lifetime
    "CWE-416": "HIGH",      # Use-After-Free
    "CWE-476": "HIGH",      # Null Pointer Dereference

    # Medium severity
    "CWE-327": "MEDIUM",    # Use of a Broken or Risky Cryptographic Algorithm
    "CWE-338": "MEDIUM",    # Use of Cryptographically Weak Pseudo-Random Number Generator
    "CWE-259": "MEDIUM",    # Use of Hard-coded Password
    "CWE-295": "MEDIUM",    # Improper Certificate Validation
    "CWE-352": "MEDIUM",    # Cross-Site Request Forgery (CSRF)
    "CWE-552": "MEDIUM",    # Files or Directories Accessible to External Parties

    # Low severity
    "CWE-319": "LOW",       # Cleartext Transmission of Sensitive Information
    "CWE-330": "LOW",       # Use of Insufficiently Random Values
    "CWE-444": "LOW",       # Inconsistent Interpretation of HTTP Requests
    "CWE-534": "LOW",       # Information Exposure Through Debug Log Files
}

# Bandit test IDs to CWE mapping
BANDIT_TEST_CWE_MAP = {
    "B101": "CWE-391",      # assert_used
    "B102": "CWE-391",      # exec_used
    "B103": "CWE-377",      # set_bad_file_permissions
    "B104": "CWE-377",      # hardcoded_temp_directory
    "B105": "CWE-89",       # hardcoded_sql_string
    "B106": "CWE-327",      # hardcoded_password_string
    "B107": "CWE-327",      # hardcoded_password_default
    "B108": "CWE-327",      # hardcoded_password_func_arg
    "B109": "CWE-327",      # hardcoded_password_variable
    "B110": "CWE-327",      # hardcoded_sql_expression
    "B201": "CWE-78",       # flask_debug_true
    "B301": "CWE-502",      # pickle
    "B302": "CWE-90",       # marshal
    "B303": "CWE-95",       # md5
    "B304": "CWE-327",      # des
    "B305": "CWE-327",      # cipher
    "B306": "CWE-327",      # mktemp_q
    "B307": "CWE-327",      # eval
    "B308": "CWE-611",      # mark_safe
    "B309": "CWE-611",      # parse_xml
    "B310": "CWE-611",      # urllib_parse
    "B311": "CWE-327",      # random
    "B312": "CWE-327",      # telnetlib
    "B313": "CWE-502",      # xml_bad_expat
    "B314": "CWE-502",      # xml_bad_etree
    "B315": "CWE-502",      # xml_bad_pulldom
    "B316": "CWE-502",      # xml_bad_sax
    "B317": "CWE-502",      # xml_bad_minidom
    "B318": "CWE-502",      # xml_bad_pulldom
    "B319": "CWE-502",      # xml_bad_etree
    "B320": "CWE-502",      # xml_bad_expat
    "B321": "CWE-502",      # ftplib
    "B322": "CWE-502",      # unverified_context
    "B323": "CWE-78",       # unguarded_temp_directory
    "B324": "CWE-327",      # probable_insecure_hash_usage
    "B325": "CWE-327",      # probable_insecure_hash_usage_hashlib
    "B401": "CWE-502",      # paramiko
    "B402": "CWE-327",      # flask_debug
    "B403": "CWE-502",      # import_pickle
    "B404": "CWE-502",      # import_subprocess
    "B405": "CWE-611",      # import_xml_etree
    "B406": "CWE-611",      # import_xml_sax
    "B407": "CWE-611",      # import_xml_expat
    "B408": "CWE-611",      # import_xml_minidom
    "B409": "CWE-611",      # import_xml_pulldom
    "B410": "CWE-611",      # import_xmlrpc
    "B411": "CWE-327",      # import_httpoxy
    "B501": "CWE-327",      # request_verify
    "B502": "CWE-327",      # ssl_insecure_version
    "B503": "CWE-295",      # ssl_verify_disabled
    "B504": "CWE-327",      # ssl_with_bad_version
    "B505": "CWE-327",      # weak_cryptographic_key
    "B506": "CWE-89",       # yaml_load
    "B601": "CWE-327",      # paramiko_calls
    "B602": "CWE-78",       # shell_injection
    "B603": "CWE-78",       # subprocess_without_shell
    "B604": "CWE-78",       # any_other_function_with_shell_equals_true
    "B605": "CWE-78",       # start_process_with_a_shell
    "B606": "CWE-327",      # process_with_no_shell
    "B607": "CWE-426",      # partial_path_dependency
    "B608": "CWE-89",       # hardcoded_sql_string
    "B609": "CWE-327",      # wildcard_injection
    "B610": "CWE-90",       # sql_expression
    "B611": "CWE-327",      # sqlalchemy_from_string
    "B701": "CWE-327",      # jinja2_autoescape
    "B702": "CWE-327",      # mako_templates
    "B703": "CWE-327",      # django_mark_safe
    "B704": "CWE-327",      # django_template_tag
}


class CWEMapper:
    """Map CWE IDs to severity levels and calculate risk scores."""

    def __init__(self):
        """Initialize CWE mapper."""
        self.cwe_severity_map = CWE_SEVERITY_MAP
        self.bandit_cwe_map = BANDIT_TEST_CWE_MAP

    def map_severity(self, cwe_id: Optional[str]) -> str:
        """
        Map CWE ID to standard severity level.

        Args:
            cwe_id: CWE identifier (e.g., "CWE-89")

        Returns:
            Severity level: CRITICAL, HIGH, MEDIUM, or LOW
        """
        if not cwe_id:
            return "MEDIUM"

        cwe_id = str(cwe_id).strip().upper()
        return self.cwe_severity_map.get(cwe_id, "MEDIUM")

    def map_bandit_test_to_severity(self, test_id: str) -> str:
        """
        Map Bandit test ID to severity via CWE.

        Args:
            test_id: Bandit test ID (e.g., "B602")

        Returns:
            Severity level: CRITICAL, HIGH, MEDIUM, or LOW
        """
        test_id = str(test_id).strip().upper()
        cwe_id = self.bandit_cwe_map.get(test_id)
        if cwe_id:
            return self.map_severity(cwe_id)
        return "MEDIUM"

    def calculate_risk_score(self, findings: List[Dict]) -> float:
        """
        Calculate overall risk score from findings (0-10 scale).

        Scoring algorithm:
        - CRITICAL: 3.0 points per finding
        - HIGH: 2.0 points per finding
        - MEDIUM: 1.0 point per finding
        - LOW: 0.5 points per finding
        - Score capped at 10.0

        Args:
            findings: List of security findings

        Returns:
            Risk score from 0.0 to 10.0
        """
        score = 0.0

        for finding in findings:
            severity = finding.get("severity", "MEDIUM")

            # Normalize severity to uppercase
            if isinstance(severity, str):
                severity = severity.upper()

            if severity == "CRITICAL":
                score += 3.0
            elif severity == "HIGH":
                score += 2.0
            elif severity == "MEDIUM":
                score += 1.0
            elif severity == "LOW":
                score += 0.5

        # Cap at 10.0
        return min(score, 10.0)

    def estimate_risk_level(self, risk_score: float) -> str:
        """
        Convert risk score (0-10) to categorical risk level.

        Args:
            risk_score: Risk score from 0.0 to 10.0

        Returns:
            Risk level: CRITICAL, HIGH, MEDIUM, LOW, or NONE
        """
        if risk_score >= 8.0:
            return "CRITICAL"
        elif risk_score >= 6.0:
            return "HIGH"
        elif risk_score >= 3.0:
            return "MEDIUM"
        elif risk_score > 0.0:
            return "LOW"
        else:
            return "NONE"

    def get_recommendation(self, risk_score: float, critical_count: int, high_count: int) -> str:
        """
        Generate recommendation based on risk metrics.

        Args:
            risk_score: Overall risk score (0-10)
            critical_count: Number of critical findings
            high_count: Number of high findings

        Returns:
            Recommendation string
        """
        if critical_count > 0:
            return (
                f"REJECT: {critical_count} critical vulnerability/ies found. "
                f"Must be fixed before merge (risk score: {risk_score:.1f}/10)."
            )

        if risk_score >= 8.0:
            return (
                f"REJECT: Risk score {risk_score:.1f}/10 exceeds threshold. "
                f"Critical security issues must be addressed."
            )

        if risk_score >= 6.0:
            return (
                f"CONDITIONAL: High risk ({high_count} high-severity issues). "
                f"Requires security review and fixes (risk score: {risk_score:.1f}/10)."
            )

        if risk_score >= 3.0:
            return (
                f"REVIEW: Medium risk detected. "
                f"Recommend code review and consideration of fixes (risk score: {risk_score:.1f}/10)."
            )

        if risk_score > 0.0:
            return (
                f"APPROVE: Low-risk changes with minor security observations "
                f"(risk score: {risk_score:.1f}/10)."
            )

        return "APPROVE: No security issues detected."

    def categorize_findings(self, findings: List[Dict]) -> Dict:
        """
        Categorize findings by severity and tool.

        Args:
            findings: List of security findings

        Returns:
            {
                "by_severity": dict,
                "by_tool": dict,
                "by_cwe": dict,
            }
        """
        categories = {
            "by_severity": {
                "CRITICAL": [],
                "HIGH": [],
                "MEDIUM": [],
                "LOW": [],
            },
            "by_tool": {},
            "by_cwe": {},
        }

        for finding in findings:
            severity = finding.get("severity", "MEDIUM").upper()
            if severity in categories["by_severity"]:
                categories["by_severity"][severity].append(finding)

            tool = finding.get("tool", "unknown")
            if tool not in categories["by_tool"]:
                categories["by_tool"][tool] = []
            categories["by_tool"][tool].append(finding)

            cwe = finding.get("cwe")
            if cwe:
                if cwe not in categories["by_cwe"]:
                    categories["by_cwe"][cwe] = []
                categories["by_cwe"][cwe].append(finding)

        return categories

    def generate_report(self, findings: List[Dict]) -> Dict:
        """
        Generate comprehensive security report from findings.

        Args:
            findings: List of security findings

        Returns:
            Comprehensive report dict with scoring, categorization, and recommendations
        """
        risk_score = self.calculate_risk_score(findings)
        risk_level = self.estimate_risk_level(risk_score)
        categories = self.categorize_findings(findings)

        critical_count = len(categories["by_severity"]["CRITICAL"])
        high_count = len(categories["by_severity"]["HIGH"])
        medium_count = len(categories["by_severity"]["MEDIUM"])
        low_count = len(categories["by_severity"]["LOW"])

        decision = "REJECT" if risk_score > 7.0 else "APPROVE"
        recommendation = self.get_recommendation(risk_score, critical_count, high_count)

        return {
            "decision": decision,
            "risk_score": round(risk_score, 2),
            "risk_level": risk_level,
            "total_findings": len(findings),
            "critical_count": critical_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "categories": categories,
            "recommendation": recommendation,
        }
