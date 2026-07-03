# AlertManager + Feishu Quick Setup Guide

## Pre-requisites
- Docker & Docker Compose installed
- Feishu workspace with bot creation permission
- mc-backend running on port 8000

## Step 1: Create Feishu Bot

1. Open your Feishu workspace
2. Navigate to: Settings → App Center → Create Custom App
3. Fill in app details (e.g., "AlertBot")
4. Go to Permissions → Enable "Incoming Webhook"
5. Copy the webhook URL (looks like: `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx`)

## Step 2: Configure Environment

Create `.env` in the infra directory (or use existing):
```bash
FEISHU_ALERT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_HERE
```

## Step 3: Start Services

```bash
cd /d/Vibe\ Coding/AI\ Agent/repos/infra
docker-compose up -d alertmanager prometheus
```

Verify services started:
```bash
docker-compose ps | grep -E "prometheus|alertmanager"
```

## Step 4: Verify Prometheus Configuration

Visit http://localhost:9090 and check:
1. Status → Configuration (scroll to "alerting" section)
2. Status → Targets (should show alertmanager:9093)
3. Alerts menu (should list all 15+ alert rules)

## Step 5: Test Feishu Integration

```bash
cd /d/Vibe\ Coding/AI\ Agent/repos/infra/prometheus
python test_alerts.py
```

You should receive 6 test notifications in Feishu within 2-3 seconds.

## Step 6: Configure Real Alerts (Optional)

Update alert thresholds in `alert-rules.yaml` based on your metrics:
- Lower thresholds for faster triggering during testing
- Adjust `for:` duration (minimum evaluation period)
- Check metric names match your exporters

## Troubleshooting

### Can't connect to AlertManager
```bash
docker logs ai-alertmanager
docker logs ai-prometheus
```

### Alerts not showing in Prometheus
- Visit http://localhost:9090/alerts
- Check "Pending" vs "Firing" state
- Verify rule syntax: `docker exec ai-prometheus promtool check rules /etc/prometheus/alert-rules.yml`

### Feishu notifications not arriving
- Check mc-backend logs: `docker logs mc-backend`
- Verify webhook URL is correct
- Test with curl:
```bash
curl -X POST http://localhost:8000/api/alerts/feishu \
  -H "Content-Type: application/json" \
  -d '{"alerts": [{"status": "firing", "labels": {"alertname": "TestAlert", "severity": "warning", "component": "test"}, "annotations": {"summary": "Test", "description": "Test alert"}, "startsAt": "2024-01-01T00:00:00Z"}]}'
```

## Key Files

- `alertmanager.yml` - AlertManager routing config
- `alert-rules.yaml` - 15+ alert rules with PromQL expressions
- `prometheus.yml` - Prometheus config pointing to AlertManager
- `test_alerts.py` - Test script with 6 sample alerts
- `../mc-backend/api/alerts.py` - Feishu webhook handler

## Next Steps

1. Instrument your services with Prometheus metrics
2. Adjust alert thresholds based on baseline metrics
3. Add more alert rules as needed
4. Configure Grafana dashboards for visualization
5. Set up notification groups by severity in AlertManager

## Performance Impact

- Alert evaluation: ~50-100ms per rule check every 15s
- AlertManager processing: Negligible (<10ms per alert)
- Feishu webhook call: ~100-500ms per notification (network dependent)
- Overall impact: Minimal on system resources
