"""
Egress Firewall — Domain-level egress rules for Firecracker sandbox VMs.

Enforces a strict allowlist (whitelist) of outbound domains that agent code
running inside Firecracker microVMs is permitted to reach. All other egress
traffic is blocked at the CNI level via iptables rules applied to the
firecracker tap interfaces.

Design:
    - Whitelist approach: only explicitly allowed domains pass through
    - CNI-level enforcement: iptables rules on the VM's tap interface
    - Default policy: DROP all outbound traffic
    - Managed via a simple in-memory rule set

Default allowed domains:
    - github.com        (source code access)
    - npmjs.org         (Node.js package registry)
    - pypi.org          (Python package registry)
    - anthropic.com     (Claude API access)
    - mcp-gateway.internal (internal MCP gateway service)

Pure functions — no async needed since this operates on in-memory rules
and would correspond to iptables rule management in production.
"""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EgressFirewall:
    """
    Manages egress firewall rules for Firecracker sandbox VMs.

    Real implementation (future):
        import subprocess

        TAP_PREFIX = "fc-"
        CHAIN_NAME = "FC_EGRESS"

        def _apply_iptables(self, domain: str, port: int, action: str):
            # Resolve domain to IP ranges, add/del iptables rules
            # iptables -A FC_EGRESS -i fc-*-tap -d <ip> -p tcp --dport <port> -j ACCEPT
            ...

    Stub implementation (current):
        Maintains an in-memory rule set with validation logic.
    """

    # Default allowed domains (egress whitelist)
    DEFAULT_WHITELIST: list[str] = [
        "github.com",
        "npmjs.org",
        "pypi.org",
        "anthropic.com",
        "mcp-gateway.internal",
    ]

    def __init__(self):
        self._rules: list[dict] = []
        # Seed with default whitelist rules
        for domain in self.DEFAULT_WHITELIST:
            self._rules.append({
                "domain": domain,
                "port": 443,
                "protocol": "tcp",
                "action": "ACCEPT",
                "source": "defaults",
            })
        logger.info(
            "[EgressFirewall] Initialized with %d whitelist rule(s)",
            len(self._rules),
        )

    # ------------------------------------------------------------------
    # Get Whitelist
    # ------------------------------------------------------------------

    def get_whitelist(self) -> list[str]:
        """
        Return the list of currently allowed domains.

        Real implementation (future):
            # Parse iptables-save output for FC_EGRESS chain
            ...

        Returns:
            list of domain name strings in the whitelist.
        """
        domains = sorted(set(r["domain"] for r in self._rules))
        logger.debug(
            "[EgressFirewall] Returning whitelist: %d domain(s)",
            len(domains),
        )
        return domains

    # ------------------------------------------------------------------
    # Is Allowed
    # ------------------------------------------------------------------

    def is_allowed(self, url: str) -> bool:
        """
        Check whether a URL's domain is in the egress whitelist.

        Parses the URL, extracts the hostname, and checks it against
        the current rule set. Only exact domain or subdomain matches
        are permitted (e.g., "api.github.com" is allowed because
        it's a subdomain of "github.com").

        Args:
            url: Full URL string to check (e.g., "https://github.com/org/repo").

        Returns:
            True if the domain is allowed, False otherwise.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
        except Exception:
            logger.warning("[EgressFirewall] Failed to parse URL: %s", url)
            return False

        if not hostname:
            logger.warning("[EgressFirewall] No hostname found in URL: %s", url)
            return False

        allowed_domains = self.get_whitelist()

        for domain in allowed_domains:
            # Exact match
            if hostname == domain:
                logger.debug("[EgressFirewall] ALLOW %s (exact match: %s)", url, domain)
                return True
            # Subdomain match (e.g., api.github.com matches github.com)
            if hostname.endswith("." + domain):
                logger.debug("[EgressFirewall] ALLOW %s (subdomain match: %s)", url, domain)
                return True

        logger.debug("[EgressFirewall] DENY %s (not in whitelist)", url)
        return False

    # ------------------------------------------------------------------
    # Add Rule
    # ------------------------------------------------------------------

    def add_rule(self, domain: str, port: int = 443) -> dict:
        """
        Add a new egress firewall rule for a domain.

        Real implementation (future):
            subprocess.run([
                "iptables", "-A", "FC_EGRESS",
                "-i", "fc-+-tap",
                "-d", domain,
                "-p", "tcp", "--dport", str(port),
                "-j", "ACCEPT",
            ], check=True)

        Args:
            domain: Domain name to allow (e.g., "registry.example.com").
            port: Destination port (default 443 for HTTPS).

        Returns:
            dict with keys:
                added   - True if the rule was added
                domain  - The domain
                port    - The port
                message - Human-readable status message
        """
        # Check if already exists
        for rule in self._rules:
            if rule["domain"] == domain and rule["port"] == port:
                logger.info(
                    "[EgressFirewall] Rule already exists: %s:%d",
                    domain, port,
                )
                return {
                    "added": False,
                    "domain": domain,
                    "port": port,
                    "message": f"Rule for {domain}:{port} already exists",
                }

        new_rule = {
            "domain": domain,
            "port": port,
            "protocol": "tcp",
            "action": "ACCEPT",
            "source": "manual",
        }
        self._rules.append(new_rule)

        logger.info("[EgressFirewall] Rule added: %s:%d", domain, port)
        print(
            f"[EgressFirewall] [STUB] Would run: "
            f"iptables -A FC_EGRESS -i fc-+-tap -d {domain} "
            f"-p tcp --dport {port} -j ACCEPT"
        )

        return {
            "added": True,
            "domain": domain,
            "port": port,
            "message": f"Rule added: {domain}:{port} -> ACCEPT",
        }

    # ------------------------------------------------------------------
    # Remove Rule
    # ------------------------------------------------------------------

    def remove_rule(self, domain: str) -> bool:
        """
        Remove all egress firewall rules matching a domain.

        Real implementation (future):
            subprocess.run([
                "iptables", "-D", "FC_EGRESS",
                "-i", "fc-+-tap",
                "-d", domain,
                "-j", "ACCEPT",
            ], check=True)

        Args:
            domain: Domain name to remove from the rules.

        Returns:
            True if at least one rule was removed, False if no match.
        """
        initial_count = len(self._rules)
        self._rules = [r for r in self._rules if r["domain"] != domain]
        removed_count = initial_count - len(self._rules)

        if removed_count > 0:
            logger.info(
                "[EgressFirewall] Removed %d rule(s) for domain: %s",
                removed_count, domain,
            )
            print(
                f"[EgressFirewall] [STUB] Would run: "
                f"iptables -D FC_EGRESS -i fc-+-tap -d {domain} -j ACCEPT"
            )
            print(
                f"[EgressFirewall] [STUB] {removed_count} rule(s) removed for {domain}"
            )
            return True
        else:
            logger.warning(
                "[EgressFirewall] No rules found for domain: %s",
                domain,
            )
            print(
                f"[EgressFirewall] [STUB] No rules found for domain: {domain}"
            )
            return False

    # ------------------------------------------------------------------
    # Get Rules
    # ------------------------------------------------------------------

    def get_rules(self) -> list[dict]:
        """
        Return all current egress firewall rules.

        Real implementation (future):
            # Parse: iptables -L FC_EGRESS -n --line-numbers
            ...

        Returns:
            list of dict, each with keys:
                domain, port, protocol, action, source
        """
        logger.debug(
            "[EgressFirewall] Returning %d rule(s)",
            len(self._rules),
        )
        return list(self._rules)

    # ------------------------------------------------------------------
    # Validate Config
    # ------------------------------------------------------------------

    def validate_config(self) -> dict:
        """
        Validate the firewall configuration for correctness.

        Checks:
            - No duplicate rules (same domain + port)
            - No empty domains
            - Ports are in valid range (1-65535)
            - All default whitelist domains are present
            - At least one rule exists

        Real implementation (future):
            Also verifies iptables chain exists and rules are active:
                subprocess.run(["iptables", "-L", "FC_EGRESS"], check=True)

        Returns:
            dict with keys:
                valid          - True if configuration passes all checks
                errors         - List of error messages (empty if valid)
                warnings       - List of warning messages
                rule_count     - Total number of active rules
                whitelist_size - Number of unique domains in the whitelist
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check for empty configuration
        if not self._rules:
            errors.append("No firewall rules defined — all egress traffic would be blocked")

        # Check for duplicates and invalid entries
        seen = set()
        for rule in self._rules:
            domain = rule.get("domain", "")
            port = rule.get("port", 0)

            # Empty domain
            if not domain:
                errors.append(f"Rule has empty domain: {rule}")
                continue

            # Invalid port
            if not (1 <= port <= 65535):
                errors.append(f"Invalid port {port} for domain '{domain}'")

            # Duplicate check (domain + port)
            key = (domain, port)
            if key in seen:
                warnings.append(f"Duplicate rule: {domain}:{port}")
            seen.add(key)

        # Check all default domains are present
        current_domains = self.get_whitelist()
        for default_domain in self.DEFAULT_WHITELIST:
            if default_domain not in current_domains:
                warnings.append(
                    f"Default domain '{default_domain}' is not in the whitelist"
                )

        valid = len(errors) == 0

        logger.info(
            "[EgressFirewall] Configuration validation: valid=%s, "
            "%d error(s), %d warning(s), %d rule(s)",
            valid, len(errors), len(warnings), len(self._rules),
        )

        return {
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "rule_count": len(self._rules),
            "whitelist_size": len(current_domains),
        }
