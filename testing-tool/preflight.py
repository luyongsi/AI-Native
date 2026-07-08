"""Pre-flight validation — verifies infrastructure readiness before Observer starts.

Checks:
  1. NATS connectivity + JetStream stream exists
  2. Stream has active consumers (Agent Workers subscribed)
  3. MC Backend reachable
  4. LLM API reachable (quick ping)

Note: NATS dispatch message structure is verified at runtime by RuntimeVerifier,
not here. Pre-flight only verifies that the infrastructure is alive.
"""

import json
import logging
import os

import httpx
import nats

logger = logging.getLogger(__name__)


class PreFlightValidator:
    def __init__(self, nats_url: str, mc_url: str = "http://localhost:8000"):
        self.nats_url = nats_url
        self.mc_url = mc_url

    async def validate(self) -> dict:
        """Returns {ready: bool, issues: [...], checks: {...}}"""
        issues = []
        checks = {}

        # 1. NATS connectivity
        try:
            nc = await nats.connect(self.nats_url)
            checks["nats_connect"] = True
        except Exception as e:
            return {
                "ready": False,
                "issues": [f"NATS unavailable: {e}"],
                "checks": {"nats_connect": False},
                "suggestions": ["Check NATS Docker container"],
            }

        # 2. JetStream stream exists
        try:
            js = nc.jetstream()
            info = await js.stream_info("AI_NATIVE_EVENTS")
            checks["stream_exists"] = True
            checks["consumer_count"] = info.state.consumer_count
            checks["messages_stored"] = info.state.messages

            if info.state.consumer_count == 0:
                issues.append(
                    f"AI_NATIVE_EVENTS stream has 0 consumers — "
                    "Agent Workers may not be running. "
                    "Agents won't receive dispatch messages."
                )
            else:
                checks["consumers_ok"] = True
        except Exception as e:
            issues.append(f"AI_NATIVE_EVENTS stream not found: {e}")
            checks["stream_exists"] = False
            await nc.close()
            return {
                "ready": False,
                "issues": issues,
                "checks": checks,
                "suggestions": ["Run reset_nats.py to create the JetStream stream"],
            }

        await nc.close()

        # 3. MC Backend reachable
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.get(f"{self.mc_url}/api/requirements?limit=1")
            checks["mc_backend"] = resp.status_code < 500
            if not checks["mc_backend"]:
                issues.append(f"MC Backend returned {resp.status_code}")
        except Exception as e:
            issues.append(f"MC Backend unavailable: {e}")
            checks["mc_backend"] = False

        # 4. LLM API quick ping
        try:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.post(
                    "https://uniapi.ruijie.com.cn/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro-202606"),
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5,
                    },
                )
            checks["llm"] = resp.status_code == 200
            if not checks["llm"]:
                issues.append(f"LLM API returned {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            issues.append(f"LLM API unreachable: {e}")
            checks["llm"] = False

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "checks": checks,
            "suggestions": [],
        }
