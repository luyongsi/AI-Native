# Prometheus AlertManager + Feishu Integration

This directory contains the configuration for Prometheus AlertManager with Feishu webhook integration.

## Components

### alertmanager.yml
Main AlertManager configuration file:
- Routes all alerts to Feishu webhook receiver
- Groups alerts by alertname, cluster, and service
- Configures inhibit rules (critical alerts suppress warnings)
- 5-minute resolve timeout

### alert_rules.yaml (alert-rules.yaml)
Prometheus alert rules with 15+ different alert conditions covering:
- **Agent monitoring**: Failure rate, stuck agents
- **LLM monitoring**: Call latency, throughput
- **Context Builder**: Processing duration
- **Infrastructure**: NATS, PostgreSQL, Redis, event bus
- **Pipeline**: WIP limits, throughput, test failures

Each alert includes:
- PromQL expression with time window
- Severity labels (critical/warning/info)
- Component tags for categorization
- Human-readable annotations

### prometheus.yml
Updated Prometheus configuration:
- Added alerting section pointing to AlertManager on port 9093
- Added rule_files reference to alert_rules.yml
- Added AlertManager job for self-monitoring

## Docker Setup

### docker-compose.yml
Added AlertManager service:
- Image: `prom/alertmanager:v0.26.0`
- Port: 9093
- Volumes: alertmanager.yml + persistent storage
- Network: ai-network

Prometheus service updates:
- Added alert_rules.yml volume mount
- Added dependency on alertmanager service

## Feishu Integration

### Backend Endpoint
- **Route**: `POST /api/alerts/feishu`
- **File**: `/d/Vibe Coding/AI Agent/repos/mc-backend/api/alerts.py`
- **Handler**: Receives Prometheus AlertManager webhooks and forwards to Feishu

### Features
- Severity-based color coding (red/orange/blue/green)
- Emoji indicators for alert status
- Rich message formatting with Markdown
- Quick-action buttons linking to Grafana and Prometheus
- Async HTTP client with timeout protection
- Detailed logging for debugging

### Environment Variables
```bash
FEISHU_ALERT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
GRAFANA_URL=http://172.27.78.109:3000
PROMETHEUS_URL=http://172.27.78.109:9090
```

## Setup Instructions

### 1. Configure Feishu Webhook

1. Go to your Feishu workspace
2. Create a new bot in: Settings → App Center → Create Custom App
3. Enable "Incoming Webhook" permission
4. Copy the webhook URL
5. Set `FEISHU_ALERT_WEBHOOK` environment variable

### 2. Start Services

```bash
docker-compose up -d prometheus alertmanager
```

Verify services are running:
- Prometheus: http://localhost:9090
- AlertManager: http://localhost:9093

### 3. Verify Prometheus Configuration

Visit http://localhost:9090/config and check:
- Alerting section shows AlertManager target
- Rule files loaded successfully
- Alert rules are visible

### 4. Test Alerts

Run the test script:
```bash
python infra/prometheus/test_alerts.py
```

This sends 6 test alerts to the webhook endpoint:
1. HighAgentFailureRate (warning)
2. HighLLMLatency (warning)
3. NATSConnectionDown (critical)
4. HighRedisMemory (warning)
5. PostgreSQLPoolExhausted (warning)
6. SlowContextBuilder (resolved)

Check Feishu for incoming notifications.

## Alert Rules Reference

### Critical Alerts
- **NATSConnectionDown**: NATS broker disconnected
- **LoopTripped**: Circuit breaker tripped
- **DatabaseConnectionPoolExhausted**: No agent activity with pending work

### Warning Alerts
- **HighAgentFailureRate**: Agent failure rate > 10%
- **HighLLMLatency**: P95 latency > 30s
- **PostgreSQLPoolExhausted**: Connection pool > 80%
- **HighRedisMemory**: Memory usage > 90%
- **AgentStuck**: Agent running > 30 minutes
- **GateSLAOverdue**: Gate approval overdue
- **HighWIP**: > 10 requirements in development
- **WebSocketConnectionDrop**: > 10 WS connections dropped in 5m
- **TestFailureSpike**: Test failure rate > 0.5/sec

### Info Alerts
- **SlowContextBuilder**: P95 duration > 10s
- **ZeroThroughput**: No new requirements in 1h
- **HighEventBusLatency**: Low event bus throughput

## Message Format

Feishu notification includes:
- Status emoji and alert name as title
- Color-coded header (red/orange/blue for firing, green for resolved)
- Alert description and component
- Severity level and trigger time
- Action buttons linking to monitoring dashboards

## Troubleshooting

### AlertManager not connecting to backend
- Check mc-backend is running on port 8000
- Verify FEISHU_ALERT_WEBHOOK is set
- Check AlertManager logs: `docker logs ai-alertmanager`

### Alerts not firing
- Verify alert rules syntax: `docker exec ai-prometheus promtool check rules /etc/prometheus/alert_rules.yml`
- Check evaluation interval (default 15s)
- Verify metric names match your exporters
- Lower thresholds temporarily for testing

### Feishu notifications not arriving
- Verify webhook URL is correct
- Check mc-backend logs: `docker logs ai-prometheus`
- Test endpoint: `curl -X POST http://localhost:8000/api/alerts/feishu -d @test-alert.json`
- Verify Feishu bot has webhook permission

### Query response time
- Alert evaluation adds minimal overhead (rules evaluated every 15s)
- AlertManager processing is lightweight
- Network latency to Feishu may add 100-500ms per notification

## Files Modified/Created

- `infra/prometheus/alertmanager.yml` (new)
- `infra/prometheus/alert_rules.yaml` (updated)
- `infra/prometheus/prometheus.yml` (updated)
- `infra/prometheus/test_alerts.py` (new)
- `infra/.env.example` (new)
- `infra/docker-compose.yml` (updated)
- `mc-backend/api/alerts.py` (updated)
- `mc-backend/requirements.txt` (updated)

## Acceptance Criteria Checklist

- [x] AlertManager container running (port 9093)
- [x] Prometheus loads alert rules successfully
- [x] Feishu webhook endpoint accessible
- [x] Alert triggering sends Feishu messages
- [x] Alert resolution sends recovery notifications
- [x] Message format correct (title + color + description + buttons)
- [x] 15+ alert rules defined with proper severity
- [x] Test script can trigger alerts
