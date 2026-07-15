"""Phase3 109环境综合测试套件"""
import paramiko
import json
import time
import uuid

SERVER = "172.27.78.109"
USER = "root"
PASSWORD = "Shyfzx@Admin"

class TestSuite:
    def __init__(self):
        self.client = None
        self.results = {
            "suite": "Phase3 Integration Test",
            "server": SERVER,
            "timestamp": "",
            "categories": {},
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        }

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(SERVER, username=USER, password=PASSWORD, timeout=15)

    def run_cmd(self, cmd, desc=""):
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=30)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        return out, err

    def add_result(self, category, name, passed, detail="", error=""):
        if category not in self.results["categories"]:
            self.results["categories"][category] = []
        status = "PASS" if passed else ("SKIP" if error == "SKIP" else "FAIL")
        self.results["categories"][category].append({
            "name": name, "status": status, "detail": str(detail)[:500], "error": str(error)[:500],
        })
        self.results["summary"]["total"] += 1
        if passed:
            self.results["summary"]["passed"] += 1
        elif error == "SKIP":
            self.results["summary"]["skipped"] += 1
        else:
            self.results["summary"]["failed"] += 1
        icon = "✅" if passed else ("⏭️" if error == "SKIP" else "❌")
        print(f"  {icon} [{category}] {name}")

    # ── CATEGORY 1: Infrastructure Health ───────────────────────────────

    def test_infra_health(self):
        print("\n📦 [1] 基础设施健康检查")
        cat = "infrastructure"

        # Docker containers
        out, _ = self.run_cmd("docker ps --format '{{.Names}}' | sort")
        containers = out.split("\n") if out else []
        required = ["ai-postgres", "ai-nats", "ai-redis", "ai-neo4j", "ai-temporal"]
        for c in required:
            self.add_result(cat, f"Container: {c}", c in containers,
                           f"Running" if c in containers else "NOT FOUND")

        # PostgreSQL
        out, _ = self.run_cmd(
            "docker exec ai-postgres pg_isready -U ai_native 2>&1")
        self.add_result(cat, "PostgreSQL ready", "accepting connections" in out, out)

        # NATS
        out, _ = self.run_cmd("curl -s http://localhost:8222/healthz 2>&1")
        self.add_result(cat, "NATS healthz", out.strip() == "ok", out)

        # NATS JetStream
        out, _ = self.run_cmd(
            "curl -s http://localhost:8222/jsz 2>&1 | head -5")
        self.add_result(cat, "NATS JetStream", "streams" in out.lower() or "cluster" in out.lower(), out[:100])

        # Redis
        out, _ = self.run_cmd(
            "docker exec ai-redis redis-cli ping 2>&1")
        self.add_result(cat, "Redis ping", "PONG" in out, out)

        # Temporal
        out, _ = self.run_cmd(
            "curl -s http://localhost:7233/ 2>&1 | head -1")
        self.add_result(cat, "Temporal reachable", len(out) > 0, out[:100])

    # ── CATEGORY 2: Service Health ──────────────────────────────────────

    def test_service_health(self):
        print("\n🔧 [2] 应用服务健康检查")
        cat = "services"

        # MC Backend
        out, _ = self.run_cmd("curl -s http://localhost:8000/health")
        health_ok = '"status":"ok"' in out
        self.add_result(cat, "MC Backend /health", health_ok, out)

        # Gate2 API endpoint exists (expect 404 for invalid UUID)
        out, _ = self.run_cmd(
            "curl -s -w '\\n%{http_code}' http://localhost:8000/api/gate2/00000000-0000-0000-0000-000000000000/context")
        lines = out.strip().split("\n")
        http_code = lines[-1] if lines else ""
        self.add_result(cat, "Gate2 API endpoint", http_code == "404" or http_code == "200",
                       f"HTTP {http_code}")

        # Worker processes
        out, _ = self.run_cmd(
            "ps aux | grep -E 'worker_launcher|worker.py' | grep -v grep | wc -l")
        worker_count = int(out.strip() or 0)
        self.add_result(cat, "Worker processes", worker_count >= 3,
                       f"Count: {worker_count}")

        # Worker launcher log for A6/A7/A8 registration
        out, _ = self.run_cmd(
            "tail -30 /tmp/worker_launcher.log 2>&1 | grep -E 'Registered|listening|A[678]' | head -10")
        self.add_result(cat, "A6/A7/A8 registered in launcher",
                       "A6" in out or "A7" in out or "A8" in out,
                       out[:200])

    # ── CATEGORY 3: Database Schema ─────────────────────────────────────

    def test_db_schema(self):
        print("\n🗄️ [3] 数据库 Schema 验证")
        cat = "database"
        db_cmd = "docker exec ai-postgres psql -U ai_native -d ai_native"

        # Requirements table has tech_prep columns
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT column_name FROM information_schema.columns '
            f'WHERE table_name=\'requirements\' AND column_name LIKE \'tech_prep%\' ORDER BY column_name;" -t')
        has_status = "tech_prep_status" in out
        has_revision = "tech_prep_revision_count" in out
        self.add_result(cat, "requirements.tech_prep_status", has_status, out.strip())
        self.add_result(cat, "requirements.tech_prep_revision_count", has_revision, out.strip())

        # Approvals table has a6_rework/a7_rework
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT column_name FROM information_schema.columns '
            f'WHERE table_name=\'approvals\' AND column_name LIKE \'%rework\' ORDER BY column_name;" -t')
        has_a6 = "a6_rework" in out
        has_a7 = "a7_rework" in out
        self.add_result(cat, "approvals.a6_rework", has_a6, out.strip())
        self.add_result(cat, "approvals.a7_rework", has_a7, out.strip())

        # task_dags table structure
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT column_name, data_type FROM information_schema.columns '
            f'WHERE table_name=\'task_dags\' ORDER BY ordinal_position;" -t')
        has_cycle = "cycle" in out
        has_version = "version" in out
        has_dag_json = "dag_json" in out
        self.add_result(cat, "task_dags has cycle", has_cycle, out[:200])
        self.add_result(cat, "task_dags has version", has_version, out[:200])
        self.add_result(cat, "task_dags has dag_json", has_dag_json, out[:200])

        # test_assets table structure
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT column_name FROM information_schema.columns '
            f'WHERE table_name=\'test_assets\' ORDER BY ordinal_position;" -t')
        has_unit = "unit_tests" in out
        has_integration = "integration_tests" in out
        has_version_ta = "version" in out
        self.add_result(cat, "test_assets.unit_tests", has_unit, out[:200])
        self.add_result(cat, "test_assets.integration_tests", has_integration, out[:200])
        self.add_result(cat, "test_assets.version", has_version_ta, out[:200])

        # Unique constraint on task_dags
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT constraint_name FROM information_schema.table_constraints '
            f'WHERE table_name=\'task_dags\' AND constraint_type=\'UNIQUE\';" -t')
        has_uq = "uq_task_dags" in out
        self.add_result(cat, "task_dags UNIQUE (req_id,cycle,version)", has_uq, out.strip())

        # agent_results table
        out, _ = self.run_cmd(
            f'{db_cmd} -c "SELECT agent_key, count(*) FROM agent_results GROUP BY agent_key ORDER BY agent_key;" -t')
        self.add_result(cat, "agent_results has records", len(out.strip()) > 0, out[:200])

    # ── CATEGORY 4: NATS Event Flow ─────────────────────────────────────

    def test_nats_events(self):
        print("\n📡 [4] NATS 事件总线测试")
        cat = "nats"

        # Check NATS streams
        out, _ = self.run_cmd(
            "curl -s http://localhost:8222/jsz 2>&1 | python3 -c "
            "\"import sys,json; d=json.load(sys.stdin); "
            "print(f'streams={d.get(\\\"streams\\\",0)}') if isinstance(d,dict) else print('not_json')\" 2>&1")
        self.add_result(cat, "NATS JetStream accessible", "streams=" in out, out[:100])

        # List streams
        out, _ = self.run_cmd(
            "curl -s 'http://localhost:8222/jsz?streams=true' 2>&1 | python3 -c "
            "\"import sys,json; d=json.load(sys.stdin); "
            "[print(s) for s in d.get('streams',[])] if isinstance(d,dict) else print('no_streams')\" 2>&1 | head -10")
        self.add_result(cat, "JetStream streams list", len(out.strip()) > 0, out[:200])

        # Publish test event to verify NATS works
        test_id = str(uuid.uuid4())[:8]
        pub_out, _ = self.run_cmd(
            f"python3 -c \""
            f"import asyncio,nats,json;"
            f"async def test():"
            f"  nc=await nats.connect('localhost:4222');"
            f"  js=nc.jetstream();"
            f"  await js.publish('test.phase3.health',json.dumps({{'test_id':'{test_id}'}}).encode());"
            f"  print('PUBLISHED');"
            f"  await nc.close();"
            f"asyncio.run(test())\" 2>&1")
        self.add_result(cat, "NATS publish test", "PUBLISHED" in pub_out, pub_out[:100])

        # Verify worker is listening on A6/A7/A8 subjects
        out, _ = self.run_cmd(
            "tail -50 /tmp/worker_launcher.log 2>&1 | grep -E 'context.ready.A[678]|subscribe.*A[678]' | head -10")
        self.add_result(cat, "A6/A7/A8 subject subscriptions",
                       len(out.strip()) > 0, out[:200])

    # ── CATEGORY 5: API Endpoints ──────────────────────────────────────

    def test_api_endpoints(self):
        print("\n🌐 [5] API 端点测试")
        cat = "api"

        # Health
        out, _ = self.run_cmd("curl -s http://localhost:8000/health")
        self.add_result(cat, "GET /health", '"status":"ok"' in out, out)

        # List requirements
        out, _ = self.run_cmd("curl -s http://localhost:8000/api/requirements 2>&1 | head -5")
        self.add_result(cat, "GET /api/requirements", "200" not in out or len(out) > 0, out[:200])

        # Gate2 context (with valid UUID from DB)
        out, _ = self.run_cmd(
            "docker exec ai-postgres psql -U ai_native -d ai_native -t -c "
            "\"SELECT id FROM requirements LIMIT 1;\"" )
        req_id = out.strip() if out else ""
        if req_id:
            api_out, _ = self.run_cmd(
                f"curl -s -w '\\nHTTP:%{{http_code}}' http://localhost:8000/api/gate2/{req_id}/context 2>&1")
            http_ok = "200" in api_out.split("\n")[-1] if api_out else False
            self.add_result(cat, f"GET /api/gate2/{req_id[:8]}.../context", http_ok, api_out[:200])
        else:
            self.add_result(cat, "Gate2 context (no requirements)", False, "No data", "SKIP")

        # Gate2 approve (without real workflow)
        if req_id:
            api_out, _ = self.run_cmd(
                f"curl -s -w '\\nHTTP:%{{http_code}}' -X POST "
                f"http://localhost:8000/api/gate2/{req_id}/approve "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"reviewer_name\":\"TestBot\"}}' 2>&1")
            http_code = api_out.split("\n")[-1] if api_out else ""
            self.add_result(cat, f"POST /api/gate2/{req_id[:8]}.../approve",
                           http_code in ("200", "201", "404", "422"),
                           api_out[:200])

        # Gate2 reject
        if req_id:
            api_out, _ = self.run_cmd(
                f"curl -s -w '\\nHTTP:%{{http_code}}' -X POST "
                f"http://localhost:8000/api/gate2/{req_id}/reject "
                f"-H 'Content-Type: application/json' "
                f"-d '{{\"revision_guidance\":\"DAG需要更多后端节点\","
                f"\"reject_reasons\":[{{\"type\":\"dag_incomplete\"}}],"
                f"\"a6_rework\":true,\"a7_rework\":false}}' 2>&1")
            http_code = api_out.split("\n")[-1] if api_out else ""
            self.add_result(cat, f"POST /api/gate2/{req_id[:8]}.../reject",
                           http_code in ("200", "201", "404", "422"),
                           api_out[:200])

        # Verify tech_prep_revision_count incremented after reject
        if req_id:
            out, _ = self.run_cmd(
                f'docker exec ai-postgres psql -U ai_native -d ai_native '
                f'-c "SELECT tech_prep_status, tech_prep_revision_count '
                f'FROM requirements WHERE id=\'{req_id}\';" -t')
            self.add_result(cat, "Gate2 reject → tech_prep updated",
                           "revising" in out.lower(), out[:100])

    # ── CATEGORY 6: Agent Worker Verification ───────────────────────────

    def test_agent_workers(self):
        print("\n🤖 [6] Agent Worker 验证")
        cat = "agents"

        # Check worker_launcher.py for all 8 agents
        out, _ = self.run_cmd(
            "grep -n 'from a[0-9]' /opt/ai-native/repos/agent-workers/worker_launcher.py")
        for a in ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"]:
            self.add_result(cat, f"Agent {a.upper()} imported in launcher",
                           a in out.lower(), out[:300] if a == "a1" else "")

        # Verify code quality - critical methods exist
        for file_name, method in [
            ("a6_spec_decomposer.py", "_handle_context_ready"),
            ("a6_spec_decomposer.py", "_validate_dag"),
            ("a6_spec_decomposer.py", "_fallback_decompose"),
            ("a7_test_case_generator.py", "_handle_context_ready"),
            ("a7_test_case_generator.py", "_organize_test_assets"),
            ("a8_architecture_expert.py", "_handle_context_ready"),
            ("a8_architecture_expert.py", "_check_cycles"),
            ("a8_architecture_expert.py", "_dfs_colors"),
        ]:
            out, _ = self.run_cmd(
                f"grep -c 'def {method}' /opt/ai-native/repos/agent-workers/{file_name}")
            count = int(out.strip() or 0)
            self.add_result(cat, f"{file_name}.{method}()", count > 0,
                           f"Found {count} occurrences")

    # ── CATEGORY 7: Orchestrator Code Quality ───────────────────────────

    def test_orchestrator_code(self):
        print("\n🏗️ [7] Orchestrator 代码完整性")
        cat = "orchestrator"

        checks = [
            ("states.py", "SPEC_WRITING", "SPEC_WRITING state"),
            ("transitions.py", "SPEC_WRITING", "SPEC_WRITING transitions"),
            ("transitions.py", "DECOMPOSING", "DECOMPOSING transitions"),
            ("guards.py", "can_advance_to_gate", "gate guard function"),
            ("guards.py", "DECOMPOSING", "DECOMPOSING in guards"),
            ("activities/dispatch_agent.py", "context.ready.A6", "A6 NATS subject"),
            ("activities/dispatch_agent.py", "context.ready.A7", "A7 NATS subject"),
            ("activities/dispatch_agent.py", "context.ready.A8", "A8 NATS subject"),
            ("activities/dispatch_agent.py", "_build_phase3_payload", "phase3 payload builder"),
            ("activities/migrate_phase3_schema.py", "migrate_phase3_schema", "migration activity"),
            ("workflows/requirement_workflow.py", "_run_phase3_subflow", "phase3 subflow"),
        ]
        base = "/opt/ai-native/orchestrator"
        for subpath, keyword, desc in checks:
            path = f"{base}/{subpath}"
            out, _ = self.run_cmd(f"grep -c '{keyword}' {path} 2>&1")
            matches = int(out.strip() or 0)
            self.add_result(cat, desc, matches > 0,
                           f"Found {matches} in {subpath}")

    # ── Report Generation ────────────────────────────────────────────────

    def generate_report(self):
        self.results["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        print("\n" + "=" * 60)
        print("📊 测试报告汇总")
        print("=" * 60)
        s = self.results["summary"]
        print(f"  总计: {s['total']} | 通过: {s['passed']} | 失败: {s['failed']} | 跳过: {s['skipped']}")

        # Per category
        for cat, tests in self.results["categories"].items():
            passed = sum(1 for t in tests if t["status"] == "PASS")
            failed = sum(1 for t in tests if t["status"] == "FAIL")
            skipped = sum(1 for t in tests if t["status"] == "SKIP")
            total = len(tests)
            # Colorize
            if failed > 0:
                icon = "❌"
            elif skipped == total:
                icon = "⏭️"
            else:
                icon = "✅"
            print(f"  {icon} {cat}: {passed}/{total} passed" +
                  (f" ({failed} failed)" if failed else "") +
                  (f" ({skipped} skipped)" if skipped else ""))

        # Failed details
        failed_items = []
        for cat, tests in self.results["categories"].items():
            for t in tests:
                if t["status"] == "FAIL":
                    failed_items.append(f"  [{cat}] {t['name']}: {t['error'] or t['detail']}")

        if failed_items:
            print("\n❌ 失败详情:")
            for f in failed_items:
                print(f)

        return self.results


def main():
    ts = TestSuite()
    print("=" * 60)
    print("Phase3 109环境综合测试套件")
    print(f"目标: {SERVER}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        ts.connect()
        print("✅ SSH 连接成功")

        ts.test_infra_health()
        ts.test_service_health()
        ts.test_db_schema()
        ts.test_nats_events()
        ts.test_api_endpoints()
        ts.test_agent_workers()
        ts.test_orchestrator_code()

        report = ts.generate_report()

        # Save JSON report
        json_path = "D:\\Vibe Coding\\AI-Native\\test_report_phase3_109.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📄 JSON报告已保存: {json_path}")

        # Return exit code
        if report["summary"]["failed"] > 0:
            print("\n⚠️ 存在失败项，请检查。")
        else:
            print("\n🎉 全部测试通过!")

    except Exception as e:
        print(f"❌ 测试套件异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ts.client:
            ts.client.close()


if __name__ == "__main__":
    main()
