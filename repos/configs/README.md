# configs — 可观测性配置文件

Prometheus、Grafana 的配置和数据源定义。

## 文件说明

| 文件 | 说明 |
|---|---|
| `prometheus.yml` | Prometheus 抓取配置 (self + mc-backend) |
| `agent-overview.json` | Grafana Dashboard: Agent 总览面板 |

## 部署

这些文件在 Docker Compose 中已挂载：

- `prometheus.yml` → Prometheus 容器的 `/etc/prometheus/prometheus.yml`
- `agent-overview.json` → Grafana 容器的 `/etc/grafana/provisioning/dashboards/`

## 访问地址

- Grafana: `http://localhost:3000` (admin/admin)
- Prometheus: `http://localhost:9090`
- MC Backend Metrics: `http://localhost:8000/metrics`

## 关联 Spec

spec-32 · 可观测性全量部署
