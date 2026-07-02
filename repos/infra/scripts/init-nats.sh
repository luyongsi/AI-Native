#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# init-nats.sh — bootstrap NATS JetStream stream for the AI-Native platform.
# Usage: ./init-nats.sh
# Requires the `nats` CLI (https://github.com/nats-io/natscli).
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

STREAM_NAME="AI_NATIVE_EVENTS"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Initialising NATS JetStream — ${STREAM_NAME}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if the stream already exists; update if so, create if not.
if nats stream info "${STREAM_NAME}" >/dev/null 2>&1; then
    echo "Stream '${STREAM_NAME}' already exists — updating configuration ..."
    nats stream update "${STREAM_NAME}" \
        --subjects "gate.*.*, agent.*.*, requirement.*.*, artifact.*.*, loop.*.*, test.*.*, system.*" \
        --retention limits \
        --max-msgs 1000000 \
        --max-bytes 10737418240 \
        --storage file \
        --replicas 1
else
    echo "Creating stream '${STREAM_NAME}' ..."
    nats stream add "${STREAM_NAME}" \
        --subjects "gate.*.*, agent.*.*, requirement.*.*, artifact.*.*, loop.*.*, test.*.*, system.*" \
        --retention limits \
        --max-msgs 1000000 \
        --max-bytes 10737418240 \
        --storage file \
        --replicas 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Stream '${STREAM_NAME}' ready."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
