#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# health-check.sh — verify all AI-Native platform services are reachable.
# Usage: ./health-check.sh
# Exit 0 when all services respond; exit 1 if any service fails.
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'   # No Color

failures=0

check() {
    local name="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo -e "${GREEN}[ OK ]${NC}  $name"
    else
        echo -e "${RED}[FAIL]${NC}  $name"
        failures=$((failures + 1))
    fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " AI-Native Platform — Health Check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# PostgreSQL — uses pg_isready (bundled with psql client)
check "PostgreSQL  (5432)"  pg_isready -U ai_native -h localhost

# NATS — monitoring endpoint on port 8222
check "NATS        (8222)"  curl -sf --max-time 5 http://localhost:8222/healthz

# Temporal — gRPC health probe (Temporal auto-setup exposes /health via gRPC gateway)
check "Temporal    (7233)"  curl -sf --max-time 5 http://localhost:7233/health

# Redis — PING command
check "Redis       (6379)"  redis-cli ping

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ "$failures" -gt 0 ]; then
    echo -e "${RED}  $failures service(s) unhealthy${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 1
else
    echo -e "${GREEN}  All services healthy${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    exit 0
fi
