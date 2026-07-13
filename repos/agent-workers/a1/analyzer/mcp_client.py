"""
A1 Agent — MCP Knowledge Base Client

Encapsulates 4 MCP tool calls:
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

MCP_GATEWAY_URL = os.environ.get("MCP_GATEWAY_URL", "http://localhost:8100/mcp")


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
            {"query": query, "top_k": 5},
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
                )
                if resp.status_code != 200:
                    logger.warning(
                        "MCP tool %s returned %d", tool_name, resp.status_code,
                    )
                    raise MCPCallError(f"HTTP {resp.status_code}")

                body = resp.json()
                if "error" in body:
                    raise MCPCallError(str(body["error"]))

                # MCP response: result.content[0].text is a JSON string
                content = body.get("result", {}).get("content", [])
                if content and isinstance(content[0], dict):
                    text = content[0].get("text", "{}")
                    import json as _json
                    return _json.loads(text)

                return None

        except (httpx.TimeoutException, MCPCallError):
            raise
        except Exception as exc:
            logger.warning("MCP tool %s error: %s", tool_name, exc)
            raise MCPCallError(str(exc))


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
