# AI-Native Platform Deployment

## Prerequisites

- SSH access to target server as root (`root@172.27.78.109`)
- Docker and Docker Compose installed on server
- Python 3.10+ with pip on server
- Node.js 22+ with npm on server
- rsync installed locally (available in Git Bash on Windows)

## Quick Deploy

From the project root, run:

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

## Manual Steps

If you prefer to run each step individually:

### 1. Copy environment variables

```bash
scp deploy/.env.example root@172.27.78.109:/opt/ai-native/.env
```

Edit `/opt/ai-native/.env` on the server and replace all placeholder passwords.

### 2. Sync code

```bash
rsync -avz --delete \
    --exclude 'node_modules' --exclude '.git' --exclude '__pycache__' \
    --exclude '.venv' --exclude 'venv' --exclude '*.pyc' \
    --exclude '.next' --exclude '.turbo' \
    "D:/Vibe Coding/AI Agent/repos/" root@172.27.78.109:/opt/ai-native/repos/

rsync -avz --delete \
    --exclude 'node_modules' --exclude '.next' \
    "D:/Vibe Coding/AI Agent/frontend/" root@172.27.78.109:/opt/ai-native/frontend/
```

### 3. Install Python dependencies

```bash
ssh root@172.27.78.109 "cd /opt/ai-native/repos/mc-backend && pip install -r requirements.txt"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/agent-workers && pip install -r requirements.txt"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/orchestrator && pip install -r requirements.txt"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/context-builder && pip install -r requirements.txt"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/feishu-bot && pip install -r requirements.txt"
ssh root@172.27.78.109 "cd /opt/ai-native/repos/event-bus && pip install -e ."
ssh root@172.27.78.109 "cd /opt/ai-native/repos/llm-provider && pip install -e ."
```

### 4. Start infrastructure

```bash
ssh root@172.27.78.109 "cd /opt/ai-native/repos/infra && docker compose up -d"
```

Wait for PostgreSQL to become ready:

```bash
ssh root@172.27.78.109 "until docker exec ai-postgres pg_isready -U ai_native; do sleep 2; done"
```

### 5. Run database migrations

```bash
ssh root@172.27.78.109 "cd /opt/ai-native/repos/infra/alembic && alembic upgrade head"
```

### 6. Start backend

```bash
ssh root@172.27.78.109 "cd /opt/ai-native/repos/mc-backend && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/ai-native-backend.log 2>&1 &"
```

### 7. Build and start frontend

```bash
ssh root@172.27.78.109 "cd /opt/ai-native/frontend && npm install && npm run build"
ssh root@172.27.78.109 "cd /opt/ai-native/frontend && nohup npm start -- -p 3000 > /var/log/ai-native-frontend.log 2>&1 &"
```

### 8. Health check

```bash
ssh root@172.27.78.109 "curl -s http://localhost:8000/health"
ssh root@172.27.78.109 "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000"
```

## Access

- **Backend API:** http://172.27.78.109:8000
- **Frontend:** http://172.27.78.109:3000
- **Grafana:** http://172.27.78.109:3001 (if exposed)
- **Prometheus:** http://172.27.78.109:9090 (if exposed)

## Troubleshooting

### Backend logs

```bash
ssh root@172.27.78.109 "tail -f /var/log/ai-native-backend.log"
```

### Frontend logs

```bash
ssh root@172.27.78.109 "tail -f /var/log/ai-native-frontend.log"
```

### Docker service status

```bash
ssh root@172.27.78.109 "docker compose -f /opt/ai-native/repos/infra/docker-compose.yml ps"
```

### Restart a crashed service

```bash
ssh root@172.27.78.109 "docker compose -f /opt/ai-native/repos/infra/docker-compose.yml restart <service-name>"
```

## Rolling Back

If something goes wrong, the previous deployment can be restored if you kept a backup of `/opt/ai-native`. Otherwise, re-deploy the previous known-good commit.
