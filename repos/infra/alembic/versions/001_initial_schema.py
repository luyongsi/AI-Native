"""001_initial_schema

Revision: 001
Create Date: 2026-06-30

Initial schema matching init-db.sql: requirements, agent_activities,
gate_approvals, test_executions, loop_events, knowledge_chunks (pgvector).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── pgvector extension ──────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── requirements ────────────────────────────────────────────────────
    op.create_table(
        "requirements",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("external_id", sa.String(50), unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "priority",
            sa.String(5),
            nullable=False,
            server_default="P2",
        ),
        sa.Column("current_gate", sa.SmallInteger()),
        sa.Column("spec", postgresql.JSONB()),
        sa.Column("tasks", postgresql.JSONB()),
        sa.Column(
            "ai_completion",
            sa.SmallInteger(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "human_interventions",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "blocked",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column("block_reason", sa.Text()),
        sa.Column("version", sa.String(20)),
        sa.Column("source_type", sa.String(30)),
        sa.Column("source_payload", postgresql.JSONB()),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # ── agent_activities ────────────────────────────────────────────────
    op.create_table(
        "agent_activities",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", sa.String(50), nullable=False),
        sa.Column("agent_type", sa.String(30), nullable=False),
        sa.Column(
            "req_id",
            postgresql.UUID(),
            sa.ForeignKey("requirements.id"),
        ),
        sa.Column("task_id", sa.String(50)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_action", sa.Text()),
        sa.Column("tool_calls_json", postgresql.JSONB()),
        sa.Column("code_added", sa.Integer(), server_default=sa.text("0")),
        sa.Column("code_removed", sa.Integer(), server_default=sa.text("0")),
        sa.Column("anomaly", sa.String(30)),
        sa.Column("inner_loop", postgresql.JSONB()),
        sa.Column("session_id", sa.String(100)),
        sa.Column("cost_usd", sa.Numeric(10, 6)),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_activities_req", "agent_activities", ["req_id"]
    )
    op.create_index(
        "idx_activities_status", "agent_activities", ["status"]
    )

    # ── gate_approvals ──────────────────────────────────────────────────
    op.create_table(
        "gate_approvals",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "req_id",
            postgresql.UUID(),
            sa.ForeignKey("requirements.id"),
            nullable=False,
        ),
        sa.Column("gate", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("approver", sa.String(100)),
        sa.Column(
            "sla_deadline",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column("agent_reviews", postgresql.JSONB()),
        sa.Column("reject_reasons", postgresql.JSONB()),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True)),
    )
    op.create_index("idx_gate_req", "gate_approvals", ["req_id"])

    # ── test_executions ─────────────────────────────────────────────────
    op.create_table(
        "test_executions",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "req_id",
            postgresql.UUID(),
            sa.ForeignKey("requirements.id"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(50)),
        sa.Column("round", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("total_cases", sa.Integer(), server_default=sa.text("0")),
        sa.Column("passed", sa.Integer(), server_default=sa.text("0")),
        sa.Column("failed", sa.Integer(), server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), server_default=sa.text("0")),
        sa.Column("coverage", sa.Numeric(5, 2)),
        sa.Column("ai_generated_ratio", sa.Numeric(5, 2)),
        sa.Column("quality_score", postgresql.JSONB()),
        sa.Column("failed_cases", postgresql.JSONB()),
        sa.Column("traces", postgresql.JSONB()),
        sa.Column("visual_diffs", postgresql.JSONB()),
        sa.Column("vis_task_id", sa.String(50)),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_test_req", "test_executions", ["req_id"])

    # ── loop_events ─────────────────────────────────────────────────────
    op.create_table(
        "loop_events",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "req_id",
            postgresql.UUID(),
            sa.ForeignKey("requirements.id"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("participants", postgresql.JSONB()),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("max_round", sa.Integer(), nullable=False),
        sa.Column("escalation", sa.String(30)),
        sa.Column(
            "tripped",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column("fallback_action", sa.Text()),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    # ── knowledge_chunks (pgvector + full-text search) ──────────────────
    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            postgresql.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("doc_id", sa.String(100), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.String(30)),
        sa.Column("file_path", sa.String(500)),
        sa.Column("repo_path", sa.String(300)),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("project", sa.String(100)),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    # Add the vector column after table creation (custom PG type).
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN embedding vector(1024)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
        "ON knowledge_chunks "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_search "
        "ON knowledge_chunks "
        "USING GIN (search_vector)"
    )


def downgrade() -> None:
    # ── Drop indexes & tables in reverse dependency order ──────────────
    op.execute("DROP INDEX IF EXISTS idx_chunks_search")
    op.execute("DROP INDEX IF EXISTS idx_chunks_embedding")
    op.drop_table("knowledge_chunks")

    op.drop_table("loop_events")

    op.execute("DROP INDEX IF EXISTS idx_test_req")
    op.drop_table("test_executions")

    op.execute("DROP INDEX IF EXISTS idx_gate_req")
    op.drop_table("gate_approvals")

    op.execute("DROP INDEX IF EXISTS idx_activities_status")
    op.execute("DROP INDEX IF EXISTS idx_activities_req")
    op.drop_table("agent_activities")

    op.drop_table("requirements")

    # ── pgvector extension ──────────────────────────────────────────────
    op.execute("DROP EXTENSION IF EXISTS vector")
