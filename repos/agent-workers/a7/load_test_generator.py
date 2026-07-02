"""
Load Test Generator — generates k6 load test scripts from OpenAPI specs.

Real implementation would:
  - Parse OpenAPI operations and map each to a k6 request
  - Derive realistic scenarios: smoke, average-load, stress, spike, soak
  - Auto-tune VUs, duration, and ramp-up using historical traffic patterns
  - Embed checks for status code, response time, and JSON body assertions
  - Output a ready-to-run k6 script with thresholds and custom metrics
"""

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class LoadTestGenerator:
    """Generate k6 load test scripts from an OpenAPI 3.x specification."""

    # Pre-built execution scenarios
    PRESET_SCENARIOS = {
        "smoke": {"vus": 5, "duration": "1m", "ramp_up": "30s", "description": "Smoke test: minimal load to verify basic functionality"},
        "average": {"vus": 50, "duration": "5m", "ramp_up": "1m", "description": "Average load: simulates normal production traffic"},
        "stress": {"vus": 200, "duration": "10m", "ramp_up": "2m", "description": "Stress test: ramps up to find breaking point"},
        "spike": {"vus": 500, "duration": "2m", "ramp_up": "15s", "description": "Spike test: sudden traffic surge"},
        "soak": {"vus": 30, "duration": "30m", "ramp_up": "5m", "description": "Soak test: sustained load to detect memory leaks"},
    }

    async def generate_k6_script(self, api_spec: dict, target_url: str) -> dict:
        """
        Generate a k6 load test script from an OpenAPI spec.

        Args:
            api_spec: Parsed OpenAPI 3.x document.
            target_url: Base URL of the target service (e.g. https://api.example.com).

        Returns:
            {
                script: str,                # complete k6 JavaScript source
                scenarios: [{name, vus, duration, ramp_up}],
                checks: [],
            }
        """
        paths = api_spec.get("paths", {})
        logger.info(
            "Generating k6 load test script for %d path(s) targeting %s",
            len(paths),
            target_url,
        )

        # Build the list of HTTP requests to include in the script
        requests: List[Dict[str, Any]] = self._extract_requests(paths)

        # Select scenarios to include
        scenarios = [
            self.PRESET_SCENARIOS["smoke"],
            self.PRESET_SCENARIOS["average"],
            self.PRESET_SCENARIOS["stress"],
        ]

        # Build checks
        checks = self._build_checks(requests)

        # Render the k6 script
        script = self._render_k6_script(requests, scenarios, checks, target_url)

        logger.info(
            "k6 script generated: %d requests, %d scenarios, %d checks, %d chars",
            len(requests),
            len(scenarios),
            len(checks),
            len(script),
        )

        return {
            "script": script,
            "scenarios": [
                {
                    "name": name,
                    "vus": s["vus"],
                    "duration": s["duration"],
                    "ramp_up": s["ramp_up"],
                }
                for name, s in [
                    ("smoke", self.PRESET_SCENARIOS["smoke"]),
                    ("average", self.PRESET_SCENARIOS["average"]),
                    ("stress", self.PRESET_SCENARIOS["stress"]),
                ]
            ],
            "checks": checks,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_requests(self, paths: dict) -> list:
        """Walk OpenAPI paths and extract HTTP request definitions."""
        requests = []
        for path_url, path_item in paths.items():
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if not operation:
                    continue
                requests.append({
                    "method": method.upper(),
                    "path": path_url,
                    "operation_id": operation.get("operationId", f"{method}_{path_url}"),
                    "summary": operation.get("summary", ""),
                    "has_body": method in ("post", "put", "patch"),
                })
        return requests

    def _build_checks(self, requests: list) -> list:
        """Build k6 check definitions from extracted requests."""
        checks = []
        for req in requests:
            checks.append({
                "name": f"{req['method']} {req['path']} status is 2xx",
                "expression": f"check(res, {{ 'status 2xx': (r) => r.status >= 200 && r.status < 300 }})",
            })
            checks.append({
                "name": f"{req['method']} {req['path']} response time < 2000ms",
                "expression": f"check(res, {{ 'latency < 2000ms': (r) => r.timings.duration < 2000 }})",
            })
        return checks

    def _render_k6_script(
        self,
        requests: list,
        scenarios: list,
        checks: list,
        target_url: str,
    ) -> str:
        """Render the complete k6 JavaScript source."""
        lines = [
            "// Auto-generated k6 load test script",
            "// Generated by A7 Test Case Generator — LoadTestGenerator",
            "// Target: " + target_url,
            "",
            "import http from 'k6/http';",
            "import { check, sleep, group } from 'k6';",
            "import { Rate, Trend } from 'k6/metrics';",
            "",
            "// Custom metrics",
            "const errorRate = new Rate('errors');",
            "const responseTime = new Trend('response_time');",
            "",
            "// Configuration",
            f"const BASE_URL = '{target_url}';",
            "",
        ]

        # Scenarios / options block
        lines.append("export const options = {")
        lines.append("  scenarios: {")
        for i, scenario in enumerate(scenarios):
            name = ["smoke", "average", "stress"][i]
            lines.append(f"    {name}: {{")
            lines.append(f"      executor: 'ramping-vus',")
            lines.append(f"      startVUs: 0,")
            lines.append(f"      stages: [")
            lines.append(f"        {{ duration: '{scenario['ramp_up']}', target: {scenario['vus']} }},")
            lines.append(f"        {{ duration: '{scenario['duration']}', target: {scenario['vus']} }},")
            lines.append(f"        {{ duration: '30s', target: 0 }},")
            lines.append(f"      ],")
            lines.append(f"      exec: '{name}',")
            lines.append(f"      tags: {{ scenario: '{name}' }},")
            lines.append(f"    }},")
        lines.append("  },")
        lines.append("  thresholds: {")
        lines.append("    'http_req_duration': ['p(95)<2000'],  // 95% of requests under 2s")
        lines.append("    'http_req_failed': ['rate<0.01'],       // < 1% failure rate")
        lines.append("  },")
        lines.append("};")
        lines.append("")

        # Default function
        lines.append("export default function () {")
        lines.append("  // Default executor — runs basic smoke check")
        lines.append("  const res = http.get(`${BASE_URL}/health`);")
        lines.append("  check(res, { 'health status 200': (r) => r.status === 200 });")
        lines.append("  sleep(1);")
        lines.append("}")
        lines.append("")

        # Scenario-specific exec functions
        for i, scenario in enumerate(scenarios):
            name = ["smoke", "average", "stress"][i]
            scenario_desc = scenario.get("description", "")
            lines.append(f"// {scenario_desc}")
            lines.append(f"export function {name}() {{")
            lines.append(f"  group('{name} scenario', function () {{")
            for req in requests:
                method_lower = req["method"].lower()
                path = req["path"]
                # Replace path params with example values
                path_with_values = (
                    path.replace("{id}", "1")
                    .replace("{userId}", "42")
                    .replace("{orderId}", "100")
                    .replace("{itemId}", "5")
                )
                lines.append(f"    // {req['summary'] or req['operation_id']}")
                lines.append(f"    let res = http.{method_lower}(")
                lines.append(f"      `${{BASE_URL}}{path_with_values}`,")
                if req["has_body"]:
                    lines.append(f"      JSON.stringify({{ /* request body */ }}),")
                    lines.append(f"      {{ headers: {{ 'Content-Type': 'application/json' }} }},")
                lines.append(f"    );")
                lines.append(f"    responseTime.add(res.timings.duration);")
                lines.append(f"    errorRate.add(res.status >= 400);")
                lines.append(f"    sleep(0.5);")
                lines.append("")
            lines.append(f"  }});")
            lines.append(f"}}")
            lines.append("")

        return "\n".join(lines)
