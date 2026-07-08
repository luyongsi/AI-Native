"""CLI entry point for the testing tool."""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cli")


async def cmd_run(args):
    """Run a full pipeline test from CLI."""
    from checks.infra import run_all_checks
    from observer import PipelineObserver
    from preflight import PreFlightValidator
    from utils.db import get_pool, close_pool
    from utils.mc_client import create_requirement, trigger_workflow
    from utils.temporal_client import connect_temporal

    # Load configs
    spec = yaml.safe_load((_THIS_DIR / "truth-spec.yaml").read_text(encoding="utf-8"))
    infra = yaml.safe_load((_THIS_DIR / "infra-baseline.yaml").read_text(encoding="utf-8"))

    # Pre-flight
    print("--- Pre-flight ---")
    pf = PreFlightValidator(infra.get("nats", {}).get("url", "nats://localhost:4222"))
    pf_result = await pf.validate()
    print(json.dumps(pf_result, indent=2, ensure_ascii=False))
    if not pf_result.get("ready"):
        print("Pre-flight failed, aborting.")
        return

    # Infra checks
    print("\n--- Infrastructure ---")
    infra_result = await run_all_checks(infra)
    for name, result in infra_result.items():
        status = "PASS" if result.get("passed") else "FAIL"
        print(f"  [{status}] {name}: {result.get('error', result.get('message', ''))}")

    # Create + trigger
    print("\n--- Creating requirement ---")
    result = await create_requirement(args.title, args.desc or "")
    if not result:
        print("Failed to create requirement")
        return
    req_id = result.get("id", "")
    print(f"  req_id: {req_id}")

    wf_id = await trigger_workflow(req_id)
    if not wf_id:
        print("Failed to trigger workflow")
        return
    print(f"  workflow_id: {wf_id}")

    # Observer
    print("\n--- Observing pipeline ---")
    db_pool = await get_pool()
    temporal = await connect_temporal()

    async def event_cb(event: str, data: dict):
        if event == "finding":
            sev = data.get("severity", "info")
            icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(sev, "?")
            print(f"  {icon} [{sev.upper()}] {data.get('rule', '?')}: {data.get('message', '')[:120]}")
        elif event == "state-change":
            print(f"  State: {data.get('from')} -> {data.get('to')}")
        elif event == "gate-approved":
            print(f"  Gate {data.get('gate')} approved")
        elif event == "run-complete":
            print(f"\n  Final: {data.get('final_state')}")
            print(f"  Duration: {data.get('total_duration_s', 0):.1f}s")
            print(f"  Findings: {data.get('findings_count', 0)}")

    observer = PipelineObserver(
        req_id=req_id,
        workflow_id=wf_id,
        gate_strategy=args.gate,
        truth_spec=spec,
        db_pool=db_pool,
        temporal_client=temporal,
        keep_data=args.keep_data,
        event_callback=event_cb,
    )

    result = await observer.run()
    print(f"\n--- Done: {result['final_state']} ---")

    # Export if requested
    if args.export:
        export_path = Path(args.export)
        export_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str),
                               encoding="utf-8")
        print(f"Exported to {export_path}")

    await close_pool()


async def cmd_diagnose(args):
    """Diagnose an existing req_id (snapshot only, no agents triggered)."""
    from checks.runtime_verifier import RuntimeVerifier
    from utils.db import get_pool, close_pool, fetch_requirement

    spec = yaml.safe_load((_THIS_DIR / "truth-spec.yaml").read_text(encoding="utf-8"))
    db_pool = await get_pool()

    req = await fetch_requirement(args.req_id)
    if not req:
        print(f"Requirement {args.req_id} not found")
        await close_pool()
        return

    print(f"Diagnosing: {req['title']} (status={req['status']})")
    print(f"  external_id: {req['external_id']}")
    print(f"  created: {req['created_at']}")
    print(f"  updated: {req['updated_at']}")

    spec_data = req.get("spec", {})
    print(f"\n  spec keys: {list(spec_data.keys())}")
    print(f"  spec.openapi: {'present' if spec_data.get('openapi') else 'empty'}")
    print(f"  spec.erd: {'present' if spec_data.get('erd') else 'empty'}")
    artifacts = spec_data.get("artifacts", {})
    print(f"  spec.artifacts agents: {list(artifacts.keys())}")

    verifier = RuntimeVerifier(spec, db_pool)
    findings = []
    for agent_id in artifacts:
        f = await verifier.check_persistence_contracts(agent_id, args.req_id)
        findings.extend(f)
    findings.extend(verifier.check_worktree_cleanup_sync())

    if findings:
        print(f"\n  Findings ({len(findings)}):")
        for f in findings:
            sev = f.get("severity", "info")
            icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(sev, "?")
            print(f"    {icon} [{sev}] {f.get('rule')}: {f.get('message')[:150]}")
    else:
        print("\n  No issues found.")

    await close_pool()


async def cmd_infra(args):
    """Run infrastructure checks only."""
    from checks.infra import run_all_checks
    infra = yaml.safe_load((_THIS_DIR / "infra-baseline.yaml").read_text(encoding="utf-8"))
    results = await run_all_checks(infra)
    for name, result in results.items():
        status = "PASS" if result.get("passed") else "FAIL"
        print(f"[{status}] {name}: {json.dumps(result, ensure_ascii=False, default=str)[:200]}")


async def cmd_validate_spec(args):
    """Validate truth-spec.yaml self-consistency."""
    from checks.truth_spec_self_check import validate_truth_spec
    spec = yaml.safe_load((_THIS_DIR / "truth-spec.yaml").read_text(encoding="utf-8"))
    issues = validate_truth_spec(spec)
    if not issues:
        print("Truth Spec is self-consistent.")
    else:
        for i in issues:
            sev = i.get("severity", "error")
            print(f"[{sev.upper()}] {i.get('rule')}: {i.get('message')}")


async def cmd_cleanup(args):
    """Clean up test data."""
    from utils.db import get_pool, close_pool
    from cleanup import cleanup_all_test_data, cleanup_orphan_test_data, cleanup_worktrees, full_test_cleanup

    db_pool = await get_pool()

    if args.stats:
        from server import api_cleanup_stats
        stats = await api_cleanup_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False, default=str))
        await close_pool()
        return

    dry = args.dry_run
    if dry:
        print("[DRY RUN] No data will be deleted.\n")

    if args.all:
        if dry:
            async with db_pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM requirements WHERE external_id LIKE 'TEST-%'"
                )
            print(f"Would clean {total} test requirements")
            wt_path = Path("/tmp/a9-runtimes")
            if wt_path.exists():
                wt_dirs = [d for d in wt_path.iterdir() if d.is_dir() and d.name.startswith("wt-")]
                print(f"Would clean {len(wt_dirs)} worktree directories")
        else:
            db_result = await cleanup_all_test_data(db_pool)
            wt_result = cleanup_worktrees()
            print(f"Database: {json.dumps(db_result, ensure_ascii=False)}")
            print(f"Worktrees: {json.dumps(wt_result, ensure_ascii=False)}")

    elif args.req_id:
        if dry:
            print(f"Would clean req_id={args.req_id}")
        else:
            result = await full_test_cleanup(
                db_pool=db_pool, temporal_client=None,
                req_id=args.req_id, workflow_id=None, keep_data=False,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    elif args.orphans:
        if dry:
            async with db_pool.acquire() as conn:
                cutoff = datetime.now(timezone.utc)
                import datetime as dt_mod
                cutoff = cutoff - dt_mod.timedelta(hours=24)
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM requirements WHERE external_id LIKE 'TEST-%' AND created_at < $1",
                    cutoff,
                )
            print(f"Would clean {total} orphan requirements (>24h old)")
        else:
            result = await cleanup_orphan_test_data(db_pool, max_age_hours=24)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.worktrees:
        if dry:
            wt_path = Path("/tmp/a9-runtimes")
            if wt_path.exists():
                wt_dirs = [d for d in wt_path.iterdir() if d.is_dir() and d.name.startswith("wt-")]
                print(f"Would clean {len(wt_dirs)} worktree directories")
        else:
            result = cleanup_worktrees()
            print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print("Specify --all, --req-id, --orphans, --worktrees, or --stats")
        print("Use --dry-run to preview without deleting.")

    await close_pool()


async def cmd_export(args):
    """Export a run result."""
    from server import HISTORY
    for h in HISTORY:
        if h.get("run_id") == args.run_id:
            output = json.dumps(h, indent=2, ensure_ascii=False, default=str)
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                print(f"Exported to {args.output}")
            else:
                print(output)
            return
    print(f"Run {args.run_id} not found in history")


def main():
    parser = argparse.ArgumentParser(description="AI Native Pipeline Testing Tool")
    sub = parser.add_subparsers(dest="command")

    # run
    p_run = sub.add_parser("run", help="Run a full pipeline test")
    p_run.add_argument("--title", required=True, help="Requirement title")
    p_run.add_argument("--desc", default="", help="Requirement description")
    p_run.add_argument("--gate", choices=["auto", "manual"], default="auto")
    p_run.add_argument("--keep-data", action="store_true", help="Keep test data after run")
    p_run.add_argument("--export", help="Export result to JSON file")

    # diagnose
    p_diag = sub.add_parser("diagnose", help="Diagnose an existing req_id")
    p_diag.add_argument("--req-id", required=True)

    # infra
    sub.add_parser("infra", help="Run infrastructure checks only")

    # validate-spec
    sub.add_parser("validate-spec", help="Validate truth-spec.yaml self-consistency")

    # cleanup
    p_clean = sub.add_parser("cleanup", help="Clean up test data")
    p_clean.add_argument("--all", action="store_true")
    p_clean.add_argument("--req-id")
    p_clean.add_argument("--orphans", action="store_true")
    p_clean.add_argument("--worktrees", action="store_true")
    p_clean.add_argument("--stats", action="store_true")
    p_clean.add_argument("--dry-run", action="store_true")

    # export
    p_export = sub.add_parser("export", help="Export a run result")
    p_export.add_argument("--run-id", required=True)
    p_export.add_argument("--output", "-o", help="Output file path")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cmds = {
        "run": cmd_run,
        "diagnose": cmd_diagnose,
        "infra": cmd_infra,
        "validate-spec": cmd_validate_spec,
        "cleanup": cmd_cleanup,
        "export": cmd_export,
    }

    fn = cmds.get(args.command)
    if fn:
        asyncio.run(fn(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
