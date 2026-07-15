"""migrate_phase3_schema Activity — 执行阶段三数据库变更。

在 Temporal Workflow 中作为一次性 Activity 调用，
事务内完成所有 ALTER + CREATE + INDEX 操作，失败自动回滚。
"""
import logging

import asyncpg
from temporalio import activity

logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql://ai_native:ai_native_dev@localhost:5432/ai_native"

# 阶段三 Migration SQL（单事务）
_MIGRATION_SQL = """
-- ============================================================
-- 阶段三 Migration SQL v1.0
-- 数据库: ai_native
-- 执行方式: 单事务，失败自动回滚
-- ============================================================

BEGIN;

-- ============================================================
-- 2.1 requirements 表扩展
-- ============================================================

-- 新增阶段三子状态字段
ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS tech_prep_status VARCHAR(30);

-- 新增阶段三内部修订计数
ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS tech_prep_revision_count INT DEFAULT 0;

-- 注释
COMMENT ON COLUMN requirements.tech_prep_status IS '阶段三子状态: decomposing|decomposed|test_ready|reviewing|revising|tech_prep_completed';
COMMENT ON COLUMN requirements.tech_prep_revision_count IS '阶段三内部修订计数（Gate2拒绝时+1，不改变cycle）';

-- 为 tech_prep_status 添加检查约束
ALTER TABLE requirements
    ADD CONSTRAINT chk_tech_prep_status
    CHECK (tech_prep_status IS NULL OR tech_prep_status IN (
        'decomposing', 'decomposed', 'test_ready', 'reviewing',
        'revising', 'tech_prep_completed'
    ));

-- ============================================================
-- 2.2 approvals 表扩展
-- ============================================================

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS a6_rework BOOLEAN DEFAULT true;

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS a7_rework BOOLEAN DEFAULT true;

COMMENT ON COLUMN approvals.a6_rework IS 'Gate2 reject 时是否需要 A6 返工（默认 true）';
COMMENT ON COLUMN approvals.a7_rework IS 'Gate2 reject 时是否需要 A7 返工（默认 true）';

-- ============================================================
-- 2.3 task_dags 新表
-- ============================================================

-- 先删除旧版 task_dags 表（infra/migrations/009_task_dags.sql 创建的旧表无 cycle 字段，
-- CREATE TABLE IF NOT EXISTS 不会重建，因此必须先 DROP 再 CREATE）
DROP TABLE IF EXISTS task_dags CASCADE;

CREATE TABLE task_dags (
    id                      BIGSERIAL PRIMARY KEY,
    req_id                  UUID NOT NULL
        REFERENCES requirements(id) ON DELETE CASCADE,
    cycle                   INT NOT NULL DEFAULT 0,
    version                 INT NOT NULL DEFAULT 1,
    dag_json                JSONB NOT NULL,
    node_count              INT,
    critical_path_length    INT,
    total_estimated_hours   NUMERIC(6,1),
    human_review_nodes      INT DEFAULT 0,
    source                  VARCHAR(20) DEFAULT 'llm',
    stage3_revision_count   INT DEFAULT 0,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uq_task_dags_req_cycle_version UNIQUE (req_id, cycle, version)
);

COMMENT ON TABLE task_dags IS 'A6 产出的任务 DAG，按 (req_id, cycle, version) 保留所有历史版本';
COMMENT ON COLUMN task_dags.version IS '修订版本号（Gate2打回后递增 或 A6↔A8对抗递增）';
COMMENT ON COLUMN task_dags.source IS 'llm | llm_no_mcp | fallback | timeout';
COMMENT ON COLUMN task_dags.stage3_revision_count IS 'A6↔A8对抗循环轮次计数（P1）';

CREATE INDEX IF NOT EXISTS idx_task_dags_req ON task_dags(req_id, cycle, version DESC);
CREATE INDEX IF NOT EXISTS idx_task_dags_created ON task_dags(req_id, created_at DESC);

-- ============================================================
-- 2.4 test_assets 表确认（A7 已建，此处确保字段完整）
-- ============================================================

-- 如果 test_assets 表不存在则创建
CREATE TABLE IF NOT EXISTS test_assets (
    id                      BIGSERIAL PRIMARY KEY,
    req_id                  UUID NOT NULL
        REFERENCES requirements(id) ON DELETE CASCADE,
    unit_tests              JSONB,
    integration_tests       JSONB,
    e2e_tests               JSONB,
    visual_tests            JSONB,
    coverage_targets        JSONB,
    total_cases             INT,
    priority_distribution   JSONB,
    source                  VARCHAR(50) DEFAULT 'a7_generator',
    version                 INT DEFAULT 1,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_test_assets_req ON test_assets(req_id, created_at DESC);

COMMIT;
"""

# 回滚脚本
_ROLLBACK_SQL = """
-- 阶段三 Migration 回滚脚本
BEGIN;

ALTER TABLE requirements DROP COLUMN IF EXISTS tech_prep_status;
ALTER TABLE requirements DROP COLUMN IF EXISTS tech_prep_revision_count;
ALTER TABLE approvals DROP COLUMN IF EXISTS a6_rework;
ALTER TABLE approvals DROP COLUMN IF EXISTS a7_rework;
DROP TABLE IF EXISTS task_dags CASCADE;
-- test_assets 表不删除（A7 已使用，属于长期表）

COMMIT;
"""


@activity.defn(name="migrate_phase3_schema")
async def migrate_phase3_schema(rollback: bool = False) -> dict:
    """执行阶段三 Migration SQL 或回滚脚本。

    Args:
        rollback: True 则执行回滚脚本，False 则执行正向迁移。

    Returns:
        dict with ok, rollback, note.
    """
    sql = _ROLLBACK_SQL if rollback else _MIGRATION_SQL
    action = "rollback" if rollback else "migration"

    activity.logger.info("migrate_phase3_schema: executing %s", action)

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute(sql)
            activity.logger.info("migrate_phase3_schema: %s completed", action)
            return {"ok": True, "rollback": rollback, "note": f"{action} executed successfully"}
        finally:
            await conn.close()
    except Exception as e:
        activity.logger.error("migrate_phase3_schema: %s failed: %s", action, e)
        return {"ok": False, "rollback": rollback, "note": f"{action} failed: {e}"}
