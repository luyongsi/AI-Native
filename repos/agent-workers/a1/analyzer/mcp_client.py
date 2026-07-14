"""
A1 Agent — MCP Knowledge Base Client

Encapsulates 5 MCP tool calls (4 original + 1 added for A2):
  - search_similar_requirements
  - get_domain_risks
  - get_tech_stack_recommendations
  - get_cost_baseline

All calls are parallelized via asyncio.gather with individual 5s timeouts.
Single failure does not block the rest.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

MCP_GATEWAY_URL = os.environ.get("MCP_GATEWAY_URL", "http://localhost:8081/tools/call")


class MCPCallError(Exception):
    """Raised when an individual MCP tool call fails."""


class MCPClient:
    """MCP knowledge-base calling facade."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or MCP_GATEWAY_URL

    async def search_similar_requirements(
        self, draft: dict | None, timeout: float = 5.0,
    ) -> list[dict]:
        """Search for similar historical requirements.

        Returns:
            [{"id": "uuid", "title": "需求标题", "similarity": 0.92, "metadata": {...}}, ...]
        """
        query = _build_search_text(draft)
        result = await self._call_tool(
            "search_similar_requirements",
            {"query": query, "limit": 5},
            timeout,
        )
        if isinstance(result, list):
            return result
        return []

    async def get_domain_risks(
        self, domain: str, timeout: float = 5.0,
    ) -> list[dict]:
        """Query known risks for a domain.

        Returns:
            [{"risk": "风险名称", "description": "...", "severity": "high|medium|low"}, ...]
        """
        result = await self._call_tool(
            "get_domain_risks",
            {"domain": domain or "general"},
            timeout,
        )
        if isinstance(result, list):
            return result
        return []

    async def get_tech_stack_recommendations(
        self, draft: dict | None, timeout: float = 5.0,
    ) -> dict:
        """Recommend a technology stack based on the draft.

        Returns:
            {"backend": "...", "frontend": "...", "database": "..."} | {}
        """
        query = _build_search_text(draft)
        result = await self._call_tool(
            "get_tech_stack_recommendations",
            {"query": query},
            timeout,
        )
        if isinstance(result, dict):
            return result
        return {}

    async def get_cost_baseline(
        self, draft: dict | None, timeout: float = 5.0,
    ) -> dict | None:
        """Estimate cost baseline for a requirement.

        Returns:
            {"estimated_effort_months": 3.0, "team_size": 2, "breakdown": {...}} | None
        """
        query = _build_search_text(draft)
        result = await self._call_tool(
            "get_cost_baseline",
            {"query": query},
            timeout,
        )
        if isinstance(result, dict):
            return result
        return None

    async def search_known_issues(
        self, draft: dict | None, timeout: float = 5.0,
    ) -> list[dict]:
        """Search for known issues/bugs/technical debt related to the draft.

        Returns:
            [{"id": "uuid", "title": "issue title", "similarity": 0.88, ...}, ...]
        """
        query = _build_search_text(draft)
        result = await self._call_tool(
            "search_known_issues",
            {"query": query, "limit": 10},
            timeout,
        )
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    async def _call_tool(
        self, tool_name: str, args: dict, timeout: float,
    ) -> dict | list | None:
        """Call an MCP tool via HTTP JSON-RPC.

        Uses short overall timeout (timeout param) and even shorter connect
        timeout (1.5 s) so an absent MCP gateway fails fast.
        """
        try:
            import httpx

            headers = {}
            # JWT auth required for /tools/* endpoints on the Gateway
            jwt_token = await self._ensure_token()
            if jwt_token:
                headers["Authorization"] = f"Bearer {jwt_token}"

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=1.5),
            ) as client:
                resp = await client.post(
                    self.base_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": args},
                        "id": 1,
                    },
                    headers=headers,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "MCP tool %s returned %d", tool_name, resp.status_code,
                    )
                    raise MCPCallError(f"HTTP {resp.status_code}")

                body = resp.json()
                if "error" in body:
                    raise MCPCallError(str(body["error"]))

                # Go server returns {result: <raw data>} — no content[0].text wrapper
                data = body.get("result")
                if data is not None:
                    return data

                return None

        except (httpx.TimeoutException, MCPCallError):
            raise
        except Exception as exc:
            logger.warning("MCP tool %s error: %s", tool_name, exc)
            raise MCPCallError(str(exc))

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    _token: str | None = None

    async def _ensure_token(self) -> str | None:
        """Obtain a JWT from the Gateway's /auth/token endpoint (cached)."""
        if self._token:
            return self._token
        try:
            import httpx
            # Derive auth URL from the tools URL: /tools/call → /auth/token
            auth_url = self.base_url.rsplit("/tools/", 1)[0] + "/auth/token"
            async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1.5)) as client:
                resp = await client.post(
                    auth_url,
                    json={"agent_id": "a1", "req_id": "mcp-client-init"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data.get("token") or data.get("access_token")
                    if self._token:
                        logger.debug("MCP JWT token obtained")
                    return self._token
        except Exception:
            logger.debug("MCP JWT token request failed — will call without auth")
        return None


# ------------------------------------------------------------------
def _build_search_text(draft: dict | None) -> str:
    """Build a search query string from the current draft."""
    if not draft:
        return ""
    parts = []
    if draft.get("title"):
        parts.append(draft["title"])
    if draft.get("description"):
        parts.append(draft["description"])
    if draft.get("domain"):
        parts.append(draft["domain"])
    return " ".join(parts)
