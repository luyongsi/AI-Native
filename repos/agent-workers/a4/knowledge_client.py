"""
A4 Sub-module: Knowledge Client

MCP-based knowledge retrieval for A4 spec writing.
Calls 3 MCP tools in parallel with 5s timeout each:
  - get_openapi_templates(domain) — domain-specific OpenAPI templates
  - get_erd_patterns(domain) — domain-specific ERD design patterns
  - get_ddl_conventions() — team DDL naming/index conventions

Three-tier degradation:
  1. Full — all MCP tools available + LLM normal
  2. Partial — some MCP tools failed, LLM normal (source='llm_no_mcp')
  3. Fallback — LLM unavailable (source='fallback')
"""

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

MCP_GATEWAY_URL = os.environ.get("MCP_GATEWAY_URL", "http://localhost:8081/tools/call")


class MCPCallError(Exception):
    """Raised when an individual MCP tool call fails."""


class A4KnowledgeClient:
    """MCP knowledge-base client for A4 spec writing."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or MCP_GATEWAY_URL

    async def fetch_all(
        self, domain: str, timeout: float = 5.0,
    ) -> dict:
        """Fetch all three knowledge sources in parallel.

        Returns:
            {
              "tier": "full" | "partial" | "none",
              "openapi_templates": list[dict],
              "erd_patterns": list[dict],
              "ddl_conventions": dict | None,
              "errors": list[str],
            }
        """
        results = await asyncio.gather(
            self.get_openapi_templates(domain, timeout),
            self.get_erd_patterns(domain, timeout),
            self.get_ddl_conventions(timeout),
            return_exceptions=True,
        )

        openapi_templates, erd_patterns, ddl_conventions = results
        errors = []

        if isinstance(openapi_templates, Exception):
            errors.append(f"openapi_templates: {openapi_templates}")
            openapi_templates = []
        if isinstance(erd_patterns, Exception):
            errors.append(f"erd_patterns: {erd_patterns}")
            erd_patterns = []
        if isinstance(ddl_conventions, Exception):
            errors.append(f"ddl_conventions: {ddl_conventions}")
            ddl_conventions = None

        all_failed = (not openapi_templates and not erd_patterns
                      and ddl_conventions is None)
        any_failed = len(errors) > 0

        tier = "none" if all_failed else ("partial" if any_failed else "full")

        return {
            "tier": tier,
            "openapi_templates": openapi_templates,
            "erd_patterns": erd_patterns,
            "ddl_conventions": ddl_conventions,
            "errors": errors,
        }

    async def get_openapi_templates(
        self, domain: str, timeout: float = 5.0,
    ) -> list[dict]:
        """Get domain-specific OpenAPI templates.

        Returns:
            [{"name": "模板名", "template": {...}, "tags": [...]}, ...]
        """
        result = await self._call_tool(
            "get_openapi_templates",
            {"domain": domain or "general"},
            timeout,
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "templates" in result:
            return result["templates"]
        return []

    async def get_erd_patterns(
        self, domain: str, timeout: float = 5.0,
    ) -> list[dict]:
        """Get domain-specific ERD design patterns.

        Returns:
            [{"name": "模式名", "entities": [...], "relationships": [...]}, ...]
        """
        result = await self._call_tool(
            "get_erd_patterns",
            {"domain": domain or "general"},
            timeout,
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "patterns" in result:
            return result["patterns"]
        return []

    async def get_ddl_conventions(self, timeout: float = 5.0) -> dict | None:
        """Get team DDL writing conventions.

        Returns:
            {"naming": {...}, "indexing": {...}, "field_types": {...}} | None
        """
        result = await self._call_tool(
            "get_ddl_conventions", {}, timeout,
        )
        if isinstance(result, dict):
            return result
        return None

    async def _call_tool(
        self, tool_name: str, args: dict, timeout: float,
    ) -> dict | list | None:
        """Call an MCP tool via the gateway HTTP JSON-RPC interface."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=timeout + 2.0) as client:
                resp = await client.post(
                    self.base_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": args},
                        "id": 1,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=timeout,
                )
                resp.raise_for_status()
                body = resp.json()

                # JSON-RPC response
                if "result" in body:
                    result = body["result"]
                    if isinstance(result, dict) and "content" in result:
                        # MCP standard: content is an array of content items
                        content = result["content"]
                        if isinstance(content, list) and len(content) > 0:
                            text = content[0].get("text", "")
                            try:
                                return json.loads(text)
                            except (json.JSONDecodeError, TypeError):
                                return {"raw": text}
                    return result

                if "error" in body:
                    raise MCPCallError(f"MCP error: {body['error']}")

                return body
        except httpx.HTTPError as e:
            logger.warning(f"MCP HTTP error calling {tool_name}: {e}")
            raise MCPCallError(str(e))
        except Exception as e:
            logger.warning(f"MCP call {tool_name} failed: {e}")
            raise MCPCallError(str(e))
