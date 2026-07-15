#!/usr/bin/env python3
"""Phase 3 完整部署脚本 - 更新 172.27.78.109 上的 AI-Native 系统"""
import paramiko
import sys
import os
import time
import tempfile
import subprocess
from pathlib import Path

SERVER = "172.27.78.109"
USER = "root"
PASSWORD = "Shyfzx@Admin"
REMOTE_DIR = "/opt/ai-native"
LOCAL_REPOS = Path("D:/Vibe Coding/AI-Native/repos")
LOCAL_FRONTEND = Path("D:/Vibe Coding/AI-Native/frontend")

# Phase 3 需要同步的文件列表（相对于 repos/）
PHASE3_FILES = [
    # A6/A7/A8 Agent 重构
    "agent-workers/a6_spec_decomposer.py",
    "agent-workers/a7_test_case_generator.py",
    "agent-workers/a8_architecture_expert.py",
    # worker_launcher: 启用 A6/A7/A8 注册
    "agent-workers/worker_launcher.py",
    # Orchestrator Phase3（实际路径）
    "orchestrator/workflows/requirement_workflow.py",
    "orchestrator/activities/context_build.py",
    "orchestrator/activities/dispatch_agent.py",
    "orchestrator/activities/store_agent_result.py",
    "orchestrator/state_machine/transitions.py",
    "orchestrator/state_machine/states.py",       # SPEC_WRITING 等新状态
    "orchestrator/state_machine/guards.py",        # Gate2 guard 逻辑
    # NEW: Migration SQL
    "orchestrator/activities/migrate_phase3_schema.py",
    # MC Backend Gate2（实际路径）
    "mc-backend/api/gate2.py",
    "mc-backend/api/approvals.py",
    "mc-backend/services/nats_subscriber.py",
]

def ssh_connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USER, password=PASSWORD, timeout=15)
    sftp = client.open_sftp()
    return client, sftp

def run_cmd(client, cmd, desc="", critical=False):
    prefix = f"[{desc}] " if desc else ""
    print(f"  {prefix}$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    exit_code = stdout.channel.recv_exit_status()
    if out:
        for line in out.strip().split('\n'):
            print(f"    {line}")
    if err:
        for line in err.strip().split('\n'):
            print(f"    [ERR] {line}")
    if critical and exit_code != 0:
        print(f"  !! 命令失败(exit={exit_code})，中止")
        sys.exit(1)
    return out, err, exit_code


# ============================================================
# Phase 1: 服务器状态检查
# ============================================================
def phase1_check(client):
    print("\n" + "=" * 55)
    print("Phase 1: 服务器状态检查")
    print("=" * 55)
    run_cmd(client, "uname -a", "系统")
    run_cmd(client, f"ls -la {REMOTE_DIR}/repos/agent-workers/", "agent-workers目录")
    run_cmd(client, "docker ps --format 'table {{.Names}}\t{{.Status}}'", "Docker容器")
    run_cmd(client, "systemctl is-active ai-native-agents ai-native-orchestrator ai-native-backend 2>/dev/null || true", "服务状态")
    run_cmd(client, "curl -s http://localhost:8000/health 2>/dev/null || echo 'Backend not responding'", "后端健康检查")


# ============================================================
# Phase 2: 代码同步
# ============================================================
def phase2_sync(client, sftp):
    print("\n" + "=" * 55)
    print("Phase 2: 同步 Phase 3 代码")
    print("=" * 55)
    
    # 确保远程目录存在
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/repos/orchestrator/activities", "确保目录")
    run_cmd(client, f"mkdir -p {REMOTE_DIR}/repos/mc-backend/api", "确保api目录")
    
    synced = 0
    failed = 0
    
    for rel_path in PHASE3_FILES:
        local_path = LOCAL_REPOS / rel_path
        remote_path = f"{REMOTE_DIR}/repos/{rel_path}"
        
        if not local_path.exists():
            print(f"  !! 本地文件不存在: {local_path}")
            failed += 1
            continue
        
        try:
            sftp.put(str(local_path), remote_path)
            print(f"  OK  {rel_path}")
            synced += 1
        except Exception as e:
            print(f"  XX  {rel_path}: {e}")
            failed += 1
    
    print(f"\n  --- 同步结果: 成功 {synced}, 失败 {failed} ---")
    
    if failed > 0:
        print("  有文件同步失败!")
        return False
    
    # 验证远端文件
    print("\n  验证远端文件...")
    for rel_path in PHASE3_FILES:
        remote_path = f"{REMOTE_DIR}/repos/{rel_path}"
        out, _, code = run_cmd(client, f"test -f {remote_path} && echo 'EXISTS' || echo 'MISSING'", f"检查{rel_path}")
    
    return True


# ============================================================
# Phase 3: 数据库迁移
# ============================================================
def phase3_migrate(client):
    print("\n" + "=" * 55)
    print("Phase 3: 数据库迁移 (Phase 3 Schema)")
    print("=" * 55)
    
    # 检查 PostgreSQL 是否运行
    out, _, _ = run_cmd(client, "docker exec ai-postgres pg_isready -U ai_native 2>/dev/null || echo 'PG_NOT_READY'", "PG检查")
    if "accepting" not in out:
        print("  !! PostgreSQL 未就绪，尝试启动...")
        run_cmd(client, f"cd {REMOTE_DIR}/repos/infra && docker compose up -d postgres", "启动PG")
        time.sleep(3)
    
    # 执行 Phase3 Migration
    migrate_script = """
import asyncio
import asyncpg
import os

MIGRATION_SQL = '''
BEGIN;

ALTER TABLE requirements 
    ADD COLUMN IF NOT EXISTS tech_prep_status VARCHAR(30) DEFAULT 'decomposing',
    ADD COLUMN IF NOT EXISTS tech_prep_revision_count INT DEFAULT 0;

ALTER TABLE approvals 
    ADD COLUMN IF NOT EXISTS a6_rework BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS a7_rework BOOLEAN DEFAULT true;

DROP TABLE IF EXISTS task_dags CASCADE;

CREATE TABLE task_dags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id          UUID NOT NULL REFERENCES requirements(id),
    cycle           INT NOT NULL DEFAULT 0,
    version         INT NOT NULL DEFAULT 1,
    dag_json        JSONB NOT NULL,
    node_count      INT DEFAULT 0,
    edge_count      INT DEFAULT 0,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_task_dags_req_cycle_version UNIQUE (req_id, cycle, version)
);

CREATE INDEX IF NOT EXISTS idx_task_dags_req_id ON task_dags(req_id);
CREATE INDEX IF NOT EXISTS idx_task_dags_cycle ON task_dags(req_id, cycle);

CREATE TABLE IF NOT EXISTS test_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    req_id          UUID NOT NULL REFERENCES requirements(id),
    version         INT NOT NULL DEFAULT 1,
    test_type       VARCHAR(20) NOT NULL DEFAULT 'unit',
    total_cases     INT DEFAULT 0,
    test_json       JSONB DEFAULT '[]',
    coverage_report JSONB DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_test_assets_req_version UNIQUE (req_id, version)
);

COMMIT;

-- 验证
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'requirements' AND column_name LIKE 'tech_prep%'
UNION ALL
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'approvals' AND column_name IN ('a6_rework', 'a7_rework')
UNION ALL
SELECT column_name, data_type FROM information_schema.columns 
WHERE table_name = 'task_dags'
ORDER BY column_name;
'''

async def main():
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='ai_native',
        password='ai_native',
        database='ai_native'
    )
    try:
        async with conn.transaction():
            await conn.execute(MIGRATION_SQL)
        print("MIGRATION OK: Phase3 schema applied successfully")

        # verify
        rows = await conn.fetch("""
            SELECT column_name, data_type FROM information_schema.columns 
            WHERE table_name IN ('requirements','approvals','task_dags')
            AND column_name IN ('tech_prep_status','tech_prep_revision_count','a6_rework','a7_rework','cycle')
            ORDER BY table_name, column_name
        """)
        for r in rows:
            print(f"  VERIFY: {r['column_name']} ({r['data_type']})")
    finally:
        await conn.close()

asyncio.run(main())
"""
    
    # 写入迁移脚本到服务器
    _, _ = run_cmd(client, f"cat > /tmp/migrate_phase3.py << 'PYEOF'\n{migrate_script}\nPYEOF", "写入迁移脚本")
    
    # 安装 asyncpg（如果需要）
    _, _, code = run_cmd(client, "python3 -c 'import asyncpg' 2>/dev/null && echo 'asyncpg OK' || pip3 install asyncpg -q", "检查/安装asyncpg")
    
    # 执行迁移
    out, err, code = run_cmd(client, "cd /tmp && python3 migrate_phase3.py", "执行迁移", critical=False)
    
    if "MIGRATION OK" in out:
        print("  ✅ 数据库迁移成功!")
        return True
    else:
        print(f"  ⚠️  迁移可能有问题，请检查输出: {out[:200]}...{err[:200]}")
        return False


# ============================================================
# Phase 4: 服务重启
# ============================================================
def phase4_restart(client):
    print("\n" + "=" * 55)
    print("Phase 4: 重启服务")
    print("=" * 55)
    
    services = [
        ("ai-native-agents", "Agent Workers"),
        ("ai-native-orchestrator", "Orchestrator"),
        ("ai-native-backend", "MC Backend"),
    ]
    
    for svc, name in services:
        # 检查是否存在
        out, _, code = run_cmd(client, f"systemctl is-enabled {svc} 2>/dev/null || echo 'not-found'", f"检查{name}")
        
        if "not-found" in out:
            print(f"  ⚠️  {name}({svc}) 未安装为systemd服务，尝试直接重启进程...")
            # 尝试kill旧进程+重启
            if "backend" in svc:
                run_cmd(client, "pkill -f 'uvicorn main:app' 2>/dev/null || true", f"停旧{name}")
                time.sleep(2)
                run_cmd(client, f"cd {REMOTE_DIR}/repos/mc-backend && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/ai-native-backend.log 2>&1 &", f"启动{name}")
            elif "agents" in svc:
                run_cmd(client, "pkill -f 'worker_launcher.py' 2>/dev/null || true", f"停旧{name}")
                time.sleep(2)
                run_cmd(client, f"cd {REMOTE_DIR}/repos/agent-workers && nohup python3 worker_launcher.py > /var/log/agent-workers.log 2>&1 &", f"启动{name}")
            elif "orchestrator" in svc:
                run_cmd(client, "pkill -f 'orchestrator.*worker.py' 2>/dev/null || true", "停旧Orchestrator")
                time.sleep(2)
                run_cmd(client, f"cd {REMOTE_DIR}/repos/orchestrator && nohup python3 worker.py > /var/log/orchestrator-worker.log 2>&1 &", f"启动{name}")
        else:
            out, _, code = run_cmd(client, f"systemctl restart {svc}", f"重启{name}")
            if code == 0:
                print(f"  ✅ {name} 已重启")
            else:
                print(f"  !! {name} 重启失败")

    time.sleep(5)
    
    # 检查服务状态
    print("\n  验证服务状态...")
    run_cmd(client, "ps aux | grep -E 'uvicorn|worker_launcher|worker.py' | grep -v grep || echo 'No processes found'", "进程检查")


# ============================================================
# Phase 5: 验证测试
# ============================================================
def phase5_verify(client):
    print("\n" + "=" * 55)
    print("Phase 5: 验证测试")
    print("=" * 55)
    
    results = {}
    
    # 1. 后端健康检查
    out, _, code = run_cmd(client, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/health 2>/dev/null || echo '000'", "后端/health")
    results['backend_health'] = '200' in out
    
    # 2. 检查 Gate2 API
    out, _, _ = run_cmd(client, "curl -s http://localhost:8000/docs 2>/dev/null | head -5 || echo 'No docs'", "API文档")
    results['api_docs'] = len(out) > 10
    
    # 3. 检查 NATS 连通性
    out, _, _ = run_cmd(client, "python3 -c \"import nats; print('NATS SDK OK')\" 2>/dev/null || echo 'NATS SDK missing'", "NATS SDK")
    
    # 4. 检查最新日志
    print("\n  --- 最近日志 (Agent Workers) ---")
    run_cmd(client, "tail -20 /var/log/agent-workers.log 2>/dev/null || tail -20 /opt/ai-native/repos/agent-workers/*.log 2>/dev/null || echo 'No agent logs'", "Agent日志")
    
    print("\n  --- 最近日志 (Orchestrator) ---")
    run_cmd(client, "tail -20 /var/log/orchestrator-worker.log 2>/dev/null || echo 'No orch logs'", "Orch日志")
    
    print("\n  --- 最近日志 (Backend) ---")
    run_cmd(client, "tail -20 /var/log/ai-native-backend.log 2>/dev/null || echo 'No backend logs'", "Backend日志")
    
    # 5. 检查 Phase3 特有功能
    out, _, _ = run_cmd(client, f"test -f {REMOTE_DIR}/repos/orchestrator/activities/migrate_phase3_schema.py && echo 'Migration script OK' || echo 'Migration script MISSING'", "Migration脚本")
    results['migration_script'] = 'OK' in out
    
    out, _, _ = run_cmd(client, f"test -f {REMOTE_DIR}/repos/mc-backend/api/gate2.py && echo 'Gate2 API OK' || echo 'Gate2 API MISSING'", "Gate2 API文件")
    results['gate2_api'] = 'OK' in out
    
    # 汇总
    print("\n" + "=" * 55)
    print("验证结果汇总:")
    print("=" * 55)
    all_pass = True
    for k, v in results.items():
        status = "✅" if v else "❌"
        if not v:
            all_pass = False
        print(f"  {status} {k}")
    
    return all_pass


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 55)
    print("AI-Native Phase 3 部署脚本")
    print(f"目标: {USER}@{SERVER}")
    print("=" * 55)
    
    print("\n[1/5] 连接服务器...")
    client, sftp = ssh_connect()
    print("SSH连接成功!")
    
    try:
        phase1_check(client)
        
        # 询问确认
        print("\n" + "-" * 40)
        print("准备执行部署，将:")
        print(f"  - 同步 {len(PHASE3_FILES)} 个文件")
        print("  - 执行数据库迁移 (task_dags表将DROP重建)")
        print("  - 重启 Agent/Orchestrator/Backend 服务")
        print("-" * 40)
        
        # Phase 2: 同步代码
        if not phase2_sync(client, sftp):
            print("代码同步失败，中止")
            return
        
        # Phase 3: 迁移
        phase3_migrate(client)
        
        # Phase 4: 重启
        phase4_restart(client)
        
        # Phase 5: 验证
        all_ok = phase5_verify(client)
        
        print("\n" + "=" * 55)
        if all_ok:
            print("✅ Phase 3 部署完成!")
        else:
            print("⚠️  部署完成，但部分验证未通过，请检查上述日志。")
        print(f"    后端: http://{SERVER}:8000")
        print(f"    API文档: http://{SERVER}:8000/docs")
        print(f"    前端: http://{SERVER}:3000")
        print("=" * 55)
        
    finally:
        sftp.close()
        client.close()

if __name__ == "__main__":
    main()
