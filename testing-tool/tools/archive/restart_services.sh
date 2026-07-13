#!/bin/bash
set -e

echo "=== 1. Stop all systemd services ==="
systemctl stop ai-native-agents 2>/dev/null || true
systemctl stop ai-native-orchestrator 2>/dev/null || true
systemctl stop ai-native-backend 2>/dev/null || true

echo "=== 2. Kill all python3 ==="
killall -9 python3 2>/dev/null || true
sleep 3

echo "=== 3. Verify clean ==="
ps aux | grep python | grep -v grep | grep -v unattended || echo "ALL CLEAN"

echo "=== 4. Reset NATS stream ==="
python3 -c "
import asyncio, nats
async def p():
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    try:
        await js.delete_stream('AI_NATIVE_EVENTS')
    except:
        pass
    await js.add_stream(
        name='AI_NATIVE_EVENTS',
        subjects=['context.ready.>', 'agent.result.>', 'agent.status.changed.>', 'orchestrator.>'],
        retention='interest',
        storage='file',
    )
    print('NATS stream recreated OK')
    await nc.close()
asyncio.run(p())
"

echo "=== 5. Deploy updated files ==="
# context_build.py already deployed via scp earlier

echo "=== 6. Start services fresh ==="
systemctl start ai-native-backend
sleep 2
systemctl start ai-native-agents
sleep 3
systemctl start ai-native-orchestrator
sleep 3

echo "=== 7. Verify all running ==="
ps aux | grep python | grep -v grep | grep -v unattended

echo "=== DONE ==="
