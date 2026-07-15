"""Phase3 部署修复脚本 — 上传缺失文件到 109 服务器并重启服务"""
import paramiko
import os
import time
import json

SERVER = "172.27.78.109"
USER = "root"
PASSWORD = "Shyfzx@Admin"
BASE_LOCAL = r"D:\Vibe Coding\AI-Native"
BASE_REMOTE = "/opt/ai-native"

# 需要上传的文件映射 (本地路径 -> 远程路径)
FILES_TO_UPLOAD = {
    "repos/orchestrator/workflows/requirement_workflow.py":
        "orchestrator/workflows/requirement_workflow.py",
    "repos/orchestrator/state_machine/states.py":
        "orchestrator/state_machine/states.py",
    "repos/orchestrator/state_machine/transitions.py":
        "orchestrator/state_machine/transitions.py",
    "repos/orchestrator/state_machine/guards.py":
        "orchestrator/state_machine/guards.py",
    "repos/orchestrator/activities/dispatch_agent.py":
        "orchestrator/activities/dispatch_agent.py",
    "repos/orchestrator/activities/migrate_phase3_schema.py":
        "orchestrator/activities/migrate_phase3_schema.py",
    "repos/mc-backend/api/gate2.py":
        "mc-backend/api/gate2.py",
    "repos/mc-backend/main.py":
        "mc-backend/main.py",
}


def connect():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(SERVER, username=USER, password=PASSWORD, timeout=15)
    return client


def upload_file(client, local_rel, remote_rel):
    """Upload a single file via SFTP"""
    local_path = os.path.join(BASE_LOCAL, local_rel)
    # Use forward slashes for remote paths (Linux target)
    remote_path = BASE_REMOTE + "/" + remote_rel.replace("\\", "/")

    if not os.path.exists(local_path):
        print(f"  ❌ 本地文件不存在: {local_path}")
        return False

    local_size = os.path.getsize(local_path)
    sftp = client.open_sftp()

    try:
        # Ensure remote directory exists
        remote_dir = "/".join(remote_path.split("/")[:-1])
        print(f"  📁 目标: {remote_path}")
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            print(f"  📁 创建目录: {remote_dir}")
            stdin, stdout, stderr = client.exec_command(f"mkdir -p {remote_dir}")
            stdout.read()
            err_output = stderr.read().decode().strip()
            if err_output:
                print(f"  ⚠️ mkdir stderr: {err_output}")

        # Backup remote file if exists
        try:
            sftp.stat(remote_path)
            backup_path = remote_path + f".bak.{int(time.time())}"
            sftp.rename(remote_path, backup_path)
            print(f"  📦 已备份: {remote_rel} → {os.path.basename(backup_path)}")
        except FileNotFoundError:
            pass

        sftp.put(local_path, remote_path)
        remote_size = sftp.stat(remote_path).st_size
        success = remote_size == local_size
        if success:
            print(f"  ✅ {remote_rel} ({local_size} bytes)")
        else:
            print(f"  ⚠️ {remote_rel} 大小不匹配: local={local_size} remote={remote_size}")
        return success
    finally:
        sftp.close()


def run_remote(client, cmd, desc=""):
    """Run a command on remote server and return output"""
    if desc:
        print(f"  🔧 {desc}...")
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if err:
        print(f"  ⚠️ stderr: {err[:200]}")
    return out


def main():
    print("=" * 60)
    print("Phase3 部署修复脚本")
    print(f"目标: {USER}@{SERVER}")
    print("=" * 60)

    client = connect()
    print("✅ SSH 连接成功\n")

    # Step 1: Upload files
    print("📤 Step 1: 上传文件...")
    success_count = 0
    for local_rel, remote_rel in FILES_TO_UPLOAD.items():
        ok = upload_file(client, local_rel, remote_rel)
        if ok:
            success_count += 1
    print(f"\n  上传完成: {success_count}/{len(FILES_TO_UPLOAD)} 成功\n")

    if success_count == 0:
        print("❌ 没有文件上传成功，终止。")
        client.close()
        return

    # Step 2: Verify critical files
    print("📋 Step 2: 验证关键内容...")
    checks = {
        "SPEC_WRITING in states.py":
            'grep -c "SPEC_WRITING" /opt/ai-native/orchestrator/state_machine/states.py',
        "Phase3 in workflow":
            'grep -c "_run_phase3_subflow" /opt/ai-native/orchestrator/workflows/requirement_workflow.py',
        "A6 in dispatch":
            'grep -c "context.ready.A6" /opt/ai-native/orchestrator/activities/dispatch_agent.py',
        "gate2.py exists":
            'test -f /opt/ai-native/mc-backend/api/gate2.py && echo "1" || echo "0"',
        "gate2 in main.py":
            'grep -c "gate2_router" /opt/ai-native/mc-backend/main.py',
    }
    all_pass = True
    for name, cmd in checks.items():
        result = run_remote(client, cmd)
        ok = result.strip() not in ("", "0")
        print(f"  {'✅' if ok else '❌'} {name}: {result.strip()}")
        if not ok:
            all_pass = False

    if not all_pass:
        print("\n⚠️ 部分验证未通过，但继续重启流程...")

    # Step 3: Restart services
    print("\n🔄 Step 3: 重启服务...")

    # Kill existing processes
    print("  🛑 停止现有进程...")
    run_remote(client,
        "pkill -f 'python3 worker_launcher.py' 2>/dev/null; "
        "pkill -f 'python3 worker.py' 2>/dev/null; "
        "pkill -f 'uvicorn main:app' 2>/dev/null; "
        "sleep 3",
        "停止旧进程")

    # Verify processes stopped
    time.sleep(2)
    remaining = run_remote(client,
        "ps aux | grep -E 'worker_launcher|uvicorn main' | grep -v grep | wc -l")
    print(f"  剩余进程数: {remaining.strip()}")

    # Start MC Backend
    print("  🚀 启动 MC Backend...")
    run_remote(client,
        "cd /opt/ai-native/mc-backend && "
        "nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 "
        "> /tmp/mc-backend.log 2>&1 &",
        "启动 MC Backend")
    time.sleep(3)

    # Start worker launcher
    print("  🚀 启动 Worker Launcher...")
    run_remote(client,
        "cd /opt/ai-native/repos/agent-workers && "
        "nohup python3 worker_launcher.py > /tmp/worker_launcher.log 2>&1 &",
        "启动 Worker Launcher")
    time.sleep(5)

    # Step 4: Verify services
    print("\n✅ Step 4: 验证服务...")

    # Backend health
    health = run_remote(client, "curl -s http://localhost:8000/health")
    print(f"  Backend: {health}")

    # Gate2 API
    gate2_api = run_remote(client,
        "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/gate2/test/context 2>&1")
    print(f"  Gate2 API (expect 404 for test id): {gate2_api}")

    # Agent workers
    workers = run_remote(client,
        "ps aux | grep -E 'worker_launcher|worker.py' | grep -v grep | wc -l")
    print(f"  Worker processes: {workers.strip()}")

    # Check worker_launcher output for A6/A7/A8
    launcher_log = run_remote(client,
        "tail -20 /tmp/worker_launcher.log 2>&1 | grep -E 'A[678]|registered|listening' | head -10")
    if launcher_log:
        print(f"  Launcher log:\n    {launcher_log}")

    # NATS check
    nats_check = run_remote(client,
        "curl -s http://localhost:8222/healthz 2>&1")
    print(f"  NATS health: {nats_check}")

    print("\n" + "=" * 60)
    print("部署修复完成!")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
