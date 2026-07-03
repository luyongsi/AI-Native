#!/bin/bash
set -e

SERVER="root@172.27.78.109"
REMOTE_DIR="/opt/ai-native"
LOCAL_DIR="D:/Vibe Coding/AI Agent"

echo "=== Deploying AI-Native Platform to $SERVER ==="

# 1. Sync code
echo "--- Syncing code ---"
rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.venv' \
    --exclude 'venv' \
    --exclude '*.pyc' \
    --exclude '.next' \
    --exclude '.turbo' \
    "$LOCAL_DIR/repos/" "$SERVER:$REMOTE_DIR/repos/"
rsync -avz --delete \
    --exclude 'node_modules' \
    --exclude '.next' \
    "$LOCAL_DIR/frontend/" "$SERVER:$REMOTE_DIR/frontend/"

# 2. Install Python dependencies
echo "--- Installing Python dependencies ---"
ssh "$SERVER" "cd $REMOTE_DIR/repos/mc-backend && pip install -r requirements.txt"
ssh "$SERVER" "cd $REMOTE_DIR/repos/agent-workers && pip install -r requirements.txt"
ssh "$SERVER" "cd $REMOTE_DIR/repos/orchestrator && pip install -r requirements.txt"
ssh "$SERVER" "cd $REMOTE_DIR/repos/context-builder && pip install -r requirements.txt"
ssh "$SERVER" "cd $REMOTE_DIR/repos/feishu-bot && pip install -r requirements.txt"
ssh "$SERVER" "cd $REMOTE_DIR/repos/event-bus && pip install -e ."
ssh "$SERVER" "cd $REMOTE_DIR/repos/llm-provider && pip install -e ."

# 3. Start Docker Compose
echo "--- Starting infrastructure ---"
ssh "$SERVER" "cd $REMOTE_DIR/repos/infra && docker compose up -d"

# 4. Wait for PostgreSQL
echo "--- Waiting for PostgreSQL ---"
ssh "$SERVER" "until docker exec ai-postgres pg_isready -U ai_native; do sleep 2; done"

# 5. Run Alembic migrations
echo "--- Running database migrations ---"
ssh "$SERVER" "cd $REMOTE_DIR/repos/infra/alembic && alembic upgrade head"

# 6. Start backend
echo "--- Starting FastAPI backend ---"
ssh "$SERVER" "cd $REMOTE_DIR/repos/mc-backend && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/ai-native-backend.log 2>&1 &"

# 7. Build and start frontend
echo "--- Building frontend ---"
ssh "$SERVER" "cd $REMOTE_DIR/frontend && npm install && npm run build"
ssh "$SERVER" "cd $REMOTE_DIR/frontend && nohup npm start -- -p 3000 > /var/log/ai-native-frontend.log 2>&1 &"

# 8. Health check
echo "--- Health check ---"
sleep 5
ssh "$SERVER" "curl -s http://localhost:8000/health" || echo "Backend health check FAILED"
ssh "$SERVER" "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000" || echo "Frontend check FAILED"

echo "=== Deployment complete ==="
echo "Backend: http://172.27.78.109:8000"
echo "Frontend: http://172.27.78.109:3000"
